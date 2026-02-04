"""
ZK Proof SEI Handler - GIAI ĐOẠN 1 & 2
=======================================

Nhúng ZK Proof vào SEI NAL unit với cấu trúc chuẩn:
- UUID: 16 bytes (identifier)
- Data Size: 4 bytes (proof length)
- ZK Proof: ~192 bytes (Groth16 proof)
- Checksum: 4 bytes (CRC32)

Tuân thủ H.264 RBSP (emulation prevention bytes)
"""

import struct
import uuid
import zlib
from typing import Optional, Tuple


class ZKProofSEIHandler:
    """Handler for embedding/extracting ZK proofs in SEI NAL units"""
    
    # UUID cho ZK Proof SEI (cố định để nhận diện)
    # Generated once: uuid.uuid5(uuid.NAMESPACE_DNS, 'zkproof.steganography.v1')
    ZKPROOF_UUID = uuid.UUID('a1b2c3d4-e5f6-5a1b-8c9d-0e1f2a3b4c5d')
    
    # SEI NAL unit type
    SEI_NAL_TYPE = 0x06
    
    # SEI payload type: user_data_unregistered
    SEI_USER_DATA_UNREGISTERED = 0x05
    
    def __init__(self):
        self.uuid_bytes = self.ZKPROOF_UUID.bytes
    
    def create_sei_payload(self, zkproof_bytes: bytes) -> bytes:
        """
        Tạo SEI payload với cấu trúc:
        [UUID 16B][Size 4B][Proof NB][CRC32 4B]
        
        Args:
            zkproof_bytes: ZK proof binary data
            
        Returns:
            Complete SEI payload
        """
        # 1. UUID (16 bytes)
        payload = self.uuid_bytes
        
        # 2. Data size (4 bytes, big-endian)
        proof_size = len(zkproof_bytes)
        payload += struct.pack('>I', proof_size)
        
        # 3. ZK Proof content
        payload += zkproof_bytes
        
        # 4. CRC32 checksum (4 bytes)
        # Checksum covers UUID + Size + Proof
        checksum = zlib.crc32(payload) & 0xFFFFFFFF
        payload += struct.pack('>I', checksum)
        
        return payload
    
    def apply_rbsp_encoding(self, data: bytes) -> bytes:
        """
        Apply RBSP emulation prevention bytes.
        
        H.264 spec: Nếu có sequence 0x000000, 0x000001, 0x000002, 0x000003
        thì chèn 0x03 sau 0x0000 -> 0x00000300, 0x00000301, 0x00000302, 0x00000303
        
        Điều này ngăn decoder nhầm lẫn với NAL start codes.
        
        Args:
            data: Raw payload data
            
        Returns:
            RBSP-encoded data
        """
        result = bytearray()
        zero_count = 0
        
        for byte in data:
            # Đếm số lượng 0x00 liên tiếp
            if byte == 0x00:
                zero_count += 1
                result.append(byte)
            else:
                # Nếu có 2 byte 0x00 liên tiếp và byte tiếp theo <= 0x03
                # thì chèn emulation prevention byte 0x03
                if zero_count >= 2 and byte <= 0x03:
                    result.append(0x03)  # Emulation prevention byte
                
                result.append(byte)
                zero_count = 0
        
        return bytes(result)
    
    def remove_rbsp_encoding(self, data: bytes) -> bytes:
        """
        Remove RBSP emulation prevention bytes.
        
        Ngược lại với apply_rbsp_encoding: tìm pattern 0x000003XX
        và loại bỏ byte 0x03.
        
        Args:
            data: RBSP-encoded data
            
        Returns:
            Raw payload data
        """
        result = bytearray()
        i = 0
        
        while i < len(data):
            # Check for emulation prevention pattern: 0x000003
            if (i + 2 < len(data) and 
                data[i] == 0x00 and 
                data[i+1] == 0x00 and 
                data[i+2] == 0x03):
                # Copy 0x0000, skip 0x03
                result.append(0x00)
                result.append(0x00)
                i += 3  # Skip to byte after 0x03
            else:
                result.append(data[i])
                i += 1
        
        return bytes(result)
    
    def create_sei_nal_unit(self, zkproof_bytes: bytes) -> bytes:
        """
        Tạo complete SEI NAL unit.
        
        Structure:
        [Start Code 4B][NAL Header 1B][SEI Type 1B][Payload Size][Payload][Trailing]
        
        Args:
            zkproof_bytes: ZK proof data
            
        Returns:
            Complete NAL unit bytes (with start code)
        """
        # 1. Create payload
        payload = self.create_sei_payload(zkproof_bytes)
        
        # 2. Apply RBSP encoding
        rbsp_payload = self.apply_rbsp_encoding(payload)
        
        # 3. Build NAL unit
        nal_unit = bytearray()
        
        # NAL Header: forbidden_zero_bit(1) + nal_ref_idc(2) + nal_unit_type(5)
        # SEI: nal_ref_idc = 0, nal_unit_type = 6
        nal_header = 0x06  # 00000110
        nal_unit.append(nal_header)
        
        # SEI payload type (user_data_unregistered = 5)
        nal_unit.append(self.SEI_USER_DATA_UNREGISTERED)
        
        # Payload size (using variable-length encoding)
        payload_size = len(rbsp_payload)
        while payload_size >= 255:
            nal_unit.append(0xFF)
            payload_size -= 255
        nal_unit.append(payload_size)
        
        # Payload
        nal_unit.extend(rbsp_payload)
        
        # RBSP trailing bits (alignment to byte boundary)
        # rbsp_stop_one_bit = 1, followed by zeros
        nal_unit.append(0x80)  # 10000000
        
        # 4. Add start code (4-byte version: 0x00000001)
        complete_nal = bytearray([0x00, 0x00, 0x00, 0x01])
        complete_nal.extend(nal_unit)
        
        return bytes(complete_nal)
    
    def embed_proof_in_video(self, input_video: str, zkproof_bytes: bytes, 
                            output_video: str) -> dict:
        """
        Nhúng ZK proof vào video file.
        
        Chiến lược: Insert SEI NAL trước IDR frame đầu tiên
        
        Args:
            input_video: Input video path
            zkproof_bytes: ZK proof data
            output_video: Output video path
            
        Returns:
            Statistics dict
        """
        print("="*70)
        print("EMBEDDING ZK PROOF INTO SEI")
        print("="*70)
        
        # 1. Read input video
        with open(input_video, 'rb') as f:
            video_data = f.read()
        
        print(f"[1/5] Read input video: {len(video_data):,} bytes")
        
        # 2. Create SEI NAL unit
        sei_nal = self.create_sei_nal_unit(zkproof_bytes)
        print(f"[2/5] Created SEI NAL: {len(sei_nal):,} bytes")
        print(f"      Proof size: {len(zkproof_bytes)} bytes")
        print(f"      UUID: {self.ZKPROOF_UUID}")
        
        # 3. Find insertion point (before first IDR frame)
        # IDR frame: NAL type = 5 (0x65 or 0x25 with nal_ref_idc)
        insertion_point = self._find_idr_frame(video_data)
        
        if insertion_point is None:
            print("[WARNING] No IDR frame found, inserting at end")
            insertion_point = len(video_data)
        else:
            print(f"[3/5] Found IDR frame at byte {insertion_point:,}")
        
        # 4. Insert SEI NAL
        output_data = (
            video_data[:insertion_point] +
            sei_nal +
            video_data[insertion_point:]
        )
        
        print(f"[4/5] Inserted SEI at position {insertion_point:,}")
        
        # 5. Write output
        with open(output_video, 'wb') as f:
            f.write(output_data)
        
        size_increase = len(output_data) - len(video_data)
        print(f"[5/5] Wrote output video: {len(output_data):,} bytes")
        print(f"      Size increase: +{size_increase:,} bytes")
        
        print("="*70)
        
        return {
            'input_size': len(video_data),
            'output_size': len(output_data),
            'sei_size': len(sei_nal),
            'proof_size': len(zkproof_bytes),
            'insertion_point': insertion_point,
            'success': True
        }
    
    def _find_idr_frame(self, video_data: bytes) -> Optional[int]:
        """
        Tìm vị trí của IDR frame đầu tiên.
        
        IDR frame có NAL type = 5
        Start codes: 0x000001 hoặc 0x00000001
        
        Args:
            video_data: Video bitstream
            
        Returns:
            Byte offset of IDR frame, or None if not found
        """
        i = 0
        while i < len(video_data) - 4:
            # Check for start code
            if video_data[i:i+3] == b'\x00\x00\x01':
                nal_header = video_data[i+3]
                nal_type = nal_header & 0x1F
                
                if nal_type == 5:  # IDR frame
                    return i
                
                i += 3
            elif video_data[i:i+4] == b'\x00\x00\x00\x01':
                nal_header = video_data[i+4]
                nal_type = nal_header & 0x1F
                
                if nal_type == 5:  # IDR frame
                    return i
                
                i += 4
            else:
                i += 1
        
        return None
    
    def extract_proof_from_video(self, video_path: str) -> Tuple[Optional[bytes], dict]:
        """
        Trích xuất ZK proof từ video.
        
        Args:
            video_path: Path to video file
            
        Returns:
            (proof_bytes, statistics)
            proof_bytes is None if not found or invalid
        """
        print("="*70)
        print("EXTRACTING ZK PROOF FROM SEI")
        print("="*70)
        
        # 1. Read video
        with open(video_path, 'rb') as f:
            video_data = f.read()
        
        print(f"[1/4] Read video: {len(video_data):,} bytes")
        
        # 2. Find SEI NAL units
        sei_nals = self._find_sei_nals(video_data)
        print(f"[2/4] Found {len(sei_nals)} SEI NAL unit(s)")
        
        if not sei_nals:
            print("[ERROR] No SEI NAL units found")
            return None, {'success': False, 'error': 'No SEI found'}
        
        # 3. Extract and verify each SEI
        for idx, (offset, nal_data) in enumerate(sei_nals):
            print(f"\n[3/{idx+3}] Processing SEI #{idx+1} at offset {offset:,}")
            
            try:
                proof = self._extract_proof_from_sei_nal(nal_data)
                
                if proof is not None:
                    print(f"[SUCCESS] Extracted ZK proof: {len(proof)} bytes")
                    print(f"          Checksum: VALID ✓")
                    print("="*70)
                    
                    return proof, {
                        'success': True,
                        'proof_size': len(proof),
                        'sei_offset': offset,
                        'sei_index': idx
                    }
                else:
                    print(f"[SKIP] SEI #{idx+1} is not ZK proof (wrong UUID or checksum)")
            
            except Exception as e:
                print(f"[ERROR] Failed to parse SEI #{idx+1}: {e}")
                continue
        
        print("\n[ERROR] No valid ZK proof found in any SEI")
        print("="*70)
        
        return None, {'success': False, 'error': 'No valid proof found'}
    
    def _find_sei_nals(self, video_data: bytes) -> list:
        """
        Tìm tất cả SEI NAL units trong video.
        
        Returns:
            List of (offset, nal_data) tuples
        """
        sei_nals = []
        i = 0
        
        while i < len(video_data) - 4:
            start_code_len = 0
            
            # Check for 3-byte start code
            if video_data[i:i+3] == b'\x00\x00\x01':
                start_code_len = 3
            # Check for 4-byte start code
            elif video_data[i:i+4] == b'\x00\x00\x00\x01':
                start_code_len = 4
            
            if start_code_len > 0:
                nal_header = video_data[i + start_code_len]
                nal_type = nal_header & 0x1F
                
                if nal_type == 6:  # SEI
                    # Find next start code to get NAL length
                    next_start = self._find_next_start_code(video_data, i + start_code_len + 1)
                    
                    if next_start is None:
                        nal_data = video_data[i + start_code_len:]
                    else:
                        nal_data = video_data[i + start_code_len:next_start]
                    
                    sei_nals.append((i, nal_data))
                
                i += start_code_len
            else:
                i += 1
        
        return sei_nals
    
    def _find_next_start_code(self, data: bytes, start: int) -> Optional[int]:
        """Find next NAL start code"""
        i = start
        while i < len(data) - 4:
            if data[i:i+3] == b'\x00\x00\x01':
                return i
            elif data[i:i+4] == b'\x00\x00\x00\x01':
                return i
            i += 1
        return None
    
    def _extract_proof_from_sei_nal(self, nal_data: bytes) -> Optional[bytes]:
        """
        Extract ZK proof from SEI NAL unit data.
        
        Args:
            nal_data: NAL unit without start code (starts with NAL header)
            
        Returns:
            Proof bytes or None if invalid
        """
        if len(nal_data) < 2:
            return None
        
        # Parse NAL header (already removed)
        # nal_data[0] is NAL header (should be 0x06)
        
        # Parse SEI type
        sei_type = nal_data[1]
        
        if sei_type != self.SEI_USER_DATA_UNREGISTERED:
            return None
        
        # Parse payload size (variable length)
        idx = 2
        payload_size = 0
        while idx < len(nal_data):
            byte = nal_data[idx]
            payload_size += byte
            idx += 1
            if byte != 0xFF:
                break
        
        # Extract RBSP payload
        rbsp_start = idx
        rbsp_end = rbsp_start + payload_size
        
        if rbsp_end > len(nal_data):
            return None
        
        rbsp_payload = nal_data[rbsp_start:rbsp_end]
        
        # Remove RBSP encoding
        raw_payload = self.remove_rbsp_encoding(rbsp_payload)
        
        # Parse payload structure
        # [UUID 16B][Size 4B][Proof NB][CRC32 4B]
        
        if len(raw_payload) < 16 + 4 + 4:  # Min size
            return None
        
        # Check UUID
        payload_uuid = raw_payload[:16]
        if payload_uuid != self.uuid_bytes:
            return None  # Not our ZK proof
        
        # Parse size
        proof_size = struct.unpack('>I', raw_payload[16:20])[0]
        
        # Extract proof
        proof_start = 20
        proof_end = proof_start + proof_size
        
        if proof_end + 4 > len(raw_payload):
            return None  # Invalid size
        
        proof_bytes = raw_payload[proof_start:proof_end]
        
        # Verify checksum
        checksum_received = struct.unpack('>I', raw_payload[proof_end:proof_end+4])[0]
        checksum_calculated = zlib.crc32(raw_payload[:proof_end]) & 0xFFFFFFFF
        
        if checksum_received != checksum_calculated:
            print(f"[WARNING] Checksum mismatch: {checksum_received:08x} != {checksum_calculated:08x}")
            return None
        
        return proof_bytes


