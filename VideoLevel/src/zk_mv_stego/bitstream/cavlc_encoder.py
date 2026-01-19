"""
CAVLC Encoder for H.264 Baseline Profile

Encodes quantized DCT coefficients into CAVLC bitstream
This is the REVERSE process of CAVLC decoder

Reference: ITU-T H.264 (2021) Section 9.2 - CAVLC
"""

import numpy as np
from typing import List, Tuple
from dataclasses import dataclass

from .bitstream_writer import BitstreamWriter
from .cavlc_tables import (
    find_coeff_token_code,
    find_total_zeros_code,
    find_run_before_code
)


# Zigzag scan order for 4x4 block
ZIGZAG_4X4 = [
    0,  1,  4,  8,
    5,  2,  3,  6,
    9, 12, 13, 10,
    7, 11, 14, 15
]


@dataclass
class BlockAnalysis:
    """Analysis of coefficient block for encoding"""
    total_coeffs: int
    trailing_ones: int
    trailing_signs: List[int]  # +1 or -1
    levels: List[int]  # All non-zero coefficients
    total_zeros: int
    runs: List[int]  # Run of zeros before each coefficient


class CAVLCEncoder:
    """
    Encode quantized DCT coefficients using CAVLC
    
    Reverse process of CAVLCDecoder:
    - Analyze coefficient block
    - Encode coeff_token
    - Encode trailing ones signs
    - Encode levels with adaptive suffix
    - Encode total_zeros
    - Encode run_before values
    """
    
    def __init__(self, writer: BitstreamWriter):
        self.writer = writer
    
    def encode_block_cavlc(self, coeffs: List[int], nC: int, max_num_coeff: int = 16, debug_key=None):
        """
        Encode one coefficient block using CAVLC
        
        Args:
            coeffs: Coefficient array in zigzag order (length max_num_coeff)
            nC: Neighbor prediction for context
            max_num_coeff: Maximum coefficients (16 for 4x4, 15 for chroma DC)
            debug_key: Optional (mb_idx, block_idx) for debugging
        """
        # Debug: log what we're encoding
        if debug_key and debug_key[0] == 0 and debug_key[1] in [16, 17, 18, 19]:
            non_zero = [c for c in coeffs if c != 0]
            print(f"      [CAVLC_ENC] Encoding MB{debug_key[0]} block{debug_key[1]}: {non_zero[:5]}...")
        
        # Analyze block
        analysis = self._analyze_block(coeffs, max_num_coeff)
        
        # 1. Encode coeff_token
        coeff_token_code = find_coeff_token_code(
            analysis.total_coeffs, 
            analysis.trailing_ones, 
            nC
        )
        self.writer.write_bit_string(coeff_token_code)
        
        # If all zeros, done
        if analysis.total_coeffs == 0:
            return
        
        # 2. Encode trailing ones signs
        for sign in analysis.trailing_signs:
            # 0 = positive, 1 = negative
            self.writer.write_bit(1 if sign < 0 else 0)
        
        # 3. Encode levels (excluding trailing ones)
        self._encode_levels(analysis)
        
        # 4. Encode total_zeros (if not all coefficients)
        if analysis.total_coeffs < max_num_coeff:
            total_zeros_code = find_total_zeros_code(
                analysis.total_zeros,
                analysis.total_coeffs
            )
            self.writer.write_bit_string(total_zeros_code)
        
        # 5. Encode run_before values
        self._encode_run_before(analysis)
    
    def _analyze_block(self, coeffs: List[int], max_num_coeff: int) -> BlockAnalysis:
        """
        Analyze coefficient block to extract encoding parameters
        
        Args:
            coeffs: Coefficients in zigzag order
            max_num_coeff: Maximum number of coefficients
        
        Returns:
            BlockAnalysis with all parameters
        """
        # Find non-zero coefficients
        non_zero_indices = [i for i, c in enumerate(coeffs) if c != 0]
        total_coeffs = len(non_zero_indices)
        
        if total_coeffs == 0:
            return BlockAnalysis(
                total_coeffs=0,
                trailing_ones=0,
                trailing_signs=[],
                levels=[],
                total_zeros=0,
                runs=[]
            )
        
        # Extract levels (values) in reverse zigzag order
        levels = [coeffs[i] for i in reversed(non_zero_indices)]
        
        # Count trailing ±1s (from highest frequency, max 3)
        trailing_ones = 0
        trailing_signs = []
        
        for level in levels:
            if abs(level) == 1 and trailing_ones < 3:
                trailing_ones += 1
                trailing_signs.append(level)
            else:
                break
        
        # Calculate total_zeros
        # total_zeros is the count of ALL zero coefficients up to (but not including)
        # the LAST non-zero coefficient position
        # For example: [5,0,0,0,...] has last_coeff at index 0, so total_zeros = 0
        # For example: [3,0,-2,0,...] has last_coeff at index 2, so total_zeros = 1 (the zero at index 1)
        # For example: [0,0,3,0,5,0,...] has last_coeff at index 4, so total_zeros = 3 (indices 0,1,3)
        
        # Actually, looking at H.264 spec more carefully:
        # total_zeros is number of zeros BEFORE the highest-frequency (last in zigzag) coefficient
        # Since we process in REVERSE order, this is zeros before the FIRST non-zero in forward scan
        
        # Simpler: total_zeros = (max_num_coeff - total_coeffs) - trailing_zeros_after_last_coeff
        # Even simpler: count zeros from position 0 to last non-zero position (inclusive)
        last_coeff_idx = non_zero_indices[-1]
        total_zeros = last_coeff_idx + 1 - total_coeffs
        
        # Calculate run_before for each coefficient
        runs = []
        prev_idx = -1
        
        for idx in non_zero_indices:
            run = idx - prev_idx - 1
            runs.append(run)
            prev_idx = idx
        
        # Reverse runs to match encoding order (high freq first)
        runs = list(reversed(runs))
        
        return BlockAnalysis(
            total_coeffs=total_coeffs,
            trailing_ones=trailing_ones,
            trailing_signs=trailing_signs,
            levels=levels,
            total_zeros=total_zeros,
            runs=runs
        )
    
    def _encode_levels(self, analysis: BlockAnalysis):
        """
        Encode coefficient levels with adaptive suffix length
        
        Reference: H.264 Section 9.2.2.1
        """
        # Skip trailing ones
        levels_to_encode = analysis.levels[analysis.trailing_ones:]
        
        if not levels_to_encode:
            return
        
        # Initialize suffix length
        if analysis.total_coeffs > 10 and analysis.trailing_ones < 3:
            suffixLength = 1
        else:
            suffixLength = 0
        
        for i, level in enumerate(levels_to_encode):
            abs_level = abs(level)
            
            # Calculate levelCode WITH sign embedded
            # H.264 Spec Section 9.2.2.1:
            # - Normal: levelCode = 2*abs_level - 2 + (sign ? 1 : 0)
            # - After 3 T1s: Use abs_level + 3 (bias correction)
            if i == 0 and analysis.trailing_ones == 3:
                # When 3 trailing ones exist, first level uses:
                # levelCode = 2*(abs_level + 3) - 6 + (sign ? 1 : 0)
                #           = 2*abs_level + 6 - 6 + sign
                #           = 2*abs_level + (sign ? 1 : 0)
                # This handles the case where 4th consecutive ±1 appears
                levelCode = (abs_level << 1)
                if level < 0:
                    levelCode += 1
            else:
                # levelCode = 2*abs_level - 2 + (sign ? 1 : 0)
                levelCode = (abs_level << 1) - 2
                if level < 0:
                    levelCode += 1
            
            # Ensure non-negative (should not happen with correct logic)
            if levelCode < 0:
                levelCode = 0
            
            # Determine levelPrefix and levelSuffixSize
            if suffixLength == 0:
                if levelCode < 14:
                    levelPrefix = levelCode
                    levelSuffixSize = 0
                    levelSuffix = 0
                else:
                    # Escape code with 4-bit suffix
                    levelPrefix = 14
                    levelSuffixSize = 4
                    levelSuffix = levelCode - 14
            else:
                # Normal case: split into prefix and suffix
                levelPrefix = levelCode >> suffixLength
                levelSuffix = levelCode & ((1 << suffixLength) - 1)
                levelSuffixSize = suffixLength
                
                # Check for escape
                if levelPrefix >= 15:
                    levelPrefix = 15
                    # Extended escape with larger suffix
                    levelSuffixSize = 4
                    levelSuffix = levelCode - (15 << suffixLength)
            
            # Write level_prefix (unary)
            self.writer.write_unary(levelPrefix)
            
            # Write level_suffix
            if levelSuffixSize > 0:
                self.writer.write_bits(levelSuffixSize, levelSuffix)
            
            # NO SIGN BIT - sign is embedded in levelCode!
            
            # Update suffixLength adaptively
            if suffixLength == 0:
                suffixLength = 1
            elif abs_level > (3 << (suffixLength - 1)) and suffixLength < 6:
                suffixLength += 1
    
    def _encode_run_before(self, analysis: BlockAnalysis):
        """
        Encode run_before values
        
        Args:
            analysis: Block analysis with runs
        """
        zeros_left = analysis.total_zeros
        
        # Encode all runs except the last (which is implicit)
        for run in analysis.runs[:-1]:
            run_before_code = find_run_before_code(run, zeros_left)
            self.writer.write_bit_string(run_before_code)
            zeros_left -= run
    
    def zigzag_scan_4x4(self, block_4x4: np.ndarray) -> List[int]:
        """
        Convert 4x4 block to zigzag-scanned 1D array
        
        Args:
            block_4x4: 4x4 numpy array
        
        Returns:
            16-element list in zigzag order
        """
        flat = block_4x4.flatten()
        return [int(flat[i]) for i in ZIGZAG_4X4]
    
    def inverse_zigzag_scan_4x4(self, zigzag: List[int]) -> np.ndarray:
        """
        Convert zigzag-scanned array back to 4x4 block
        
        Args:
            zigzag: 16-element list in zigzag order
        
        Returns:
            4x4 numpy array
        """
        block = np.zeros(16, dtype=int)
        for i, val in enumerate(zigzag):
            block[ZIGZAG_4X4[i]] = val
        
        return block.reshape((4, 4))


