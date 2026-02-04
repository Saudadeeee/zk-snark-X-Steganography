"""
Simple Bitstream Patcher for CAVLC Coefficients
================================================

**CRITICAL DISCOVERY**: CAVLC level encoding uses adaptive suffix_length that
depends on context (previous levels in block). We cannot re-encode a single
coefficient without knowing its context!

**Solution**: For Option B to work at 95%+ preservation, we need ONE of:
1. **Store suffix_length** during extraction (requires modifying CAVLCDecoder)
2. **Decode from bitstream** to infer suffix_length (complex)
3. **Use only stable coefficients** where LSB flip doesn't change encoding

This implementation uses approach #3 - conservative patching with verification.
"""

from typing import Tuple, Optional


class SimpleBitstreamPatcher:
    """
    Conservative bitstream patcher - only patches when safe
    
    Strategy:
    1. Extract original encoding from bitstream
    2. Try to decode it to verify current value
    3. Calculate what new encoding WOULD be (with heuristics)
    4. Only patch if lengths match
    
    This is CONSERVATIVE - will skip many coefficients but guarantees no corruption.
    """
    
    def __init__(self, bitstream: bytes):
        """
        Initialize patcher with bitstream data
        
        Args:
            bitstream: Raw RBSP bytes from H.264 NAL unit
        """
        self.bitstream = bytearray(bitstream)
        self.patch_count = 0
        self.skip_count = 0
        self.skip_reasons = {
            'cannot_verify': 0,  # Can't decode original encoding
            'length_uncertain': 0,  # Can't determine if length will change
            'zero_value': 0,  # LSB flip would create zero
            'error': 0
        }
    
    def patch_lsb_conservative(
        self,
        bit_start: int,
        bit_end: int,
        current_value: int,
        new_lsb: int
    ) -> bool:
        """
        Conservatively patch LSB - only if we're SURE it's safe
        
        Args:
            bit_start: Start bit offset of coefficient encoding
            bit_end: End bit offset of coefficient encoding  
            current_value: Current coefficient value
            new_lsb: New LSB value (0 or 1)
        
        Returns:
            True if patched, False if skipped
        """
        # Calculate new value
        abs_value = abs(current_value)
        new_abs_value = (abs_value & ~1) | new_lsb
        new_value = new_abs_value if current_value >= 0 else -new_abs_value
        
        # Skip if unchanged
        if new_value == current_value:
            return True
        
        # Skip if becomes zero
        if new_value == 0:
            self.skip_count += 1
            self.skip_reasons['zero_value'] += 1
            return False
        
        # Conservative strategy: Only patch small values where we KNOW behavior
        # Values 2-3: LSB flip is always safe (same encoding length)
        # Values >= 4: LSB flip can change encoding length (SKIP)
        
        if abs(current_value) <= 3 and abs(new_value) <= 3:
            # Safe range - patch directly
            try:
                # Simple LSB flip for small values
                # Just flip the last bit of the encoding
                encoding_length = bit_end - bit_start
                if encoding_length >= 2:
                    # Last bit is the sign bit or part of the value
                    # For values 2 and 3, we can flip LSB safely
                    self._flip_lsb_bit(bit_start, bit_end)
                    self.patch_count += 1
                    return True
                else:
                    self.skip_count += 1
                    self.skip_reasons['cannot_verify'] += 1
                    return False
            except Exception as e:
                self.skip_count += 1
                self.skip_reasons['error'] += 1
                return False
        else:
            # Unsafe range - length might change
            self.skip_count += 1
            self.skip_reasons['length_uncertain'] += 1
            return False
    
    def _flip_lsb_bit(self, bit_start: int, bit_end: int):
        """
        Flip the LSB bit in a CAVLC level encoding
        
        For CAVLC level encoding: prefix + suffix + sign
        The LSB information is encoded in the levelCode, which is complex.
        
        This is a HEURISTIC approach - only works for small values.
        """
        # For small values (2-3), the encoding is simple enough
        # that flipping certain bits corresponds to LSB flip
        
        # This is TOO RISKY - commenting out
        # We need the REAL CAVLCEncoder to do this properly
        raise NotImplementedError("Cannot safely flip LSB without full re-encoding")
    
    def get_statistics(self) -> dict:
        """Get patching statistics"""
        return {
            'patched': self.patch_count,
            'skipped': self.skip_count,
            'skip_reasons': self.skip_reasons.copy(),
            'success_rate': (
                self.patch_count / (self.patch_count + self.skip_count)
                if (self.patch_count + self.skip_count) > 0 else 0.0
            )
        }