def test_sei_handler():
    """Test SEI handler với mock ZK proof"""
    
    print("\n" + "="*70)
    print("TESTING ZK PROOF SEI HANDLER")
    print("="*70 + "\n")
    
    handler = ZKProofSEIHandler()
    
    # 1. Create mock ZK proof (192 bytes)
    mock_proof = b"GROTH16_PROOF_" * 13 + b"_PI_A_PI_B_PI_C"
    mock_proof = mock_proof[:192]  # Exactly 192 bytes
    
    print(f"Mock proof: {len(mock_proof)} bytes")
    print(f"First 40 bytes: {mock_proof[:40]}")
    print()
    
    # 2. Test payload creation
    payload = handler.create_sei_payload(mock_proof)
    print(f"✓ Created SEI payload: {len(payload)} bytes")
    print(f"  Structure: UUID(16) + Size(4) + Proof(192) + CRC(4) = {16+4+192+4} bytes")
    print()
    
    # 3. Test RBSP encoding
    rbsp = handler.apply_rbsp_encoding(payload)
    print(f"✓ RBSP encoded: {len(payload)} -> {len(rbsp)} bytes")
    
    # Test decoding
    decoded = handler.remove_rbsp_encoding(rbsp)
    assert decoded == payload, "RBSP decode failed!"
    print(f"✓ RBSP decode: Verified ✓")
    print()
    
    # 4. Test NAL unit creation
    nal = handler.create_sei_nal_unit(mock_proof)
    print(f"✓ Created SEI NAL: {len(nal)} bytes")
    print(f"  Start code: {nal[:4].hex()}")
    print(f"  NAL header: 0x{nal[4]:02x} (should be 0x06)")
    print(f"  SEI type:   0x{nal[5]:02x} (should be 0x05)")
    print()
    
    # 5. Test extraction from NAL
    extracted = handler._extract_proof_from_sei_nal(nal[4:])  # Skip start code
    
    if extracted == mock_proof:
        print(f"✓ Extraction: SUCCESS ✓")
        print(f"  Extracted {len(extracted)} bytes")
        print(f"  Match: {extracted == mock_proof}")
    else:
        print(f"✗ Extraction: FAILED")
        print(f"  Expected: {mock_proof[:40]}...")
        print(f"  Got:      {extracted[:40] if extracted else 'None'}...")
    
    print("\n" + "="*70)
    print("TEST COMPLETE")
    print("="*70 + "\n")


if __name__ == "__main__":
    test_sei_handler()