def test_encoder_basic():
    """
    Test basic CAVLC encoding
    """
    print("Testing CAVLC Encoder...")
    
    writer = BitstreamWriter()
    encoder = CAVLCEncoder(writer)
    
    # Test 1: All zeros
    print("\n[Test 1] All zeros block")
    coeffs = [0] * 16
    writer.reset()
    encoder.encode_block_cavlc(coeffs, nC=2)
    bits = writer.get_bit_count()
    print(f"  Encoded {bits} bits")
    
    # Test 2: Single coefficient
    print("\n[Test 2] Single coefficient [-9]")
    coeffs = [-9] + [0] * 15
    writer.reset()
    encoder.encode_block_cavlc(coeffs, nC=2)
    bits = writer.get_bit_count()
    print(f"  Encoded {bits} bits")
    
    # Test 3: Known block from decoder test
    print("\n[Test 3] Known block [-9, 16, -4, -3, 1, 1, 1]")
    # These are in ZIGZAG order already - positions matter!
    # According to decoder output: 7 coeffs with 4 zeros between them
    # Need to reconstruct proper zigzag positions
    coeffs = [0] * 16
    coeffs[0] = -9  # Position 0
    coeffs[1] = 16  # Position 1
    coeffs[3] = -4  # Position 3
    coeffs[4] = -3  # Position 4
    coeffs[8] = 1   # Position 8
    coeffs[11] = 1  # Position 11
    coeffs[15] = 1  # Position 15
    
    print(f"  Coeffs: {coeffs}")
    print(f"  Non-zero at indices: {[i for i, c in enumerate(coeffs) if c != 0]}")
    
    writer.reset()
    encoder.encode_block_cavlc(coeffs, nC=2)
    bits = writer.get_bit_count()
    bytes_data = writer.get_bytes()
    print(f"  Encoded {bits} bits ({len(bytes_data)} bytes)")
    print(f"  Bytes: {bytes_data.hex()}")
    
    # Test 4: Zigzag scan
    print("\n[Test 4] Zigzag scan")
    block_4x4 = np.array([
        [-9, 16,  0, -4],
        [ 0,  0, -3,  0],
        [ 0,  1,  0,  0],
        [ 1,  0,  0,  1]
    ])
    zigzag = encoder.zigzag_scan_4x4(block_4x4)
    print(f"  Zigzag: {zigzag}")
    
    # Reverse
    restored = encoder.inverse_zigzag_scan_4x4(zigzag)
    print(f"  Match: {np.array_equal(block_4x4, restored)}")
    
    print("\n[+] Basic encoder tests complete")


if __name__ == '__main__':
    test_encoder_basic()
