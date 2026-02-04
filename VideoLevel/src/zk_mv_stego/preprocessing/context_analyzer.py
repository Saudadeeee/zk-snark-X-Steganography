"""
Context Analyzer for Video Steganography

Analyzes texture complexity and motion characteristics to improve
coefficient selection quality. High-texture and high-motion regions
are more suitable for data embedding (less perceptually sensitive).

Week 5 Component - Phase 2: Embedding Enhancement
"""

import numpy as np
from typing import Dict, Tuple, Optional, List
import cv2


class ContextAnalyzer:
    """
    Analyze macroblock context for embedding suitability
    
    Features:
    - Texture analysis (Laplacian variance, local std)
    - Motion analysis (optical flow when available)
    - Context scoring (combine texture + motion)
    - Embedding suitability classification
    """
    
    def __init__(
        self,
        texture_weight: float = 0.6,
        motion_weight: float = 0.4,
        texture_threshold: float = 10.0,
        motion_threshold: float = 2.0
    ):
        """
        Initialize context analyzer
        
        Args:
            texture_weight: Weight for texture score (0-1)
            motion_weight: Weight for motion score (0-1)
            texture_threshold: Minimum variance for textured region
            motion_threshold: Minimum magnitude for high-motion region
        """
        if not np.isclose(texture_weight + motion_weight, 1.0):
            raise ValueError("Weights must sum to 1.0")
        
        self.texture_weight = texture_weight
        self.motion_weight = motion_weight
        self.texture_threshold = texture_threshold
        self.motion_threshold = motion_threshold
        
        # Cache for analysis results
        self._texture_cache: Dict[int, float] = {}
        self._motion_cache: Dict[int, float] = {}
    
    def analyze_texture(
        self,
        macroblock: np.ndarray,
        method: str = 'laplacian'
    ) -> float:
        """
        Compute texture complexity of macroblock
        
        Args:
            macroblock: 16x16 luma block (uint8)
            method: 'laplacian' or 'std' or 'combined'
        
        Returns:
            Texture score (0.0 - 1.0, higher = more textured)
        """
        if macroblock.shape != (16, 16):
            raise ValueError(f"Expected 16x16 macroblock, got {macroblock.shape}")
        
        if method == 'laplacian':
            return self._laplacian_variance(macroblock)
        elif method == 'std':
            return self._local_std(macroblock)
        elif method == 'combined':
            lap_score = self._laplacian_variance(macroblock)
            std_score = self._local_std(macroblock)
            return 0.7 * lap_score + 0.3 * std_score
        else:
            raise ValueError(f"Unknown method: {method}")
    
    def _laplacian_variance(self, block: np.ndarray) -> float:
        """
        Compute Laplacian variance (edge detection)
        
        Laplacian kernel:
        [[ 0  1  0]
         [ 1 -4  1]
         [ 0  1  0]]
        
        High variance = edges/texture present
        Low variance = smooth region
        
        Args:
            block: 16x16 grayscale block
        
        Returns:
            Normalized variance score (0.0 - 1.0)
        """
        # Apply Laplacian operator
        laplacian = cv2.Laplacian(block, cv2.CV_64F)
        
        # Compute variance
        variance = laplacian.var()
        
        # Normalize to 0-1 range (empirical max ~1000 for natural images)
        normalized = min(variance / 1000.0, 1.0)
        
        return float(normalized)
    
    def _local_std(self, block: np.ndarray) -> float:
        """
        Compute local standard deviation
        
        Measures variation within block (texture indicator)
        
        Args:
            block: 16x16 grayscale block
        
        Returns:
            Normalized std score (0.0 - 1.0)
        """
        # Compute standard deviation
        std = np.std(block.astype(np.float64))
        
        # Normalize to 0-1 range (max std ~127 for uint8)
        normalized = min(std / 127.0, 1.0)
        
        return float(normalized)
    
    def analyze_motion(
        self,
        current_mb: np.ndarray,
        previous_mb: Optional[np.ndarray] = None,
        motion_vector: Optional[Tuple[float, float]] = None
    ) -> float:
        """
        Compute motion characteristics
        
        Args:
            current_mb: Current macroblock (16x16)
            previous_mb: Previous frame macroblock (for optical flow)
            motion_vector: H.264 motion vector (dx, dy) if available
        
        Returns:
            Motion score (0.0 - 1.0, higher = more motion)
        """
        # Priority 1: Use H.264 motion vector if available
        if motion_vector is not None:
            dx, dy = motion_vector
            magnitude = np.sqrt(dx**2 + dy**2)
            # Normalize (typical MV range: 0-32 pixels)
            normalized = min(magnitude / 32.0, 1.0)
            return float(normalized)
        
        # Priority 2: Compute optical flow if previous frame available
        if previous_mb is not None:
            return self._compute_optical_flow(current_mb, previous_mb)
        
        # Priority 3: Return neutral score (no motion info)
        return 0.5
    
    def _compute_optical_flow(
        self,
        current: np.ndarray,
        previous: np.ndarray
    ) -> float:
        """
        Compute optical flow between consecutive macroblocks
        
        Uses Farneback dense optical flow algorithm
        
        Args:
            current: Current macroblock
            previous: Previous macroblock
        
        Returns:
            Motion magnitude score (0.0 - 1.0)
        """
        # Ensure uint8 type
        curr = current.astype(np.uint8)
        prev = previous.astype(np.uint8)
        
        # Compute dense optical flow
        flow = cv2.calcOpticalFlowFarneback(
            prev, curr,
            None,
            pyr_scale=0.5,
            levels=3,
            winsize=15,
            iterations=3,
            poly_n=5,
            poly_sigma=1.2,
            flags=0
        )
        
        # Compute flow magnitude
        magnitude = np.sqrt(flow[..., 0]**2 + flow[..., 1]**2)
        
        # Use mean magnitude as motion score
        mean_magnitude = np.mean(magnitude)
        
        # Normalize (typical flow magnitude: 0-16 pixels)
        normalized = min(mean_magnitude / 16.0, 1.0)
        
        return float(normalized)
    
    def compute_context_score(
        self,
        texture_score: float,
        motion_score: float
    ) -> float:
        """
        Combine texture and motion into single context score
        
        Args:
            texture_score: Texture complexity (0-1)
            motion_score: Motion magnitude (0-1)
        
        Returns:
            Combined context score (0.0 - 1.0)
        """
        weighted_score = (
            self.texture_weight * texture_score +
            self.motion_weight * motion_score
        )
        
        return float(weighted_score)
    
    def classify_region(
        self,
        texture_score: float,
        motion_score: float
    ) -> str:
        """
        Classify region based on texture and motion
        
        Args:
            texture_score: Texture complexity (0-1)
            motion_score: Motion magnitude (0-1)
        
        Returns:
            Region type: 'high-complexity', 'medium-complexity',
                        'low-complexity', 'smooth-static'
        """
        # High texture OR high motion = high complexity
        if texture_score > 0.7 or motion_score > 0.7:
            return 'high-complexity'
        
        # Medium texture AND medium motion
        elif texture_score > 0.4 and motion_score > 0.4:
            return 'medium-complexity'
        
        # Low texture AND low motion = avoid
        elif texture_score < 0.3 and motion_score < 0.3:
            return 'smooth-static'
        
        # Default
        else:
            return 'low-complexity'
    
    def get_embedding_suitability(
        self,
        macroblock: np.ndarray,
        previous_mb: Optional[np.ndarray] = None,
        motion_vector: Optional[Tuple[float, float]] = None,
        method: str = 'combined'
    ) -> Dict[str, float]:
        """
        Compute embedding suitability for macroblock
        
        Args:
            macroblock: Current macroblock (16x16)
            previous_mb: Previous frame macroblock (optional)
            motion_vector: H.264 motion vector (optional)
            method: Texture analysis method
        
        Returns:
            Dictionary with:
            - 'texture_score': Texture complexity (0-1)
            - 'motion_score': Motion magnitude (0-1)
            - 'context_score': Combined score (0-1)
            - 'classification': Region type
            - 'embedding_quality': Quality rating
        """
        # Analyze texture
        texture_score = self.analyze_texture(macroblock, method=method)
        
        # Analyze motion
        motion_score = self.analyze_motion(
            macroblock,
            previous_mb=previous_mb,
            motion_vector=motion_vector
        )
        
        # Combine scores
        context_score = self.compute_context_score(texture_score, motion_score)
        
        # Classify region
        classification = self.classify_region(texture_score, motion_score)
        
        # Determine embedding quality
        if context_score > 0.7:
            quality = 'excellent'
        elif context_score > 0.5:
            quality = 'good'
        elif context_score > 0.3:
            quality = 'fair'
        else:
            quality = 'poor'
        
        return {
            'texture_score': texture_score,
            'motion_score': motion_score,
            'context_score': context_score,
            'classification': classification,
            'embedding_quality': quality
        }
    
    def analyze_frame(
        self,
        luma_channel: np.ndarray,
        previous_luma: Optional[np.ndarray] = None,
        motion_vectors: Optional[Dict[int, Tuple[float, float]]] = None
    ) -> Dict[int, Dict[str, float]]:
        """
        Analyze all macroblocks in a frame
        
        Args:
            luma_channel: Full luma channel (H x W)
            previous_luma: Previous frame luma (optional)
            motion_vectors: Dict of {mb_index: (dx, dy)} (optional)
        
        Returns:
            Dictionary of {mb_index: suitability_dict}
        """
        height, width = luma_channel.shape
        
        # Validate dimensions (must be multiple of 16)
        if height % 16 != 0 or width % 16 != 0:
            raise ValueError(f"Frame size must be multiple of 16, got {height}x{width}")
        
        mb_height = height // 16
        mb_width = width // 16
        
        results = {}
        
        for mb_y in range(mb_height):
            for mb_x in range(mb_width):
                mb_index = mb_y * mb_width + mb_x
                
                # Extract macroblock
                y_start = mb_y * 16
                x_start = mb_x * 16
                macroblock = luma_channel[y_start:y_start+16, x_start:x_start+16]
                
                # Extract previous macroblock if available
                prev_mb = None
                if previous_luma is not None:
                    prev_mb = previous_luma[y_start:y_start+16, x_start:x_start+16]
                
                # Get motion vector if available
                mv = motion_vectors.get(mb_index) if motion_vectors else None
                
                # Analyze suitability
                suitability = self.get_embedding_suitability(
                    macroblock,
                    previous_mb=prev_mb,
                    motion_vector=mv
                )
                
                results[mb_index] = suitability
        
        return results
    
    def get_best_macroblocks(
        self,
        frame_analysis: Dict[int, Dict[str, float]],
        top_n: int = 100,
        min_quality: str = 'fair'
    ) -> List[int]:
        """
        Get indices of best macroblocks for embedding
        
        Args:
            frame_analysis: Results from analyze_frame()
            top_n: Number of top macroblocks to return
            min_quality: Minimum quality threshold
        
        Returns:
            List of macroblock indices sorted by suitability
        """
        quality_order = {'poor': 0, 'fair': 1, 'good': 2, 'excellent': 3}
        min_quality_level = quality_order[min_quality]
        
        # Filter by minimum quality
        filtered = {
            idx: data for idx, data in frame_analysis.items()
            if quality_order[data['embedding_quality']] >= min_quality_level
        }
        
        # Sort by context score (descending)
        sorted_indices = sorted(
            filtered.keys(),
            key=lambda idx: filtered[idx]['context_score'],
            reverse=True
        )
        
        # Return top N
        return sorted_indices[:top_n]
    
    def clear_cache(self):
        """Clear cached analysis results"""
        self._texture_cache.clear()
        self._motion_cache.clear()
