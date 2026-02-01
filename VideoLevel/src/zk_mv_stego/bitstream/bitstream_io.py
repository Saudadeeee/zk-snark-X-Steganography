"""
Bitstream I/O for H.264
=======================

Unified module for bitstream reading and writing.
Contains:
- BitstreamReader: For parsing NAL units and slice headers
- BitstreamWriter: For constructing CAVLC-encoded bitstreams
"""

from typing import List

class BitstreamReader:
    """
    Bitstream reader with Exp-Golomb decoding
    Used for parsing H.264 syntax elements
    """
    
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0  # Bit position
    
    @property
    def position(self) -> int:
        """Get current bit position"""
        return self.pos
    
    def tell(self) -> int:
        """Get current bit position (alias for position property)"""
        return self.pos
    
    def seek(self, pos: int):
        """Seek to a specific bit position"""
        if pos < 0 or pos > len(self.data) * 8:
            raise ValueError(f"Invalid position: {pos}")
        self.pos = pos
    
    def is_byte_aligned(self) -> bool:
        """Check if reader is byte-aligned"""
        return self.pos % 8 == 0
        
    def read_bits(self, n: int) -> int:
        """Read n bits from bitstream"""
        result = 0
        for _ in range(n):
            byte_pos = self.pos // 8
            bit_pos = 7 - (self.pos % 8)
            
            if byte_pos >= len(self.data):
                raise EOFError("End of bitstream")
            
            bit = (self.data[byte_pos] >> bit_pos) & 1
            result = (result << 1) | bit
            self.pos += 1
        
        return result
    
    def read_ue(self) -> int:
        """
        Read unsigned Exp-Golomb coded integer
        Used extensively in H.264 for variable-length encoding
        """
        leading_zeros = 0
        while self.read_bits(1) == 0:
            leading_zeros += 1
            if leading_zeros > 32:
                raise ValueError("Invalid Exp-Golomb code")
        
        if leading_zeros == 0:
            return 0
        
        value = self.read_bits(leading_zeros)
        return (1 << leading_zeros) - 1 + value
    
    def read_se(self) -> int:
        """
        Read signed Exp-Golomb coded integer
        """
        code_num = self.read_ue()
        # Map: 0->0, 1->1, 2->-1, 3->2, 4->-2, ...
        return (code_num + 1) // 2 if code_num % 2 == 1 else -(code_num // 2)
    
    def byte_aligned(self) -> bool:
        """Check if at byte boundary"""
        return self.pos % 8 == 0
    
    def align_to_byte(self):
        """Skip bits to align to next byte boundary"""
        if not self.byte_aligned():
            self.pos = ((self.pos // 8) + 1) * 8
            
    def peek_bits(self, n: int) -> int:
        """Peek n bits without advancing position"""
        saved_pos = self.pos
        try:
            return self.read_bits(n)
        finally:
            self.pos = saved_pos


class BitstreamWriter:
    """
    Write bits to output buffer for CAVLC encoding
    
    Accumulates bits in buffer and converts to bytes on completion
    """
    
    def __init__(self):
        self.buffer: List[int] = []  # Byte buffer
        self.bit_buffer: int = 0      # Current byte being built
        self.bit_count: int = 0       # Number of bits in bit_buffer (0-7)
        self.total_bits: int = 0      # Total bits written
    
    def write_bits(self, num_bits: int, value: int):
        """
        Write specified number of bits to buffer
        
        Args:
            num_bits: Number of bits to write (1-32)
            value: Integer value to write
        """
        for i in range(num_bits - 1, -1, -1):
            # Extract bit at position i
            bit = (value >> i) & 1
            self.write_bit(bit)
    
    def write_bit(self, bit: int):
        """
        Write single bit (0 or 1)
        
        Args:
            bit: 0 or 1
        """
        # Add bit to buffer
        self.bit_buffer = (self.bit_buffer << 1) | bit
        self.bit_count += 1
        self.total_bits += 1  # Track total bits
        
        # Flush byte when full
        if self.bit_count == 8:
            self.buffer.append(self.bit_buffer)
            self.bit_buffer = 0
            self.bit_count = 0
    
    def write_bit_string(self, bit_string: str):
        """
        Write bit string (e.g., "10110")
        
        Args:
            bit_string: String of '0' and '1' characters
        """
        for bit_char in bit_string:
            self.write_bit(int(bit_char))
    
    def write_ue(self, value: int):
        """
        Write unsigned Exp-Golomb code
        
        Args:
            value: Non-negative integer
        """
        if value == 0:
            self.write_bit(1)
            return
        
        # value = 2^M + X - 1
        # M = floor(log2(value + 1))
        # Code: M zeros + 1 + M-bit value
        
        val_plus_1 = value + 1
        M = val_plus_1.bit_length() - 1
        
        # Write M zeros
        for _ in range(M):
            self.write_bit(0)
        
        # Write val_plus_1 in M+1 bits
        self.write_bits(M + 1, val_plus_1)
    
    def write_se(self, value: int):
        """
        Write signed Exp-Golomb code
        
        Args:
            value: Signed integer
        """
        # Map signed to unsigned:
        # 0 -> 0, 1 -> 1, -1 -> 2, 2 -> 3, -2 -> 4, ...
        if value <= 0:
            code = -2 * value
        else:
            code = 2 * value - 1
        
        self.write_ue(code)
    
    def write_me_cbp(self, cbp: int, is_intra: bool = True):
        """
        Write Coded Block Pattern using me(v) mapping (H.264 Table 9-4)
        
        Args:
            cbp: CBP value (0-47)
            is_intra: True for Intra macroblocks, False for Inter
        """
        # H.264 Table 9-4(a) for Intra macroblocks (me -> cbp)
        cbp_mapping_intra = [
            47, 31, 15, 0, 23, 27, 29, 30, 7, 11, 13, 14, 39, 43, 45, 46,
            16, 3, 5, 10, 12, 19, 21, 26, 28, 35, 37, 42, 44, 1, 2, 4,
            8, 17, 18, 20, 24, 6, 9, 22, 25, 32, 33, 34, 36, 40, 38, 41
        ]
        
        # H.264 Table 9-4(b) for Inter macroblocks (me -> cbp)
        cbp_mapping_inter = [
            0, 16, 1, 2, 4, 8, 32, 3, 5, 10, 12, 15, 47, 7, 11, 13,
            14, 6, 9, 31, 35, 37, 42, 44, 33, 34, 36, 40, 39, 43, 45, 46,
            17, 18, 20, 24, 19, 21, 26, 28, 23, 27, 29, 30, 22, 25, 38, 41
        ]
        
        # Select mapping table
        mapping = cbp_mapping_intra if is_intra else cbp_mapping_inter
        
        # Find inverse: cbp -> me_val
        try:
            me_val = mapping.index(cbp)
            # Write me_val as Exp-Golomb
            self.write_ue(me_val)
        except ValueError:
            # CBP not in mapping table - use raw value
            # This happens for invalid CBP values (e.g., 48-63 for Intra)
            # H.264 spec says max CBP for Intra 4x4 is 47
            # For now, clamp to 47 or use raw Exp-Golomb
            self.write_ue(cbp)  # Fallback: encode raw value
    
    def write_unary(self, value: int):
        """
        Write unary code for CAVLC: value zeros followed by one
        Per H.264 Table 9-7: level_prefix uses 0^M 1 format
        
        Args:
            value: Non-negative integer (number of leading zeros)
        """
        for _ in range(value):
            self.write_bit(0)
        self.write_bit(1)
    
    def align_to_byte(self):
        """
        Pad with zeros to byte boundary
        """
        if self.bit_count > 0:
            # Shift left to fill byte
            self.bit_buffer <<= (8 - self.bit_count)
            self.buffer.append(self.bit_buffer)
            self.bit_buffer = 0
            self.bit_count = 0
    
    def get_bytes(self, align: bool = True) -> bytes:
        """
        Get final byte array, optionally with padding to byte boundary
        
        Args:
            align: If True (default), align to byte boundary with padding
        
        Returns:
            Byte array of encoded data
        """
        # Flush any remaining bits if requested
        if align and self.bit_count > 0:
            self.align_to_byte()
        elif not align and self.bit_count > 0:
            # Return current buffer + partial byte (shifted left)
            partial_byte = self.bit_buffer << (8 - self.bit_count)
            return bytes(self.buffer + [partial_byte])
        
        return bytes(self.buffer)
    
    def get_bit_position(self) -> int:
        """
        Get current bit position (total bits written)
        
        Returns:
            Total number of bits written so far
        """
        return self.total_bits
    
    def get_bit_count(self) -> int:
        """
        Get total number of bits written
        
        Returns:
            Total bits (including unflushed bits)
        """
        return len(self.buffer) * 8 + self.bit_count
    
    def get_byte_count(self) -> int:
        """
        Get number of complete bytes written
        
        Returns:
            Number of bytes
        """
        return len(self.buffer)
    
    def reset(self):
        """Reset writer to initial state"""
        self.buffer.clear()
        self.bit_buffer = 0
        self.bit_count = 0
    
    def __repr__(self):
        return f"BitstreamWriter({len(self.buffer)} bytes, {self.bit_count} pending bits)"
