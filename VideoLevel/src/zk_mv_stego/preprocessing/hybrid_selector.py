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
        selected = []
        
        # Analyze macroblock with DWT to get frequency regions
        dwt_result = self.dwt_analyzer.analyze_macroblock(macroblock_data)
        
        # Process each 4x4 block
        for mb_idx, block_idx, coeff_list in coefficients:
            # Skip if no coefficients
            if not coeff_list:
                continue
            
            # Evaluate each coefficient in the block
            for position, value in enumerate(coeff_list):
                # Skip if below minimum magnitude
                if abs(value) < min_magnitude:
                    continue
                
                # Map position to DWT region
                dwt_region = self.dwt_analyzer.get_dwt_region_for_position(
                    position, mb_size=16
                )
                
                # Check if coefficient should be used
                if self.should_use_coefficient(value, position, dwt_region):
                    # Compute stability score
                    score = self.compute_stability_score(
                        value, position, dwt_region
                    )
                    
                    selected.append({
                        'mb_idx': mb_idx,
                        'block_idx': block_idx,
                        'position': position,
                        'score': score,
                        'value': value
                    })
        
        # Sort by stability score (descending)
        selected.sort(key=lambda x: x['score'], reverse=True)
        
        # Limit to max_coefficients if specified
        if max_coefficients is not None:
            selected = selected[:max_coefficients]
        
        # Return as tuples (mb_idx, block_idx, position)
        return [(s['mb_idx'], s['block_idx'], s['position']) for s in selected]
    
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
