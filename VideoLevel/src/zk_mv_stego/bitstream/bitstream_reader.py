"""
Bitstream Reader Wrapper for Testing

Wraps byte data to provide read_bits interface for CAVLC decoder
"""


class BitstreamReader:
    """Read bits from bytes for testing"""
    
    def __init__(self, data: bytes):
        self.data = data
        self.byte_pos = 0
        self.bit_pos = 0
    
    def read_bits(self, n: int) -> int:
        """Read n bits and return as integer"""
        result = 0
        
        for i in range(n):
            if self.byte_pos >= len(self.data):
                raise EOFError("End of bitstream")
            
            # Read bit from current position
            byte = self.data[self.byte_pos]
            bit = (byte >> (7 - self.bit_pos)) & 1
            
            result = (result << 1) | bit
            
            # Advance position
            self.bit_pos += 1
            if self.bit_pos == 8:
                self.bit_pos = 0
                self.byte_pos += 1
        
        return result
    
    def read_bit(self) -> int:
        """Read single bit"""
        return self.read_bits(1)
    
    def read_ue(self) -> int:
        """Read unsigned exponential-Golomb code"""
        leading_zeros = 0
        
        # Count leading zeros
        while self.read_bit() == 0:
            leading_zeros += 1
            if leading_zeros > 31:
                raise ValueError("Invalid ue code - too many leading zeros")
        
        # Read value bits
        if leading_zeros == 0:
            return 0
        
        value = self.read_bits(leading_zeros)
        return (1 << leading_zeros) - 1 + value
    
    def read_se(self) -> int:
        """Read signed exponential-Golomb code"""
        code = self.read_ue()
        if code % 2 == 0:
            return -(code // 2)
        else:
            return (code + 1) // 2
    
    def byte_align(self):
        """Align to next byte boundary"""
        if self.bit_pos != 0:
            self.bit_pos = 0
            self.byte_pos += 1
    
    def tell(self) -> int:
        """Return current bit position"""
        return self.byte_pos * 8 + self.bit_pos
    
    def seek(self, bit_pos: int):
        """Seek to bit position"""
        self.byte_pos = bit_pos // 8
        self.bit_pos = bit_pos % 8
    
    def peek_bits(self, n: int) -> int:
        """Peek n bits without advancing position"""
        saved_byte = self.byte_pos
        saved_bit = self.bit_pos
        
        result = self.read_bits(n)
        
        self.byte_pos = saved_byte
        self.bit_pos = saved_bit
        
        return result
