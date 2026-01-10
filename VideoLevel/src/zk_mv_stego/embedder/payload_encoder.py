"""
Phase 1: MV Embedding System
=============================

Architecture Overview:
    Input: H.264 video + Payload (bytes)
    ↓
    1. Extract MVs using PyAV
    2. Select carrier MVs (chaos-based)
    3. Encode payload with ECC
    4. Modify MV LSBs
    5. Re-encode video with modified MVs
    ↓
    Output: Stego video

Components:
- payload_encoder.py:     Payload → bits with ECC & header
- carrier_selector.py:    Chaos-based MV selection
- mv_embedder.py:         LSB parity embedding
- mv_extractor.py:        Extract & decode payload
- encoder_wrapper.py:     x264 wrapper with MV injection
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional
import hashlib
import struct


@dataclass
class PayloadHeader:
    """Payload header structure"""
    magic: bytes = b'ZKST'  # Magic number
    version: int = 1
    payload_length: int = 0  # Original payload length
    ecc_type: int = 1  # 1=Reed-Solomon
    chunk_size: int = 32  # Bytes per chunk
    chaos_seed: int = 0  # For carrier selection
    checksum: int = 0  # CRC32 of payload
    
    def to_bytes(self) -> bytes:
        """Serialize header to bytes"""
        return struct.pack(
            '<4sHHBBII',  # Little-endian format (18 bytes)
            self.magic,
            self.version,
            self.payload_length,
            self.ecc_type,
            self.chunk_size,
            self.chaos_seed,
            self.checksum
        )
    
    @classmethod
    def from_bytes(cls, data: bytes) -> 'PayloadHeader':
        """Deserialize header from bytes"""
        if len(data) < 18:
            raise ValueError(f"Header too short: {len(data)} < 18 bytes")
        
        print(f"[DEBUG] Unpacking header: {data[:18].hex()}")
        print(f"[DEBUG] Format: <4sHHBBII (18 bytes)")
        unpacked = struct.unpack('<4sHHBBII', data[:18])
        print(f"[DEBUG] Unpacked: {unpacked}")
        return cls(
            magic=unpacked[0],
            version=unpacked[1],
            payload_length=unpacked[2],
            ecc_type=unpacked[3],
            chunk_size=unpacked[4],
            chaos_seed=unpacked[5],
            checksum=unpacked[6]
        )
    
    @staticmethod
    def size() -> int:
        """Header size in bytes"""
        return 18


@dataclass
class EmbeddingConfig:
    """Configuration for embedding process"""
    method: str = 'lsb_parity'  # 'lsb_parity' or 'qim'
    component: str = 'mvx'  # 'mvx', 'mvy', or 'both'
    min_magnitude: float = 2.0  # Minimum MV magnitude (stable under ±1 modification)
    max_magnitude: float = 50.0  # Maximum MV magnitude to use
    embedding_rate: float = 0.1  # Use only 10% of MVs (sparse)
    chaos_map: str = 'logistic'  # 'logistic' or 'arnold'
    ecc_enabled: bool = True
    ecc_redundancy: float = 0.3  # 30% redundancy


class PayloadEncoder:
    """Encode payload with header and ECC"""
    
    def __init__(self, config: EmbeddingConfig):
        self.config = config
    
    def encode(self, payload: bytes, chaos_seed: int) -> bytes:
        """
        Encode payload with header + ECC
        
        Args:
            payload: Raw payload bytes
            chaos_seed: Seed for chaos-based selection
            
        Returns:
            Encoded bitstream (header + ECC-encoded payload)
        """
        # Calculate checksum
        checksum = self._crc32(payload)
        
        # Create header
        header = PayloadHeader(
            payload_length=len(payload),
            chaos_seed=chaos_seed,
            checksum=checksum,
            ecc_type=1 if self.config.ecc_enabled else 0,
            chunk_size=32
        )
        
        # Encode with ECC if enabled
        if self.config.ecc_enabled:
            encoded_payload = self._add_ecc(payload)
        else:
            encoded_payload = payload
        
        # Combine header + payload
        full_data = header.to_bytes() + encoded_payload
        
        return full_data
    
    def _add_ecc(self, data: bytes) -> bytes:
        """
        Add Reed-Solomon error correction
        
        Reed-Solomon(255, 223): 32 bytes parity per 223 bytes data
        """
        try:
            import reedsolo
            rs = reedsolo.RSCodec(32)  # 32 parity bytes
            return rs.encode(data)
        except ImportError:
            print("[WARNING] reedsolo not installed, skipping ECC")
            return data
    
    def _crc32(self, data: bytes) -> int:
        """Calculate CRC32 checksum"""
        import zlib
        return zlib.crc32(data) & 0xffffffff


class PayloadDecoder:
    """Decode payload from extracted bits"""
    
    def decode(self, data: bytes) -> Tuple[Optional[bytes], bool]:
        """
        Decode payload from bitstream
        
        Args:
            data: Extracted bytes (header + ECC payload)
            
        Returns:
            (payload, valid) tuple
        """
        try:
            # Parse header
            print(f"[DEBUG] Decoding data of length: {len(data)} bytes")
            print(f"[DEBUG] First 30 bytes: {data[:30].hex() if len(data) >= 30 else data.hex()}")
            
            if len(data) < PayloadHeader.size():
                print(f"[ERROR] Data too short: {len(data)} < {PayloadHeader.size()}")
                return None, False
            
            print(f"[DEBUG] Parsing header from first 18 bytes...")
            header = PayloadHeader.from_bytes(data[:18])
            print(f"[DEBUG] Header parsed: magic={header.magic}, version={header.version}, payload_length={header.payload_length}")
            
            # Verify magic
            if header.magic != b'ZKST':
                print(f"[ERROR] Invalid magic: {header.magic}")
                return None, False
            
            # Extract payload
            payload_data = data[18:]
            print(f"[DEBUG] Payload data length: {len(payload_data)} bytes")
            
            # Decode ECC if enabled
            if header.ecc_type == 1:
                try:
                    import reedsolo
                    rs = reedsolo.RSCodec(32)
                    print(f"[DEBUG] ECC decode input: {len(payload_data)} bytes")
                    decoded = rs.decode(payload_data)
                    print(f"[DEBUG] ECC decode output: {decoded}")
                    payload = decoded[0]
                    print(f"[DEBUG] Payload after ECC: {len(payload)} bytes")
                except Exception as e:
                    print(f"[ERROR] ECC decode failed: {e}")
                    print(f"[WARNING] Trying without ECC correction...")
                    # Try without ECC
                    payload = payload_data
                    if len(payload) > header.payload_length:
                        payload = payload[:header.payload_length]
            else:
                payload = payload_data
            
            # Verify checksum
            checksum = self._crc32(payload[:header.payload_length])
            if checksum != header.checksum:
                print(f"[ERROR] Checksum mismatch: {checksum} != {header.checksum}")
                return None, False
            
            return payload[:header.payload_length], True
            
        except Exception as e:
            print(f"[ERROR] Decode failed: {e}")
            return None, False
    
    def _crc32(self, data: bytes) -> int:
        """Calculate CRC32 checksum"""
        import zlib
        return zlib.crc32(data) & 0xffffffff


def bytes_to_bits(data: bytes) -> List[int]:
    """Convert bytes to bit list"""
    bits = []
    for byte in data:
        for i in range(8):
            bits.append((byte >> (7 - i)) & 1)
    return bits


def bits_to_bytes(bits: List[int]) -> bytes:
    """Convert bit list to bytes"""
    # Pad to multiple of 8
    while len(bits) % 8 != 0:
        bits.append(0)
    
    bytes_list = []
    for i in range(0, len(bits), 8):
        byte = 0
        for j in range(8):
            byte |= bits[i + j] << (7 - j)
        bytes_list.append(byte)
    
    return bytes(bytes_list)


if __name__ == '__main__':
    # Test payload encoding/decoding
    config = EmbeddingConfig()
    encoder = PayloadEncoder(config)
    decoder = PayloadDecoder()
    
    # Test payload
    test_payload = b"Hello ZK-SNARK Steganography! This is a test message."
    
    print(f"Original payload: {len(test_payload)} bytes")
    print(f"Content: {test_payload}")
    
    # Encode
    encoded = encoder.encode(test_payload, chaos_seed=12345)
    print(f"\nEncoded payload: {len(encoded)} bytes")
    print(f"Overhead: {len(encoded) - len(test_payload)} bytes ({100*(len(encoded)/len(test_payload)-1):.1f}%)")
    
    # Decode
    decoded, valid = decoder.decode(encoded)
    print(f"\nDecoded: {valid}")
    print(f"Content: {decoded}")
    print(f"Match: {decoded == test_payload}")
