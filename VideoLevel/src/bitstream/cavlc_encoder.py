"""
CAVLC Encoder for H.264 Baseline Profile

Encodes quantized DCT coefficients into CAVLC bitstream
This is the REVERSE process of CAVLC decoder

Reference: ITU-T H.264 (2021) Section 9.2 - CAVLC
"""

import numpy as np
from typing import List, Tuple
from dataclasses import dataclass

from .bitstream_io import BitstreamWriter
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
    total_coeffs: int  # Actual non-zero count for coeff_token
    total_coeffs_for_suffix: int  # For suffixLength (may use override)
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
    
    def encode_block_cavlc(self, coeffs: List[int], nC: int, max_num_coeff: int = 16,
                          debug_key=None, override_total_coeffs: int = None,
                          override_trailing_ones: int = None):
        """
        Encode one coefficient block using CAVLC

        Args:
            coeffs: Coefficient array in zigzag order (length max_num_coeff)
            nC: Neighbor prediction for context
            max_num_coeff: Maximum coefficients (16 for 4x4, 15 for chroma DC)
            debug_key: Optional (mb_idx, block_idx) for debugging
            override_total_coeffs: Override for total_coeffs (for re-encoding with preserved suffixLength)
            override_trailing_ones: Override T1 count to match original decoder's T1 (prevents
                                    encoder from choosing a higher T1 than the original)
        """
        # Analyze block
        analysis = self._analyze_block(coeffs, max_num_coeff, override_total_coeffs=override_total_coeffs,
                                       override_trailing_ones=override_trailing_ones)
        
        # DEBUG: Show encoding parameters for MB 0 and MB 309 (frame 0 and frame 1)
        if debug_key and (debug_key[0] == 0 or debug_key[0] == 309):
            print(f"[ENC_DEBUG] Block {debug_key}: total_coeffs={analysis.total_coeffs}, "
                  f"total_coeffs_for_suffix={analysis.total_coeffs_for_suffix}, "
                  f"trailing_ones={analysis.trailing_ones}, total_zeros={analysis.total_zeros}")
            print(f"  Override: {override_total_coeffs}, nC={nC}")
        
        # Track bit position before encoding
        bits_before = len(self.writer.get_bits_as_list()) if hasattr(self.writer, 'get_bits_as_list') else 0
        
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
            # DEBUG for first block
            if debug_key and debug_key[0] == 0 and debug_key[1] == 0:
                print(f"      [CAVLC_ENC] total_zeros={analysis.total_zeros}, total_coeffs={analysis.total_coeffs}, max_num_coeff={max_num_coeff}")
                print(f"      [CAVLC_ENC] Constraint: total_zeros <= {max_num_coeff - analysis.total_coeffs}")
            
            # Validate total_zeros is within valid range for VLC tables
            # Correct formula: max total_zeros = max_num_coeff - TC
            # (there are TC non-zero coefficients, so at most max_num_coeff-TC zeros)
            max_tz = max_num_coeff - analysis.total_coeffs
            if analysis.total_zeros > max_tz:
                # This should not happen after our validation in _analyze_block,
                # but add safety check anyway
                print(f"      [WARN] total_zeros ({analysis.total_zeros}) > max ({max_tz}), clamping")
                analysis.total_zeros = max_tz
            elif analysis.total_zeros < 0:
                print(f"      [WARN] total_zeros ({analysis.total_zeros}) < 0, setting to 0")
                analysis.total_zeros = 0
            
            total_zeros_code = find_total_zeros_code(
                analysis.total_zeros,
                analysis.total_coeffs
            )
            self.writer.write_bit_string(total_zeros_code)
        
        # 5. Encode run_before values
        self._encode_run_before(analysis)
    
    def _analyze_block(self, coeffs: List[int], max_num_coeff: int, override_total_coeffs: int = None,
                       override_trailing_ones: int = None) -> BlockAnalysis:
        """
        Analyze coefficient block to extract encoding parameters

        Args:
            coeffs: Coefficients in zigzag order
            max_num_coeff: Maximum number of coefficients
            override_total_coeffs: If provided, use this total_coeffs for suffixLength calculation
                                   (used when re-encoding modified blocks to preserve bit length)
            override_trailing_ones: If provided, force this T1 count (capped at actual trailing ±1 count).
                                    Used by BitstreamPatcher to match original encoder's T1 choice.

        Returns:
            BlockAnalysis with all parameters
        """
        # CRITICAL FIX: Strip trailing zeros BEFORE processing
        # H.264 CAVLC only encodes coefficients up to the last non-zero
        # Trailing zeros are implicit (not encoded in bitstream)
        last_nonzero_idx = -1
        for i in range(len(coeffs) - 1, -1, -1):
            if coeffs[i] != 0:
                last_nonzero_idx = i
                break
        
        # If all coefficients are zero
        if last_nonzero_idx == -1:
            return BlockAnalysis(
                total_coeffs=0,
                total_coeffs_for_suffix=0,
                trailing_ones=0,
                trailing_signs=[],
                levels=[],
                total_zeros=0,
                runs=[]
            )
        
        # Only process coefficients up to last non-zero (inclusive)
        # This excludes trailing zeros which are NOT encoded in CAVLC
        active_coeffs = coeffs[:last_nonzero_idx + 1]
        
        # Find non-zero coefficients within active range
        non_zero_indices = [i for i, c in enumerate(active_coeffs) if c != 0]
        
        # CRITICAL: For re-encoding modified blocks, use override_total_coeffs for suffixLength
        # but actual total_coeffs for coeff_token encoding
        actual_total_coeffs = len(non_zero_indices)  # For coeff_token
        total_coeffs_for_suffix = override_total_coeffs if override_total_coeffs is not None else actual_total_coeffs
        
        # Sanity check (should never happen after stripping trailing zeros)
        if actual_total_coeffs == 0:
            return BlockAnalysis(
                total_coeffs=0,
                total_coeffs_for_suffix=0,
                trailing_ones=0,
                trailing_signs=[],
                levels=[],
                total_zeros=0,
                runs=[]
            )
        
        # Extract levels (values) in reverse zigzag order
        levels = [active_coeffs[i] for i in reversed(non_zero_indices)]
        
        # Count trailing ±1s (from highest frequency, max 3)
        trailing_ones = 0
        trailing_signs = []

        for level in levels:
            if abs(level) == 1 and trailing_ones < 3:
                trailing_ones += 1
                trailing_signs.append(level)
            else:
                break

        # Apply override_trailing_ones if provided
        # Cap at the actual count (can't claim more T1s than exist)
        if override_trailing_ones is not None:
            capped = min(override_trailing_ones, trailing_ones)
            trailing_ones = capped
            trailing_signs = trailing_signs[:capped]
        
        # Calculate total_zeros (H.264 Section 9.2.1)
        # total_zeros = number of zero-valued coefficients BEFORE the last non-zero coefficient
        # This is the number of zeros within the active range (already stripped trailing zeros)
        # = (last_active_position + 1) - total_coeffs
        # = len(active_coeffs) - total_coeffs
        # 
        # Example: [5,0,0,3]     -> total_coeffs=2, total_zeros=2 (positions 1,2)
        # Example: [0,0,5]       -> total_coeffs=1, total_zeros=2 (positions 0,1)
        # Example: [5]           -> total_coeffs=1, total_zeros=0
        # Example: [5,0,0,3,0,0,0,0] -> strip to [5,0,0,3], total_coeffs=2, total_zeros=2
        
        # Calculate run_before for each coefficient
        runs = []
        prev_idx = -1
        
        for idx in non_zero_indices:
            run = idx - prev_idx - 1
            runs.append(run)
            prev_idx = idx
        
        # Reverse runs to match encoding order (high freq first)
        runs = list(reversed(runs))
        
        # total_zeros = number of zeros within active coefficient range
        # = (length of active range) - (number of non-zero coeffs)
        # = len(active_coeffs) - total_coeffs
        # By definition: total_zeros = sum(runs)
        total_zeros = sum(runs)
        
        # VALIDATION: For active_coeffs of length N with actual_total_coeffs non-zero values:
        # max_total_zeros = N - actual_total_coeffs
        # Since we stripped trailing zeros, N = last_nonzero_idx + 1
        max_total_zeros = len(active_coeffs) - actual_total_coeffs
        
        # Sanity check: total_zeros should equal max by construction
        # (since active_coeffs has no trailing zeros)
        if total_zeros != max_total_zeros:
            print(f"[WARN] total_zeros mismatch: calculated={total_zeros}, max={max_total_zeros}")
            print(f"  active_coeffs length: {len(active_coeffs)}, actual_total_coeffs: {actual_total_coeffs}")
            print(f"  runs: {runs}, sum: {sum(runs)}")
        
        # Validate and clamp total_zeros ONLY if it will be encoded
        # (i.e., when actual_total_coeffs < max_num_coeff)
        # When all coefficients are non-zero (actual_total_coeffs == max_num_coeff),
        # total_zeros is not encoded, so no VLC constraint applies
        if actual_total_coeffs < max_num_coeff:
            # VLC table constraint: max total_zeros = max_num_coeff - TC
            vlc_max = max_num_coeff - actual_total_coeffs
            if total_zeros > vlc_max:
                print(f"[WARN] total_zeros ({total_zeros}) > VLC max ({vlc_max}) - clamping")
                # This should not happen after stripping trailing zeros
                # But clamp just in case
                excess = total_zeros - vlc_max
                total_zeros = vlc_max
                
                # Adjust runs to maintain sum = clamped total_zeros
                for i in range(len(runs) - 1, -1, -1):
                    if excess == 0:
                        break
                    reduction = min(runs[i], excess)
                    runs[i] -= reduction
                    excess -= reduction
        
        return BlockAnalysis(
            total_coeffs=actual_total_coeffs,  # Actual count for coeff_token
            total_coeffs_for_suffix=total_coeffs_for_suffix,  # Original or actual for suffixLength
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
        
        # Initialize suffix length per H.264 Section 9.2.2.1 EXACTLY
        # CRITICAL: Must match H.264 spec precisely for round-trip encoding!
        #
        # H.264 spec initialization:
        # if( TotalCoeff( coeff_token ) > 10 )
        #     suffixLength = 1
        # else
        #     suffixLength = 0
        # if( TotalCoeff( coeff_token ) > 3 && TrailingOnes( coeff_token ) == 3 )
        #     suffixLength++
        
        # Use total_coeffs_for_suffix (not total_coeffs) to preserve bit length
        # when re-encoding modified blocks with override_total_coeffs
        if analysis.total_coeffs_for_suffix > 10:
            suffixLength = 1
        else:
            suffixLength = 0
        
        # Special case: if total_coeffs > 3 and all 3 trailing ones present
        if analysis.total_coeffs_for_suffix > 3 and analysis.trailing_ones == 3:
            suffixLength += 1
        
        for i, level in enumerate(levels_to_encode):
            abs_level = abs(level)
            sign = 1 if level < 0 else 0
            
            # Calculate levelCode WITH sign embedded (H.264 Section 9.2.2.1 Table 9-6)
            if i == 0 and analysis.trailing_ones == 3:
                levelCode = (abs_level - 2) * 2 + sign
            else:
                levelCode = (abs_level - 1) * 2 + sign
            
            # suffixLength should already be set to avoid gaps for all levels in block
            
            # Determine levelPrefix and levelSuffixSize (H.264 Section 9.2.2.1)
            # Determine levelPrefix and levelSuffixSize (H.264 Section 9.2.2.1)
            if suffixLength == 0:
                if levelCode < 14:
                    levelPrefix = levelCode
                    levelSuffixSize = 0
                    levelSuffix = 0
                elif levelCode < 30:
                    levelPrefix = 14
                    levelSuffixSize = 4
                    levelSuffix = levelCode - 14
                else:
                    # Escape code for large values (prefix >= 15)
                    levelPrefix = 15
                    levelSuffixSize = 12
                    while True:
                        if levelPrefix == 15:
                            min_val = 30
                            max_val = 30 + 4095
                        else:
                            min_val = 30 + (1 << (levelPrefix - 3)) - 4096
                            max_val = min_val + (1 << (levelPrefix - 3)) - 1
                        
                        if levelCode <= max_val:
                            levelSuffix = levelCode - min_val
                            break
                        
                        levelPrefix += 1
                        levelSuffixSize += 1
            else:
                if levelCode < (15 << suffixLength):
                    levelPrefix = levelCode >> suffixLength
                    levelSuffixSize = suffixLength
                    levelSuffix = levelCode & ((1 << suffixLength) - 1)
                else:
                    # Escape code for large values (prefix >= 15)
                    levelPrefix = 15
                    levelSuffixSize = 12
                    base = 15 << suffixLength
                    while True:
                        if levelPrefix == 15:
                            min_val = base
                            max_val = base + 4095
                        else:
                            min_val = base + (1 << (levelPrefix - 3)) - 4096
                            max_val = min_val + (1 << (levelPrefix - 3)) - 1
                        
                        if levelCode <= max_val:
                            levelSuffix = levelCode - min_val
                            break
                        
                        levelPrefix += 1
                        levelSuffixSize += 1
            
            # Write level_prefix (unary)
            self.writer.write_unary(levelPrefix)
            
            # Write level_suffix
            if levelSuffixSize > 0:
                self.writer.write_bits(levelSuffixSize, levelSuffix)
            
            # NO SIGN BIT - sign is embedded in levelCode!
            
            # CRITICAL: Adaptive suffixLength update per H.264 Section 9.2.2.1
            # Now that escape gaps are fixed, we can safely enable adaptive update.
            # This is REQUIRED to match original encoder behavior (ffmpeg uses adaptive).
            if suffixLength == 0:
                suffixLength = 1
            elif suffixLength > 0 and suffixLength < 6:
                # Threshold for increasing suffixLength
                threshold = 3 << (suffixLength - 1)
                if abs_level > threshold:
                    suffixLength += 1

    
    def _encode_run_before(self, analysis: BlockAnalysis):
        """
        Encode run_before values
        
        Args:
            analysis: Block analysis with runs
        """
        zeros_left = analysis.total_zeros
        
        # Validate zeros_left is non-negative
        if zeros_left < 0:
            zeros_left = 0
        
        # Encode all runs except the last (which is implicit)
        for run in analysis.runs[:-1]:
            # H.264 spec: when zeros_left == 0, all remaining run_before values
            # are implicitly 0 (decoder stops reading; encoder must stop writing).
            if zeros_left == 0:
                break

            # H.264 spec: run_before is in range [0, zeros_left]
            # Note: run CAN equal zeros_left (all remaining zeros before this coeff)
            # So only clamp if run > zeros_left (strictly greater)
            if run > zeros_left:
                run = zeros_left
            
            run_before_code = find_run_before_code(run, zeros_left)
            self.writer.write_bit_string(run_before_code)
            zeros_left -= run
            
            # Prevent negative zeros_left
            if zeros_left < 0:
                zeros_left = 0
    
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
