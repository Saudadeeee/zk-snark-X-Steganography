"""Reed-Solomon Error Correction Codec for ZK Proof Protection

Provides error correction capability to handle bit errors during video steganography
extraction, caused by CAVLC parser incompatibilities.

Configuration:
- Message size: 336 bytes (binary Groth16 proof)
- Split into 3 blocks of 112 bytes each
- ECC per block: 100 bytes (89% overhead per block)
- Total encoded size: 636 bytes (212 × 3)
- Correction capability: Up to 150 byte errors total (44% error rate)
"""

from reedsolo import RSCodec

class ProofRSCodec:
    """Reed-Solomon codec for ZK proof protection using 3-block encoding"""
    
    # Constants
    MESSAGE_SIZE = 336  # Binary Groth16 proof size
    BLOCK_SIZE = 112    # Each block is 112 bytes (336 ÷ 3)
    NUM_BLOCKS = 3      # Split into 3 blocks
    ECC_PER_BLOCK = 100  # 89% overhead per block (reduced to fit capacity)
    ENCODED_BLOCK_SIZE = BLOCK_SIZE + ECC_PER_BLOCK  # 212 bytes
    ENCODED_SIZE = ENCODED_BLOCK_SIZE * 3  # 636 bytes total
    
    def __init__(self):
        """Initialize RS codec with 100 ECC symbols per block (89% overhead)
        
        Configuration:
        - nsym=100: Error correction symbols per block
        - Uses standard 8-bit symbols (nsize=255, c_exp=8)
        - Each block: 112 data + 100 ECC = 212 bytes
        - Total: 3 blocks × 212 = 636 bytes
        - Can correct up to 50 bytes per block (150 total = 44%)
        """
        # Use standard RS codec with 8-bit symbols
        self.codec = RSCodec(nsym=100)
    
    # NOTE: Byte-level interleaving removed - doesn't help because errors occur
    # during extraction of the encoded data. Frame-level interleaving in the
    # embedder/extractor is needed instead to distribute extraction errors.
    
    def encode(self, data: bytes) -> bytes:
        """Add Reed-Solomon error correction codes to data
        
        Args:
            data: Binary proof data (must be 336 bytes)
            
        Returns:
            Encoded data with ECC (636 bytes)
            
        Raises:
            ValueError: If data size is not 336 bytes
        """
        if len(data) != self.MESSAGE_SIZE:
            raise ValueError(
                f"Invalid data size: {len(data)} bytes "
                f"(expected {self.MESSAGE_SIZE})"
            )
        
        # Split into 3 equal blocks (no byte-level interleaving)
        block1 = data[:self.BLOCK_SIZE]
        block2 = data[self.BLOCK_SIZE:self.BLOCK_SIZE*2]
        block3 = data[self.BLOCK_SIZE*2:]
        
        # Encode each block separately (112 → 240 bytes)
        encoded_block1 = self.codec.encode(block1)
        encoded_block2 = self.codec.encode(block2)
        encoded_block3 = self.codec.encode(block3)
        
        # Concatenate encoded blocks: 240 + 240 + 240 = 720 bytes
        result = bytes(encoded_block1) + bytes(encoded_block2) + bytes(encoded_block3)
        
        if len(result) != self.ENCODED_SIZE:
            raise RuntimeError(
                f"RS encoding produced unexpected size: {len(result)} bytes "
                f"(expected {self.ENCODED_SIZE})"
            )
        
        return result
    
    def decode(self, encoded_data: bytes) -> tuple[bytes, int, bool]:
        """Decode data and correct errors using Reed-Solomon
        
        Args:
            encoded_data: Encoded data with ECC (must be 636 bytes)
            
        Returns:
            Tuple of:
            - Corrected data (336 bytes)
            - Number of errors corrected (total across all 3 blocks)
            - Whether correction was successful
            
        Note:
            Can correct up to 50 bytes per block (150 bytes total across all blocks).
            If any block has >50 errors, correction fails.
        """
        if len(encoded_data) != self.ENCODED_SIZE:
            raise ValueError(
                f"Invalid encoded data size: {len(encoded_data)} bytes "
                f"(expected {self.ENCODED_SIZE})"
            )
        
        try:
            # Split into 3 encoded blocks of 212 bytes each
            encoded_block1 = encoded_data[:self.ENCODED_BLOCK_SIZE]
            encoded_block2 = encoded_data[self.ENCODED_BLOCK_SIZE:self.ENCODED_BLOCK_SIZE*2]
            encoded_block3 = encoded_data[self.ENCODED_BLOCK_SIZE*2:]
            
            # Track per-block results for debugging
            block_errors = []
            
            # Decode each block separately
            try:
                result1 = self.codec.decode(encoded_block1)
                if isinstance(result1, tuple):
                    decoded_msg1, _, errata1 = result1
                else:
                    decoded_msg1 = result1
                    errata1 = bytearray(b'')
                block_errors.append(('Block 1', len(errata1), True))
            except Exception as e1:
                print(f"   [DEBUG] Block 1 decode failed: Too many errors (>64 bytes)")
                block_errors.append(('Block 1', -1, False))
                raise
            
            try:
                result2 = self.codec.decode(encoded_block2)
                if isinstance(result2, tuple):
                    decoded_msg2, _, errata2 = result2
                else:
                    decoded_msg2 = result2
                    errata2 = bytearray(b'')
                block_errors.append(('Block 2', len(errata2), True))
            except Exception as e2:
                print(f"   [DEBUG] Block 2 decode failed: Too many errors (>64 bytes)")
                block_errors.append(('Block 2', -1, False))
                raise
            
            try:
                result3 = self.codec.decode(encoded_block3)
                if isinstance(result3, tuple):
                    decoded_msg3, _, errata3 = result3
                else:
                    decoded_msg3 = result3
                    errata3 = bytearray(b'')
                block_errors.append(('Block 3', len(errata3), True))
            except Exception as e3:
                print(f"   [DEBUG] Block 3 decode failed: Too many errors (>64 bytes)")
                block_errors.append(('Block 3', -1, False))
                raise
            
            # Print per-block stats if all successful
            print(f"   [DEBUG] Per-block error correction:")
            for block_name, errors, success in block_errors:
                status = "[+]" if success else "[X]"
                print(f"      {status} {block_name}: {errors} errors corrected")
            
            # Count total errors corrected across all 3 blocks
            num_errors = len(errata1) + len(errata2) + len(errata3)
            
            # Concatenate blocks to reconstruct original data: 112 + 112 + 112 = 336 bytes
            decoded_msg = decoded_msg1 + decoded_msg2 + decoded_msg3
            
            # Validate decoded size
            if len(decoded_msg) != self.MESSAGE_SIZE:
                raise RuntimeError(
                    f"RS decoding produced unexpected size: {len(decoded_msg)} bytes "
                    f"(expected {self.MESSAGE_SIZE})"
                )
            
            return decoded_msg, num_errors, True
            
        except Exception as e:
            # Too many errors to correct - return corrupted data
            # Extract original message portions from each encoded block (first 112 bytes of each)
            block1_data = encoded_data[:self.BLOCK_SIZE]
            block2_data = encoded_data[self.ENCODED_BLOCK_SIZE:self.ENCODED_BLOCK_SIZE + self.BLOCK_SIZE]
            block3_data = encoded_data[self.ENCODED_BLOCK_SIZE*2:self.ENCODED_BLOCK_SIZE*2 + self.BLOCK_SIZE]
            
            # Concatenate blocks (no deinterleaving needed)
            corrupted_msg = block1_data + block2_data + block3_data
            
            return bytes(corrupted_msg), -1, False
    
    @staticmethod
    def get_info() -> dict:
        """Get RS codec configuration information"""
        return {
            "message_size": ProofRSCodec.MESSAGE_SIZE,
            "num_blocks": ProofRSCodec.NUM_BLOCKS,
            "block_size": ProofRSCodec.BLOCK_SIZE,
            "ecc_per_block": ProofRSCodec.ECC_PER_BLOCK,
            "encoded_size": ProofRSCodec.ENCODED_SIZE,
            "max_correctable_errors_per_block": ProofRSCodec.ECC_PER_BLOCK // 2,
            "max_correctable_errors_total": (ProofRSCodec.ECC_PER_BLOCK // 2) * ProofRSCodec.NUM_BLOCKS,
            "error_rate_tolerance": "57%",
            "overhead_percentage": f"{(ProofRSCodec.ECC_PER_BLOCK * ProofRSCodec.NUM_BLOCKS / ProofRSCodec.MESSAGE_SIZE) * 100:.1f}%",
            "interleaving": "frame-level (in embedder)",
            "interleaving_pattern": "3-way byte interleaving (distributes burst errors across blocks)"
        }

