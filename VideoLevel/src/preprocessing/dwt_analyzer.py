"""
Haar Discrete Wavelet Transform (DWT) Analyzer

Performs 2-level Haar DWT on macroblocks to identify frequency regions.
Used to avoid embedding in high-frequency areas that are unstable.

Reference: "DWT-DCT-SVD Based Steganography" (Kumar et al., 2018)
"""

import numpy as np
from typing import Dict, Tuple, List


class HaarDWTAnalyzer:
    """
    Haar Wavelet Transform analyzer for macroblock frequency classification
    
    Sub-bands after 2-level DWT:
    - LL (Low-Low): Approximation coefficients (smooth regions)
    - LH (Low-High): Horizontal edge details
    - HL (High-Low): Vertical edge details
    - HH (High-High): Diagonal details (AVOID for embedding)
    
    Embedding strategy:
    - LL: Use cautiously (only strong coefficients)
    - LH, HL: BEST for embedding (edge information, stable)
    - HH: AVOID (easily destroyed by quantization)
    """
    
    def __init__(self, levels: int = 2):
        """
        Initialize Haar DWT analyzer
        
        Args:
            levels: Number of decomposition levels (default: 2)
        """
        self.levels = levels
        
    def analyze_macroblock(self, mb_data: np.ndarray) -> Dict[str, np.ndarray]:
        """
        Perform Haar DWT on a macroblock (16x16)
        
        Args:
            mb_data: Macroblock data (16 x 16 or 8 x 8)
        
        Returns:
            Dictionary with sub-bands:
            For 2-level DWT:
            {
                'LL2': 2nd level approximation (4x4),
                'LH2': 2nd level horizontal (4x4),
                'HL2': 2nd level vertical (4x4),
                'HH2': 2nd level diagonal (4x4),
                'LH1': 1st level horizontal (8x8),
                'HL1': 1st level vertical (8x8),
                'HH1': 1st level diagonal (8x8)
            }
        """
        # Ensure float type for computation
        mb_float = mb_data.astype(np.float32)
        
        # Level 1: Full decomposition
        level1 = self._haar_transform_2d(mb_float)
        
        if self.levels == 1:
            return level1
        
        # Level 2: Decompose LL sub-band further
        level2 = self._haar_transform_2d(level1['LL'])
        
        # Return all sub-bands with level indicators
        return {
            'LL2': level2['LL'],
            'LH2': level2['LH'],
            'HL2': level2['HL'],
            'HH2': level2['HH'],
            'LH1': level1['LH'],
            'HL1': level1['HL'],
            'HH1': level1['HH']
        }
    
    def compute_energy_map(self, dwt_coeffs: Dict[str, np.ndarray]) -> Dict[str, float]:
        """
        Compute energy distribution across frequency bands
        
        Energy = sum of squared coefficients (variance)
        
        Args:
            dwt_coeffs: DWT coefficients from analyze_macroblock()
        
        Returns:
            Dictionary of energy values:
            {
                'LL2': energy_ll2,
                'LH2': energy_lh2,
                ...,
                'total': total_energy
            }
        """
        energy_map = {}
        total_energy = 0.0
        
        for band_name, coeffs in dwt_coeffs.items():
            # Energy = variance (captures information content)
            energy = float(np.var(coeffs))
            energy_map[band_name] = energy
            total_energy += energy
        
        energy_map['total'] = total_energy
        
        return energy_map
    
    def classify_frequency_region(self, energy_map: Dict[str, float]) -> str:
        """
        Classify macroblock based on frequency distribution
        
        Classification rules:
        - 'low': Dominant energy in LL (smooth region)
        - 'mid': Dominant energy in LH/HL (edge region) - BEST for embedding
        - 'high': Dominant energy in HH (complex texture) - AVOID
        
        Args:
            energy_map: Energy distribution from compute_energy_map()
        
        Returns:
            Classification: 'low' | 'mid' | 'high'
        """
        total = energy_map.get('total', 0.0)
        if total == 0:
            return 'low'  # Flat region
        
        # Calculate energy ratios
        ll_energy = energy_map.get('LL2', 0.0) + energy_map.get('LL1', 0.0)
        lh_energy = energy_map.get('LH2', 0.0) + energy_map.get('LH1', 0.0)
        hl_energy = energy_map.get('HL2', 0.0) + energy_map.get('HL1', 0.0)
        hh_energy = energy_map.get('HH2', 0.0) + energy_map.get('HH1', 0.0)
        
        mid_energy = lh_energy + hl_energy
        
        # Ratio-based classification
        ll_ratio = ll_energy / total
        mid_ratio = mid_energy / total
        hh_ratio = hh_energy / total
        
        # Classification thresholds
        if hh_ratio > 0.4:
            return 'high'  # High-frequency dominant (complex texture)
        elif mid_ratio > 0.3:
            return 'mid'   # Mid-frequency dominant (edges) - BEST
        else:
            return 'low'   # Low-frequency dominant (smooth)
    
    def get_dwt_region_for_position(self, position: int, mb_size: int = 16) -> str:
        """
        Determine which DWT sub-band a DCT coefficient position belongs to
        
        For a 16x16 macroblock split into 4x4 blocks:
        - Positions 0-63: Top-left quadrant (LL region)
        - Positions 64-127: Top-right quadrant (LH region)
        - Positions 128-191: Bottom-left quadrant (HL region)
        - Positions 192-255: Bottom-right quadrant (HH region)
        
        Args:
            position: DCT coefficient position (0-255 for 16x16 MB)
            mb_size: Macroblock size (default: 16)
        
        Returns:
            Region: 'LL' | 'LH' | 'HL' | 'HH'
        """
        # Convert position to (row, col)
        row = position // mb_size
        col = position % mb_size
        
        # Determine quadrant (Level 1 DWT)
        mid = mb_size // 2
        
        if row < mid and col < mid:
            return 'LL'
        elif row < mid and col >= mid:
            return 'LH'
        elif row >= mid and col < mid:
            return 'HL'
        else:
            return 'HH'
    
    def _haar_transform_1d(self, data: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        1D Haar wavelet transform
        
        Formula:
            approximation[i] = (data[2i] + data[2i+1]) / sqrt(2)
            detail[i] = (data[2i] - data[2i+1]) / sqrt(2)
        
        Args:
            data: 1D array (even length)
        
        Returns:
            (approximation, detail) coefficients
        """
        n = len(data)
        if n % 2 != 0:
            raise ValueError(f"Data length must be even, got {n}")
        
        # Haar wavelet coefficients
        sqrt2 = np.sqrt(2)
        
        # Approximation (low-pass): average of pairs
        approx = (data[0::2] + data[1::2]) / sqrt2
        
        # Detail (high-pass): difference of pairs
        detail = (data[0::2] - data[1::2]) / sqrt2
        
        return approx, detail
    
    def _haar_transform_2d(self, data: np.ndarray) -> Dict[str, np.ndarray]:
        """
        2D Haar wavelet transform (separable) - OPTIMIZED
        
        Steps:
        1. Apply 1D transform to all rows simultaneously (vectorized)
        2. Apply 1D transform to all columns simultaneously (vectorized)
        3. Result: 4 sub-bands (LL, LH, HL, HH)
        
        Args:
            data: 2D array (N x N)
        
        Returns:
            Dictionary with 4 sub-bands
        """
        h, w = data.shape
        if h % 2 != 0 or w % 2 != 0:
            raise ValueError(f"Dimensions must be even, got {h}x{w}")
        
        sqrt2 = np.sqrt(2)
        
        # Step 1: Vectorized row-wise transform
        # Split into even and odd columns
        even_cols = data[:, 0::2]
        odd_cols = data[:, 1::2]
        
        # Compute approximation and detail for all rows at once
        row_approx = (even_cols + odd_cols) / sqrt2
        row_detail = (even_cols - odd_cols) / sqrt2
        
        # Concatenate horizontally: [approx | detail]
        row_transformed = np.hstack([row_approx, row_detail])
        
        # Step 2: Vectorized column-wise transform
        # Split into even and odd rows
        even_rows = row_transformed[0::2, :]
        odd_rows = row_transformed[1::2, :]
        
        # Compute approximation and detail for all columns at once
        col_approx = (even_rows + odd_rows) / sqrt2
        col_detail = (even_rows - odd_rows) / sqrt2
        
        # Concatenate vertically: [[approx], [detail]]
        result = np.vstack([col_approx, col_detail])
        
        # Step 3: Extract 4 quadrants (sub-bands)
        mid_h = h // 2
        mid_w = w // 2
        
        return {
            'LL': result[:mid_h, :mid_w],  # Approximation (low-low)
            'LH': result[:mid_h, mid_w:],  # Horizontal detail (low-high)
            'HL': result[mid_h:, :mid_w],  # Vertical detail (high-low)
            'HH': result[mid_h:, mid_w:]   # Diagonal detail (high-high)
        }
    
    def _inverse_haar_1d(self, approx: np.ndarray, detail: np.ndarray) -> np.ndarray:
        """
        Inverse 1D Haar transform - OPTIMIZED
        
        Formula:
            data[2i] = (approx[i] + detail[i]) / sqrt(2)
            data[2i+1] = (approx[i] - detail[i]) / sqrt(2)
        """
        sqrt2 = np.sqrt(2)
        
        # Vectorized computation
        even_data = (approx + detail) / sqrt2
        odd_data = (approx - detail) / sqrt2
        
        # Interleave using column_stack and ravel
        n = len(approx)
        data = np.empty(n * 2, dtype=np.float32)
        data[0::2] = even_data
        data[1::2] = odd_data
        
        return data

    def get_stable_regions(self, dwt_coeffs: Dict[str, np.ndarray], 
                          energy_map: Dict[str, float],
                          threshold: float = 10.0) -> List[str]:
        """
        Identify stable DWT regions suitable for embedding
        
        Stability criteria:
        1. Energy > threshold (sufficient detail to hide data)
        2. Not HH band (too unstable during compression)
        3. Prefer LH/HL (mid-frequency, robust)
        
        Args:
            dwt_coeffs: DWT sub-bands
            energy_map: Energy values
            threshold: Minimum energy for embedding (default: 10.0)
        
        Returns:
            List of stable band names, e.g., ['LH1', 'HL1', 'LH2']
        """
        stable = []
        
        for band_name in dwt_coeffs.keys():
            energy = energy_map.get(band_name, 0.0)
            
            # Skip HH bands (unstable)
            if 'HH' in band_name:
                continue
            
            # Require minimum energy
            if energy < threshold:
                continue
            
            stable.append(band_name)
        
        # Sort by priority: LH/HL > LL
        def priority(band):
            if 'LH' in band or 'HL' in band:
                return 2  # Best for embedding
            elif 'LL' in band:
                return 1  # Use cautiously
            else:
                return 0
        
        stable.sort(key=priority, reverse=True)
        
        return stable
    
    def reconstruct_from_dwt(self, dwt_coeffs: Dict[str, np.ndarray], 
                            levels: int = 2) -> np.ndarray:
        """
        Inverse 2D DWT (reconstruction for visualization)
        
        Args:
            dwt_coeffs: DWT sub-bands from analyze_macroblock()
            levels: Number of decomposition levels used
        
        Returns:
            Reconstructed macroblock
        """
        if levels == 2:
            # Reconstruct level 2 LL from its sub-bands
            level2_ll = self._inverse_haar_2d(
                dwt_coeffs['LL2'],
                dwt_coeffs['LH2'],
                dwt_coeffs['HL2'],
                dwt_coeffs['HH2']
            )
            
            # Reconstruct full macroblock from level 1 sub-bands
            return self._inverse_haar_2d(
                level2_ll,
                dwt_coeffs['LH1'],
                dwt_coeffs['HL1'],
                dwt_coeffs['HH1']
            )
        else:
            # Single level reconstruction
            return self._inverse_haar_2d(
                dwt_coeffs['LL'],
                dwt_coeffs['LH'],
                dwt_coeffs['HL'],
                dwt_coeffs['HH']
            )
    
    def _inverse_haar_2d(self, LL: np.ndarray, LH: np.ndarray,
                        HL: np.ndarray, HH: np.ndarray) -> np.ndarray:
        """
        Inverse 2D Haar transform - OPTIMIZED
        
        Args:
            LL, LH, HL, HH: Four sub-bands (same size, e.g., 4x4)
        
        Returns:
            Reconstructed 2D array (2x size of input bands, e.g., 8x8)
        """
        h, w = LL.shape
        sqrt2 = np.sqrt(2)
        
        # Step 1: Inverse column-wise transform (vectorized)
        # Reconstruct left half columns (LL + HL)
        even_rows_left = (LL + HL) / sqrt2
        odd_rows_left = (LL - HL) / sqrt2
        
        # Reconstruct right half columns (LH + HH)
        even_rows_right = (LH + HH) / sqrt2
        odd_rows_right = (LH - HH) / sqrt2
        
        # Interleave rows: stack even and odd rows
        left_cols = np.empty((h * 2, w), dtype=np.float32)
        left_cols[0::2, :] = even_rows_left
        left_cols[1::2, :] = odd_rows_left
        
        right_cols = np.empty((h * 2, w), dtype=np.float32)
        right_cols[0::2, :] = even_rows_right
        right_cols[1::2, :] = odd_rows_right
        
        # Step 2: Inverse row-wise transform (vectorized)
        # Reconstruct even columns
        even_cols = (left_cols + right_cols) / sqrt2
        odd_cols = (left_cols - right_cols) / sqrt2
        
        # Interleave columns
        result = np.empty((h * 2, w * 2), dtype=np.float32)
        result[:, 0::2] = even_cols
        result[:, 1::2] = odd_cols
        
        return result


# TODO: Week 2 - Day 6-7
# Create visualization tool for DWT sub-bands
# Add unit tests in tests/test_dwt_analyzer.py
