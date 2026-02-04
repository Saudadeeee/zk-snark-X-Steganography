"""
Hybrid DCT-DWT Coefficient Selector

Combines DCT coefficient analysis with DWT frequency mapping
to select the most stable coefficients for steganographic embedding.

Strategy: Only use coefficients that are:
1. In DWT mid-frequency regions (LH/HL)
2. Have |value| >= 3 (stable)
3. Not DC (position 0)
4. High texture or motion context
"""

import numpy as np
from typing import List, Tuple, Dict
from .dwt_analyzer import HaarDWTAnalyzer


class HybridCoefficientSelector:
    """
    Select DCT coefficients based on hybrid DCT-DWT analysis
    
    Selection criteria (in priority order):
    1. DWT region: LH/HL > LL > HH (avoid)
    2. Coefficient magnitude: |c| >= 3 best, >= 2 acceptable
    3. Position: Not DC (position 0)
    4. Context: High texture or motion (from context analyzer)
    """
    
    def __init__(self, dwt_analyzer: HaarDWTAnalyzer = None):
        """
        Initialize hybrid selector
        
        Args:
            dwt_analyzer: DWT analyzer instance (creates new if None)
        """
        self.dwt_analyzer = dwt_analyzer or HaarDWTAnalyzer(levels=2)
        
        # Selection weights for different regions
        self.region_weights = {
            'LH': 1.0,  # Best: horizontal edges
            'HL': 1.0,  # Best: vertical edges
            'LL': 0.6,  # Acceptable: smooth regions
            'HH': 0.0   # Avoid: high frequency
        }
    
    def select_coefficients(self, 
                          coefficients: List[Tuple[int, int, List[int]]],
                          macroblock_data: np.ndarray,
                          min_magnitude: int = 2,
                          max_coefficients: int = None) -> List[Tuple[int, int, int]]:
        """
        Select best coefficients for embedding using hybrid analysis
        
        Args:
            coefficients: List of (mb_idx, block_idx, coeffs) from CAVLC decoder
            macroblock_data: Raw macroblock pixel data for DWT analysis
            min_magnitude: Minimum |coefficient| value (default: 2)
            max_coefficients: Maximum number to select (None = unlimited)
        
        Returns:
            List of (mb_idx, block_idx, coeff_position) tuples
        """
        if not coefficients:
            return []
        
        # Analyze macroblock with DWT once (cache result)
        dwt_result = self.dwt_analyzer.analyze_macroblock(macroblock_data)
        
        # Pre-allocate arrays for vectorized processing
        max_coeffs_total = sum(len(c[2]) for c in coefficients)
        mb_indices = np.empty(max_coeffs_total, dtype=np.int32)
        block_indices = np.empty(max_coeffs_total, dtype=np.int32)
        positions = np.empty(max_coeffs_total, dtype=np.int32)
        values = np.empty(max_coeffs_total, dtype=np.int32)
        
        # Flatten all coefficients into arrays
        idx = 0
        for mb_idx, block_idx, coeff_list in coefficients:
            n = len(coeff_list)
            if n == 0:
                continue
            mb_indices[idx:idx+n] = mb_idx
            block_indices[idx:idx+n] = block_idx
            positions[idx:idx+n] = np.arange(n)
            values[idx:idx+n] = coeff_list
            idx += n
        
        # Trim to actual size
        mb_indices = mb_indices[:idx]
        block_indices = block_indices[:idx]
        positions = positions[:idx]
        values = values[:idx]
        
        # Vectorized filtering: magnitude >= min_magnitude
        magnitude_mask = np.abs(values) >= min_magnitude
        
        # Vectorized filtering: skip DC (position 0)
        dc_mask = positions != 0
        
        # Combine filters
        valid_mask = magnitude_mask & dc_mask
        
        # Apply filters
        mb_indices = mb_indices[valid_mask]
        block_indices = block_indices[valid_mask]
        positions = positions[valid_mask]
        values = values[valid_mask]
        
        if len(positions) == 0:
            return []
        
        # Vectorized region mapping (pre-compute for all positions)
        regions = np.array([
            self.dwt_analyzer.get_dwt_region_for_position(pos, mb_size=16)
            for pos in positions
        ])
        
        # Vectorized filtering: apply selection rules
        # Rule 2: Skip HH region
        hh_mask = regions != 'HH'
        
        # Apply HH filter
        mb_indices = mb_indices[hh_mask]
        block_indices = block_indices[hh_mask]
        positions = positions[hh_mask]
        values = values[hh_mask]
        regions = regions[hh_mask]
        
        if len(positions) == 0:
            return []
        
        # Vectorized score computation
        # Rule 3: |value| >= 2 already filtered above
        # Rule 4: texture >= 0.3 (using default texture=1.0, always passes)
        # Rule 5 & 6: Check coefficient strength by region
        
        # Vectorized magnitude scoring: log(|coeff| + 1) / log(256)
        magnitude_scores = np.log(np.abs(values) + 1) / np.log(256)
        
        # Vectorized region weights
        region_weights = np.array([
            self.region_weights.get(r, 0.0) for r in regions
        ], dtype=np.float32)
        
        # Context score (texture=1.0, motion=0.0 by default)
        context_score = 0.6 * 1.0 + 0.4 * 0.0  # = 0.6
        
        # Final scores
        scores = magnitude_scores * region_weights * context_score
        
        # Apply selection rules (vectorized)
        # Rule 5: Accept LH/HL with |value| >= 3
        lh_hl_mask = (regions == 'LH') | (regions == 'HL')
        rule5_mask = lh_hl_mask & (np.abs(values) >= 3)
        
        # Rule 6: Accept LL with |value| >= 5
        ll_mask = regions == 'LL'
        rule6_mask = ll_mask & (np.abs(values) >= 5)
        
        # Combine rules: must pass either rule 5 or rule 6
        valid_mask = rule5_mask | rule6_mask
        
        # Apply final filter
        mb_indices = mb_indices[valid_mask]
        block_indices = block_indices[valid_mask]
        positions = positions[valid_mask]
        scores = scores[valid_mask]

        
        if len(scores) == 0:
            return []
        
        # Sort by score (descending)
        sort_idx = np.argsort(-scores)  # Negative for descending
        
        # Limit to max_coefficients
        if max_coefficients is not None and len(sort_idx) > max_coefficients:
            sort_idx = sort_idx[:max_coefficients]
        
        # Return as tuples
        return [
            (int(mb_indices[i]), int(block_indices[i]), int(positions[i]))
            for i in sort_idx
        ]
    
    def compute_stability_score(self, 
                                coeff_value: int,
                                coeff_position: int,
                                dwt_region: str,
                                texture_score: float = 1.0,
                                motion_score: float = 0.0) -> float:
        """
        Compute stability score for a coefficient
        
        Score formula:
            score = magnitude_score * region_weight * context_score
        
        Where:
            magnitude_score = log(|coeff| + 1) / log(256)
            region_weight = region_weights[dwt_region]
            context_score = 0.6*texture + 0.4*motion
        
        Args:
            coeff_value: DCT coefficient value
            coeff_position: Position in block (0-15)
            dwt_region: DWT region ('LL', 'LH', 'HL', 'HH')
            texture_score: Texture complexity (0.0-1.0)
            motion_score: Motion magnitude (0.0-1.0)
        
        Returns:
            Stability score (0.0-1.0, higher = more stable)
        """
        # Magnitude score: logarithmic scaling (stronger coefficients better)
        magnitude_score = np.log(abs(coeff_value) + 1) / np.log(256)
        
        # Region weight: prioritize mid-frequency bands
        region_weight = self.region_weights.get(dwt_region, 0.0)
        
        # Context score: texture more important than motion
        context_score = 0.6 * texture_score + 0.4 * motion_score
        
        # Final score: product of all factors
        score = magnitude_score * region_weight * context_score
        
        # Clamp to [0.0, 1.0]
        return float(np.clip(score, 0.0, 1.0))
    
    def should_use_coefficient(self,
                              coeff_value: int,
                              coeff_position: int,
                              dwt_region: str,
                              texture_score: float = 1.0) -> bool:
        """
        Decision function: Should this coefficient be used?
        
        Rules:
        1. Skip DC (position 0) - always
        2. Skip HH region (high frequency) - unstable
        3. Skip |value| < 2 - too small, may flip to 0
        4. Skip low texture regions (< 0.3) - artifacts visible
        5. Accept LH/HL with |value| >= 3 - best candidates
        6. Accept LL with |value| >= 5 - cautiously use smooth regions
        
        Args:
            coeff_value: DCT coefficient value
            coeff_position: Position in zigzag order
            dwt_region: DWT sub-band ('LL', 'LH', 'HL', 'HH')
            texture_score: Texture complexity (0.0-1.0)
        
        Returns:
            True if coefficient should be used for embedding
        """
        # Rule 1: Skip DC
        if coeff_position == 0:
            return False
        
        # Rule 2: Skip high-frequency regions
        if dwt_region == 'HH':
            return False
        
        # Rule 3: Skip small coefficients
        if abs(coeff_value) < 2:
            return False
        
        # Rule 4: Skip low-texture regions
        if texture_score < 0.3:
            return False
        
        # Rule 5: Best candidates (mid-frequency edges)
        if dwt_region in ['LH', 'HL'] and abs(coeff_value) >= 3:
            return True
        
        # Rule 6: Smooth regions (only strong coefficients)
        if dwt_region == 'LL' and abs(coeff_value) >= 5:
            return True
        
        return False
    
    def create_coefficient_map(self,
                               coefficients: List[Tuple[int, int, List[int]]],
                               macroblock_data: np.ndarray) -> np.ndarray:
        """
        Create a binary map indicating usable coefficients
        
        Args:
            coefficients: List of (mb_idx, block_idx, coeffs)
            macroblock_data: Raw pixel data for DWT
        
        Returns:
            Binary map (1 = usable, 0 = skip)
        """
        # Analyze macroblock with DWT
        dwt_result = self.dwt_analyzer.analyze_macroblock(macroblock_data)
        
        # Initialize map with zeros (assume all unusable)
        total_coeffs = sum(len(coeffs) for _, _, coeffs in coefficients)
        coeff_map = np.zeros(total_coeffs, dtype=np.uint8)
        
        # Mark usable coefficients
        offset = 0
        for _, _, coeff_list in coefficients:
            for position, value in enumerate(coeff_list):
                # Map position to DWT region
                dwt_region = self.dwt_analyzer.get_dwt_region_for_position(
                    position, mb_size=16
                )
                
                # Check if usable
                if self.should_use_coefficient(value, position, dwt_region):
                    coeff_map[offset + position] = 1
            
            offset += len(coeff_list)
        
        return coeff_map
    
    def estimate_capacity(self, coefficient_map: np.ndarray) -> int:
        """
        Estimate embedding capacity based on selected coefficients
        
        Args:
            coefficient_map: Binary map from create_coefficient_map()
        
        Returns:
            Estimated capacity in bits
        """
        # TODO: Count usable coefficients
        return int(np.sum(coefficient_map))
    
    def _map_position_to_dwt(self, position: int, block_size: int = 16) -> str:
        """
        Map DCT coefficient position to DWT sub-band
        
        For 16x16 macroblock (256 coefficients):
        - Positions 0-63: LL quadrant
        - Positions 64-127: LH quadrant
        - Positions 128-191: HL quadrant
        - Positions 192-255: HH quadrant
        """
        quadrant_size = (block_size * block_size) // 4
        
        if position < quadrant_size:
            return 'LL'
        elif position < 2 * quadrant_size:
            return 'LH'
        elif position < 3 * quadrant_size:
            return 'HL'
        else:
            return 'HH'


# TODO: Week 3 - Day 6-7
# Integration with payload_embedder.py
# Benchmark stability improvement vs v2.0
# Expected: +30-40% stability score
