"""
CAVLC (Context-Adaptive Variable Length Coding) Decoder
For extracting quantized DCT coefficient levels from H.264 bitstream

Reference: ITU-T H.264 Specification Section 9.2
"""

from typing import List, Tuple
from dataclasses import dataclass
from .cavlc_tables import (
    get_coeff_token_table,
    get_total_zeros_table,
    get_run_before_table,
    decode_vlc
)


# CAVLC VLC Tables (from H.264 spec Table 9-5 to 9-7)
COEFF_TOKEN_TABLE = {
    # Format: (nC_index, code) -> (TotalCoeff, TrailingOnes)
    # nC is number of non-zero coeffs in neighboring blocks
    # Simplified table - full implementation needs all nC ranges
}

TOTAL_ZEROS_TABLE = {
    # Table 9-7: total_zeros VLC
    # Format: (TotalCoeff, code) -> total_zeros value
}

RUN_BEFORE_TABLE = {
    # Table 9-10: run_before VLC  
    # Format: (zerosLeft, code) -> run_before value
}


@dataclass
class CoefficientBlock:
    """Represents a 4x4 block of quantized DCT coefficients"""
    levels: List[int]  # Coefficient values (integers)
    total_coeffs: int  # Number of non-zero coefficients
    trailing_ones: int  # Number of trailing ±1 values
    total_zeros: int  # Total number of zeros
    bit_positions: List[Tuple[int, int]] = None  # Optional: [(start_bit, end_bit), ...] for each non-zero coefficient
    
    
class CAVLCDecoder:
    """
    Decode CAVLC-encoded residual data to extract quantized coefficient levels
    
    CAVLC encoding structure:
    1. coeff_token: Encodes TotalCoeffs and TrailingOnes
    2. trailing_ones_sign_flag: Signs of trailing ±1 values
    3. level values: Remaining non-zero coefficient values
    4. total_zeros: Total number of zeros before last coefficient
    5. run_before: Number of zeros before each coefficient
    """
    
    def __init__(self, reader, skip_constraint_fixing=False):
        """
        Args:
            reader: BitstreamReader instance positioned at residual data
            skip_constraint_fixing: If True, skip _fix_decoded_cavlc_constraints()
                                  This preserves coefficients for steganography but
                                  may violate VLC constraints in output bitstream
        """
        self.reader = reader
        self.skip_constraint_fixing = skip_constraint_fixing
        
        # H.264 VLC table max_total_zeros constraints (derived from TOTAL_ZEROS_TABLES)
        # These are the ACTUAL maximums from the VLC code tables, NOT calculated from formulas
        self.MAX_TOTAL_ZEROS_BY_TC = {
            1: 15, 2: 14, 3: 13, 4: 11, 5: 10, 6: 9, 7: 9, 8: 7,
            9: 6, 10: 5, 11: 4, 12: 3, 13: 2, 14: 1, 15: 0
        }
        
    def decode_block_cavlc(self, nC: int, max_num_coeff: int = 16, debug_key=None, track_positions: bool = False) -> CoefficientBlock:
        """
        Decode one 4x4 block of coefficients using CAVLC
        
        Args:
            nC: Prediction of number of non-zero coefficients from neighbors
            max_num_coeff: Maximum coefficients (16 for 4x4, 15 for chroma DC)
            debug_key: Optional (mb_idx, block_idx) for debugging
            track_positions: If True, track bit positions of coefficients
            
        Returns:
            CoefficientBlock with decoded levels (and positions if track_positions=True)
        """
        # Track starting position if requested
        block_start_bit = self.reader.bit_position if track_positions else None
        coeff_positions = [] if track_positions else None
        
        # Step 1: Decode coeff_token
        coeff_token_start = self.reader.bit_position if track_positions else None
        total_coeffs, trailing_ones = self._decode_coeff_token(nC)
        coeff_token_end = self.reader.bit_position if track_positions else None
        
        if total_coeffs == 0:
            # Block is all zeros
            return CoefficientBlock(
                levels=[0] * max_num_coeff,
                total_coeffs=0,
                trailing_ones=0,
                total_zeros=0
            )
        
        # Step 2: Decode signs of trailing ones
        trailing_signs = []
        for i in range(trailing_ones):
            sign_start = self.reader.bit_position if track_positions else None
            sign = self.reader.read_bits(1)
            sign_end = self.reader.bit_position if track_positions else None
            
            trailing_signs.append(-1 if sign else 1)
            
            # Track position for this trailing one coefficient
            if track_positions:
                coeff_positions.append((sign_start, sign_end))
        
        # Step 3: Decode remaining levels
        levels_remaining = total_coeffs - trailing_ones
        level_values, level_positions = self._decode_levels(
            levels_remaining, trailing_ones, total_coeffs, 
            track_positions=track_positions
        )
        
        # Append level positions to coeff_positions
        if track_positions and level_positions:
            coeff_positions.extend(level_positions)
        
        # Step 4: Decode total_zeros
        if total_coeffs < max_num_coeff:
            is_chroma_dc = (nC == -1)
            total_zeros = self._decode_total_zeros(total_coeffs, max_num_coeff, is_chroma_dc)
        else:
            total_zeros = 0
        
        # Step 5: Decode run_before values
        runs = self._decode_runs(total_coeffs, total_zeros)
        
        # Step 6: Reconstruct coefficient array with zigzag order
        # Combine levels: trailing ones first, then non-trailing levels
        # This matches encoding order (trailing ones are highest frequency coeffs)
        # Both are decoded in reverse zigzag order (high frequency first)
        # Need to reverse to get forward zigzag order for reconstruction
        all_levels = trailing_signs + level_values
        all_levels_forward = list(reversed(all_levels))
        runs_forward = list(reversed(runs))
        
        # DEBUG for MB0 Block2
        if debug_key and debug_key[0] == 0 and debug_key[1] == 2:
            print(f"[CAVLC_DEC_DEBUG] MB0 Block2:")
            print(f"  total_coeffs={total_coeffs}, trailing_ones={trailing_ones}")
            print(f"  trailing_signs={trailing_signs}")
            print(f"  level_values={level_values}")
            print(f"  all_levels_forward={all_levels_forward}")
            print(f"  runs_forward={runs_forward}")
            print(f"  total_zeros={total_zeros}")
        
        coeffs = self._reconstruct_coefficients(
            all_levels_forward,
            runs_forward,
            max_num_coeff
        )
        
        # DEBUG for MB0 Block2
        if debug_key and debug_key[0] == 0 and debug_key[1] == 2:
            print(f"  coeffs after reconstruct={coeffs}")
        
        # Debug: log what we decoded
        if debug_key and debug_key[0] == 0 and debug_key[1] in [16, 17, 18, 19]:
            non_zero = [c for c in coeffs if c != 0]
            print(f"      [CAVLC_DEC] Decoded MB{debug_key[0]} block{debug_key[1]}: {non_zero[:5]}...")
        
        # [FIX] Ensure decoded coefficients satisfy VLC constraints
        # This is critical because Exp-Golomb fallback can create invalid (TC, total_zeros) pairs
        # e.g., TC=4 with clamped value 12, but VLC table max is 12
        # STEGANOGRAPHY: Can be skipped to preserve embedded data (output may have VLC violations)
        if not self.skip_constraint_fixing:
            coeffs = self._fix_decoded_cavlc_constraints(coeffs, max_num_coeff)
        # else: Keep coefficients as-is (preserves embedded data, may violate VLC constraints)
        
        # Build final bit_positions list (aligned with coefficient positions in zigzag order)
        final_bit_positions = None
        if track_positions and coeff_positions:
            # coeff_positions currently has positions for non-zero coefficients in decode order
            # We need to map them to final coefficient array positions
            # For now, store the raw positions - mapping will be done during patching
            final_bit_positions = coeff_positions
        
        block = CoefficientBlock(
            levels=coeffs,
            total_coeffs=total_coeffs,
            trailing_ones=trailing_ones,
            total_zeros=total_zeros,
            bit_positions=final_bit_positions
        )
        
        # Add convenient attribute for extractor to access
        if track_positions:
            block.coeff_bit_positions = final_bit_positions
        
        return block
    
    def _decode_coeff_token(self, nC: int) -> Tuple[int, int]:
        """
        Decode coeff_token using VLC table with robust fallback
        
        Returns: (TotalCoeffs, TrailingOnes)
        """
        table = get_coeff_token_table(nC)
            
        if table == 'FLC6':
            # nC >= 8: use fixed-length code (8 bits total)
            # Format per H.264 spec: 6 bits TotalCoeff + 2 bits TrailingOnes
            code = self.reader.read_bits(8)
            total_coeffs = (code >> 2) & 0x3F  # Upper 6 bits
            trailing_ones = code & 0x3          # Lower 2 bits
            return (total_coeffs, min(trailing_ones, 3))
        
        elif table:
            # Use VLC table lookup with robust fallback
            start_pos = self.reader.tell()
            try:
                total_coeffs, trailing_ones = decode_vlc(self.reader, table, max_bits=16)
                return (total_coeffs, trailing_ones)
            except ValueError as e:
                # VLC code not in table - try Exp-Golomb fallback
                # This handles FFmpeg variations that use valid but uncommon codes
                self.reader.seek(start_pos)
                try:
                    # Try reading as Exp-Golomb: first bit indicates if block has coeffs
                    first_bit = self.reader.read_bits(1)
                    if first_bit == 0:
                        # No coefficients
                        return (0, 0)
                    else:
                        # Read total_coeffs and trailing_ones using Exp-Golomb
                        # This is a simplified fallback, not standard H.264
                        total_coeffs = min(self.reader.read_ue() + 1, 16)
                        trailing_ones = min(self.reader.read_bits(2), min(total_coeffs, 3))
                        return (total_coeffs, trailing_ones)
                except:
                    # Last resort - skip this block
                    return (0, 0)
        else:
            # Fallback for missing tables
            if self.reader.read_bits(1) == 0:
                return (0, 0)
            total_coeffs = self.reader.read_ue() + 1
            trailing_ones = min(self.reader.read_bits(2), total_coeffs)
            return (total_coeffs, trailing_ones)
    
    def _decode_levels(self, count: int, trailing_ones: int, total_coeffs: int, track_positions: bool = False) -> Tuple[List[int], List[Tuple[int, int]]]:
        """
        Decode remaining coefficient levels (non-trailing-one values)
        
        H.264 Spec 9.2.2.1: levelCode = 2*abs_level - 2 + (sign ? 1 : 0)
        Where sign=0 for positive, sign=1 for negative
        
        Returns:
            Tuple of (levels, positions) where positions is list of (start_bit, end_bit) if track_positions=True
        """
        levels = []
        positions = [] if track_positions else None
        
        # Level decoding uses adaptive VLC
        # suffixLength initialization per H.264 spec (MUST match encoder!)
        # Rule: suffixLength = 1 if total_coeffs > 10 and trailing_ones < 3, else 0
        if total_coeffs > 10 and trailing_ones < 3:
            suffixLength = 1
        else:
            suffixLength = 0
        
        for i in range(count):
            # Track start position for this level
            level_start = self.reader.bit_position if track_positions else None
            
            # Decode level_prefix (unary code)
            level_prefix = 0
            while self.reader.read_bits(1) == 0:
                level_prefix += 1
                if level_prefix > 15:  # Safety limit
                    break
            
            # Decode level_suffix if needed
            if level_prefix < 14:
                if suffixLength > 0:
                    level_suffix = self.reader.read_bits(suffixLength)
                else:
                    level_suffix = 0
                
                levelCode = (level_prefix << suffixLength) + level_suffix
            else:
                # Escape code
                level_suffix = self.reader.read_bits(4)
                levelCode = (15 << suffixLength) + level_suffix
            
            # Convert levelCode to actual level value
            # H.264 Section 9.2.2.1:
            # - Normal: levelCode = 2*abs_level - 2 + sign_bit
            # - After 3 T1s: levelCode = 2*abs_level + sign_bit (bias +3 correction)
            sign_bit = levelCode & 1  # LSB is sign (0=positive, 1=negative)
            
            if i == 0 and trailing_ones == 3:
                # First level after 3 T1s: special decoding
                # levelCode = 2*(abs_level - 2) + sign_bit
                # Solve: abs_level = (levelCode - sign_bit)/2 + 2
                abs_level = (levelCode - sign_bit) >> 1
                abs_level += 2
            else:
                # levelCode = 2*abs_level - 2 + sign_bit
                # abs_level = (levelCode - sign_bit + 2) / 2
                abs_level = (levelCode - sign_bit + 2) >> 1

            
            # Apply sign (1 = negative, 0 = positive)
            level = -abs_level if sign_bit else abs_level
            
            # Track end position for this level
            level_end = self.reader.bit_position if track_positions else None
            
            levels.append(level)
            if track_positions:
                positions.append((level_start, level_end))
            
            # Update suffixLength adaptively
            if suffixLength == 0:
                suffixLength = 1
            elif abs(level) > (3 << (suffixLength - 1)) and suffixLength < 6:
                suffixLength += 1
        
        return (levels, positions)
    
    def _decode_total_zeros(self, total_coeffs: int, max_num_coeff: int, is_chroma_dc: bool = False) -> int:
        """
        Decode total_zeros using VLC table with robust fallback
        
        Uses VLC table first, falls back to multiple strategies on decode errors.
        Clamps result to valid range based on H.264 constraints.
        """
        # VLC table limits per TC (from TOTAL_ZEROS_TABLES)
        MAX_TOTAL_ZEROS = {
            1: 15, 2: 14, 3: 13, 4: 11, 5: 10, 6: 9, 7: 9, 8: 7,
            9: 6, 10: 5, 11: 4, 12: 3, 13: 2, 14: 1, 15: 0
        }
        
        table = get_total_zeros_table(total_coeffs, is_chroma_dc)
        
        if table:
            start_pos = self.reader.tell()
            try:
                total_zeros = decode_vlc(self.reader, table, max_bits=9)
                return total_zeros
            except ValueError as e:
                # VLC decode failed - try multiple fallback strategies
                self.reader.seek(start_pos)
                
                # Determine max allowed value
                if total_coeffs in MAX_TOTAL_ZEROS:
                    max_allowed = MAX_TOTAL_ZEROS[total_coeffs]
                else:
                    max_allowed = max_num_coeff - total_coeffs
                
                # Strategy 1: Try fixed-length code based on max_allowed
                try:
                    num_bits = max(1, max_allowed.bit_length())
                    tz = self.reader.read_bits(num_bits)
                    if tz <= max_allowed:
                        return tz
                except:
                    pass
                
                # Strategy 2: Try Exp-Golomb
                try:
                    self.reader.seek(start_pos)
                    ue_value = self.reader.read_ue()
                    clamped = min(ue_value, max_allowed)
                    return clamped
                except:
                    # Last resort - assume 0 zeros
                    return 0
        else:
            # Fallback for missing tables
            total_zeros = self.reader.read_ue()
            max_allowed = max_num_coeff - total_coeffs
            return min(total_zeros, max_allowed)
    
    def _decode_runs(self, total_coeffs: int, total_zeros: int) -> list:
        """
        Decode run_before values (zeros before each non-zero coeff)
        """
        runs = []
        zeros_left = total_zeros
        
        # Optimization: if no zeros, all runs are 0
        if total_zeros == 0:
            return [0] * total_coeffs
        
        for i in range(total_coeffs - 1):
            if zeros_left > 0:
                # Get run_before table for current zeros_left
                table = get_run_before_table(zeros_left)
                
                if table:
                    try:
                        run = decode_vlc(self.reader, table, max_bits=11)
                        runs.append(run)
                        zeros_left -= run
                    except ValueError:
                        # Fallback
                        run = min(self.reader.read_ue(), zeros_left)
                        runs.append(run)
                        zeros_left -= run
                else:
                    # Fallback for missing tables
                    run = min(self.reader.read_ue(), zeros_left)
                    runs.append(run)
                    zeros_left -= run
            else:
                runs.append(0)
        
        # Last coefficient gets all remaining zeros
        runs.append(zeros_left)
        
        return runs
    
    def _reconstruct_coefficients(self, levels: List[int], runs: List[int], 
                                   max_num_coeff: int) -> List[int]:
        """
        Reconstruct coefficient array from levels and runs
        Apply reverse zigzag scan
        """
        coeffs = []
        level_idx = 0
        
        # Place coefficients with zeros according to runs
        for i in range(len(runs)):
            # Add zeros before this coefficient
            coeffs.extend([0] * runs[i])
            # Add the coefficient
            if level_idx < len(levels):
                coeffs.append(levels[level_idx])
                level_idx += 1
        
        # Pad with zeros to max_num_coeff
        while len(coeffs) < max_num_coeff:
            coeffs.append(0)
        
        # Coefficients are already in zigzag scan order (same as encoder input)
        # No need to apply reverse zigzag - that would convert to raster order
        return coeffs[:max_num_coeff]
    
    def _reverse_zigzag_4x4(self, coeffs: List[int]) -> List[int]:
        """
        Apply reverse zigzag scan for 4x4 block
        H.264 uses specific zigzag order (Table 8-13)
        """
        # Zigzag scan order for 4x4
        zigzag_order = [
            0,  1,  4,  8,
            5,  2,  3,  6,
            9, 12, 13, 10,
            7, 11, 14, 15
        ]
        
        result = [0] * 16
        for i, pos in enumerate(zigzag_order):
            if i < len(coeffs):
                result[pos] = coeffs[i]
        
        return result
    
    def _fix_decoded_cavlc_constraints(self, coeffs: List[int], max_num_coeff: int = 16) -> List[int]:
        """
        Fix CAVLC VLC constraints for decoded coefficients
        
        CRITICAL: This is needed because:
        1. Exp-Golomb fallback in _decode_total_zeros() can clamp values to VLC table limits
        2. But the clamped coefficients themselves might still violate VLC encoding constraints
        3. Example: TC=4 with Exp-Golomb value 13→clamped to 12, but this creates 
           total_zeros=12 which cannot be VLC-encoded for TC=4 (max is 12)
        
        This method ensures the final coefficient array can be successfully re-encoded.
        
        Args:
            coeffs: Decoded coefficient array (may contain invalid VLC patterns from clamping)
            max_num_coeff: Maximum number of coefficients (16 for 4x4 luma, 15 for chroma DC)
            
        Returns:
            Fixed coefficient array that satisfies all CAVLC VLC constraints
        """
        # Calculate active coefficients (exclude trailing zeros per H.264)
        last_nz_idx = -1
        for i in range(len(coeffs) - 1, -1, -1):
            if coeffs[i] != 0:
                last_nz_idx = i
                break
        
        if last_nz_idx == -1:
            return coeffs  # All zeros, nothing to fix
        
        active_coeffs = coeffs[:last_nz_idx + 1]
        
        # Iteratively fix constraints (up to 5 iterations for cascading fixes)
        for iteration in range(5):
            # Calculate TC and total_zeros
            total_coeffs = sum(1 for c in active_coeffs if c != 0)
            total_zeros = len(active_coeffs) - total_coeffs
            
            if total_coeffs == 0 or total_coeffs > 15:
                break  # Invalid state, stop
            
            # Get VLC table limit for this TC
            max_allowed = self.MAX_TOTAL_ZEROS_BY_TC.get(total_coeffs, 0)
            
            if total_zeros <= max_allowed:
                # Valid! Restore full coefficient array and return
                fixed_coeffs = list(active_coeffs)
                while len(fixed_coeffs) < max_num_coeff:
                    fixed_coeffs.append(0)
                return fixed_coeffs
            
            # Invalid: too many zeros for this TC
            # Convert excess zeros to ±1 (alternating signs for visual balance)
            excess_zeros = total_zeros - max_allowed
            
            # Find zero positions (excluding trailing zeros)
            zero_positions = [i for i, c in enumerate(active_coeffs) if c == 0]
            
            if len(zero_positions) < excess_zeros:
                # Safety: can't fix if insufficient zeros
                # print(f"[CAVLC_DEC_FIX] WARNING: TC={total_coeffs} total_zeros={total_zeros} max={max_allowed}, "
                #       f"but only {len(zero_positions)} zeros available to convert")
                break
            
            # Convert excess zeros to ±1 (alternating)
            for idx, pos in enumerate(zero_positions[:excess_zeros]):
                active_coeffs[pos] = 1 if (idx % 2 == 0) else -1
            
            # Note: Converting zeros to ±1 increases TC, which may trigger stricter constraints
            # So we loop to re-check
        
        # If we exhausted iterations, return the best effort
        fixed_coeffs = list(active_coeffs)
        while len(fixed_coeffs) < max_num_coeff:
            fixed_coeffs.append(0)
        
        # print(f"[CAVLC_DEC_FIX] Fixed after {iteration+1} iterations")
        return fixed_coeffs


def test_cavlc_decoder():
    """Test CAVLC decoder with synthetic data"""
    from src.zk_mv_stego.bitstream.bitstream_io import BitstreamReader
    
    # Create test bitstream (would come from real H.264 slice)
    test_data = bytes([0xFF, 0xAA, 0x55, 0x00, 0x01, 0x02, 0x03])
    reader = BitstreamReader(test_data)
    
    decoder = CAVLCDecoder(reader)
    
    # Decode one block (nC=0 means no prediction from neighbors)
    block = decoder.decode_block_cavlc(nC=0, max_num_coeff=16)
    
    print("Decoded Coefficient Block:")
    print(f"  Total coefficients: {block.total_coeffs}")
    print(f"  Trailing ones: {block.trailing_ones}")
    print(f"  Total zeros: {block.total_zeros}")
    print(f"  Levels (first 16): {block.levels[:16]}")
    
    return block


if __name__ == '__main__':
    print("CAVLC Decoder Test")
    print("=" * 60)
    print("\n[WARNING] NOTE: This is a SIMPLIFIED implementation")
    print("   Full CAVLC requires complete VLC tables from H.264 spec")
    print("   Current version uses placeholders for testing\n")
    
    block = test_cavlc_decoder()
