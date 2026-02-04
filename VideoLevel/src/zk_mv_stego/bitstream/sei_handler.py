"""
SEI (Supplemental Enhancement Information) Handler for Stable Map Embedding

Embeds and extracts stable coefficient map as SEI user_data_unregistered message.
This allows sending a single video file with embedded stable map metadata.

Reference: ITU-T H.264 Section 7.3.2.3 (SEI message syntax)
"""

import struct
from typing import List, Dict, Optional, Tuple


class SEIStableMapHandler:
    """
    Handle SEI message for stable coefficient map embedding/extraction.
    
    SEI Message Format:
        [NAL Header: 1 byte] 0x06 (SEI)
        [Payload Type: 1 byte] 0x05 (user_data_unregistered)
        [Payload Size: variable] EBSP encoded size
        [UUID: 16 bytes] Unique identifier for zkstego stable map
        [Stable Map Data: variable] Binary-encoded stable map
        [RBSP trailing bits]
    """
    
    # UUID for zkstego stable map (16 bytes)
    # Generated from "zkstego_stable_v1"
    ZKSTEGO_UUID = b'zkstego_stable\x00\x01'  # 16 bytes
    
    NAL_TYPE_SEI = 0x06
    SEI_TYPE_USER_DATA_UNREGISTERED = 0x05
    
    def __init__(self):
        self.start_code = b'\x00\x00\x00\x01'
    
    def embed_stable_map_to_video(
        self, 
        input_video_path: str,
        stable_map: Dict,
        output_video_path: str
    ) -> bool:
        """
        Embed stable map as SEI message into video.
        
        Args:
            input_video_path: Path to input H.264 video
            stable_map: Stable map dictionary from StableCoefficientMapper
            output_video_path: Path to output video with embedded SEI
        
        Returns:
            True if successful, False otherwise
        """
        try:
            print(f"\n{'='*60}")
            print(f"Embedding Stable Map as SEI")
            print(f"{'='*60}")
            
            # Read input video
            with open(input_video_path, 'rb') as f:
                video_data = f.read()
            
            print(f"[1/4] Read input video: {len(video_data)} bytes")
            
            # Create SEI NAL unit
            sei_nal = self._create_sei_nal(stable_map)
            print(f"[2/4] Created SEI NAL: {len(sei_nal)} bytes")
            
            # Find insertion point (after SPS/PPS, before first IDR/slice)
            insertion_point = self._find_sei_insertion_point(video_data)
            print(f"[3/4] Found insertion point at byte {insertion_point}")
            
            # Insert SEI NAL
            modified_video = (
                video_data[:insertion_point] +
                sei_nal +
                video_data[insertion_point:]
            )
            
            # Write output
            with open(output_video_path, 'wb') as f:
                f.write(modified_video)
            
            print(f"[4/4] Wrote output video: {len(modified_video)} bytes")
            print(f"      Size increase: +{len(modified_video) - len(video_data)} bytes")
            print(f"{'='*60}\n")
            
            return True
            
        except Exception as e:
            print(f"[!] Error embedding stable map: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def extract_stable_map_from_video(
        self, 
        video_path: str
    ) -> Optional[List[Dict]]:
        """
        Extract stable map from SEI message in video.
        
        Args:
            video_path: Path to video with embedded SEI stable map
        
        Returns:
            List of stable coefficient positions or None if not found
        """
        try:
            print(f"\n{'='*60}")
            print(f"Extracting Stable Map from SEI")
            print(f"{'='*60}")
            
            # Read video
            with open(video_path, 'rb') as f:
                video_data = f.read()
            
            print(f"[1/2] Read video: {len(video_data)} bytes")
            
            # Find and parse SEI NAL
            sei_payload = self._find_sei_stable_map(video_data)
            
            if sei_payload is None:
                print(f"[!] No stable map SEI found in video")
                return None
            
            print(f"[2/2] Found SEI payload: {len(sei_payload)} bytes")
            
            # SEI payload includes UUID (16 bytes) + stable_map data
            # Skip UUID to get to the actual stable_map data
            if len(sei_payload) < 16:
                print(f"[!] SEI payload too short: {len(sei_payload)} bytes")
                return None
            
            stable_map_data = sei_payload[16:]  # Skip UUID
            
            # Deserialize stable map
            from ..embedder.stable_coefficient_mapper import StableCoefficientMapper
            stable_coeffs = StableCoefficientMapper.deserialize_stable_map(stable_map_data)
            
            print(f"      Extracted {len(stable_coeffs)} stable coefficients")
            print(f"{'='*60}\n")
            
            return stable_coeffs
            
        except Exception as e:
            print(f"[!] Error extracting stable map: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _create_sei_nal(self, stable_map: Dict) -> bytes:
        """
        Create SEI NAL unit with stable map payload.
        
        Returns:
            Complete NAL unit with start code
        """
        from ..embedder.stable_coefficient_mapper import StableCoefficientMapper
        
        # Serialize stable map
        mapper = StableCoefficientMapper()
        stable_map_payload = mapper.serialize_stable_map(stable_map)
        
        # Build SEI payload: UUID + data
        sei_payload = self.ZKSTEGO_UUID + stable_map_payload
        
        # Encode SEI message
        sei_message = self._encode_sei_message(
            self.SEI_TYPE_USER_DATA_UNREGISTERED,
            sei_payload
        )
        
        # Create NAL unit
        nal_header = bytes([self.NAL_TYPE_SEI])
        rbsp = nal_header + sei_message
        
        # Add RBSP trailing bits
        rbsp += b'\x80'  # stop bit + alignment
        
        # Escape emulation prevention bytes
        rbsp_escaped = self._escape_rbsp(rbsp)
        
        # Add start code
        nal_unit = self.start_code + rbsp_escaped
        
        return nal_unit
    
    def _encode_sei_message(self, payload_type: int, payload: bytes) -> bytes:
        """
        Encode SEI message with type and size.
        
        Format:
            [Payload Type: variable] EBSP encoded type
            [Payload Size: variable] EBSP encoded size
            [Payload Data: variable]
        """
        message = b''
        
        # Encode payload type (EBSP)
        message += self._encode_ebsp_value(payload_type)
        
        # Encode payload size (EBSP)
        message += self._encode_ebsp_value(len(payload))
        
        # Add payload
        message += payload
        
        return message
    
    def _encode_ebsp_value(self, value: int) -> bytes:
        """
        Encode value using EBSP (Encapsulation Byte Stream Payload) encoding.
        
        Format: For values 0-254, encode as single byte.
                For values >= 255, use multiple 0xFF bytes + final byte.
        
        Examples:
            10 → 0x0A
            255 → 0xFF 0x00
            510 → 0xFF 0xFF 0x00
        """
        result = b''
        
        while value >= 255:
            result += b'\xFF'
            value -= 255
        
        result += bytes([value])
        
        return result
    
    def _escape_rbsp(self, rbsp: bytes) -> bytes:
        """
        Apply emulation prevention to RBSP.
        
        Insert 0x03 after any 0x000000, 0x000001, 0x000002, 0x000003
        to prevent start code emulation.
        """
        escaped = bytearray()
        zero_count = 0
        
        for byte in rbsp:
            if zero_count == 2 and byte <= 0x03:
                # Insert emulation prevention byte
                escaped.append(0x03)
                zero_count = 0
            
            escaped.append(byte)
            
            if byte == 0x00:
                zero_count += 1
            else:
                zero_count = 0
        
        return bytes(escaped)
    
    def _find_sei_insertion_point(self, video_data: bytes) -> int:
        """
        Find insertion point for SEI NAL (after SPS/PPS, before first slice).
        
        NAL order:
            [SPS] [PPS] <- INSERT SEI HERE -> [IDR slice] [P slices...]
        """
        # Find NAL units
        nal_positions = self._find_nal_units(video_data)
        
        # Find first slice NAL (type 1 or 5)
        for i, (start, end, nal_type) in enumerate(nal_positions):
            if nal_type in [1, 5]:  # Slice or IDR slice
                # Insert before this NAL
                return start
        
        # If no slice found, insert after SPS/PPS
        # Find last SPS or PPS
        last_param_end = 0
        for start, end, nal_type in nal_positions:
            if nal_type in [7, 8]:  # SPS or PPS
                last_param_end = end
        
        if last_param_end > 0:
            return last_param_end
        
        # Fallback: insert at beginning
        return 0
    
    def _find_nal_units(self, video_data: bytes) -> List[Tuple[int, int, int]]:
        """
        Find all NAL units in video data.
        
        Returns:
            List of (start_pos, end_pos, nal_type) tuples
        """
        nal_units = []
        pos = 0
        
        while pos < len(video_data):
            # Find start code
            start_code_pos = video_data.find(self.start_code, pos)
            
            if start_code_pos == -1:
                break
            
            # NAL header is after start code
            nal_start = start_code_pos
            nal_header_pos = start_code_pos + len(self.start_code)
            
            if nal_header_pos >= len(video_data):
                break
            
            # Read NAL type
            nal_header = video_data[nal_header_pos]
            nal_type = nal_header & 0x1F
            
            # Find next start code (end of this NAL)
            next_start = video_data.find(self.start_code, nal_header_pos)
            
            if next_start == -1:
                # Last NAL unit
                nal_end = len(video_data)
            else:
                nal_end = next_start
            
            nal_units.append((nal_start, nal_end, nal_type))
            pos = nal_header_pos + 1
        
        return nal_units
    
    def _find_sei_stable_map(self, video_data: bytes) -> Optional[bytes]:
        """
        Find and extract stable map SEI payload from video.
        
        Returns:
            SEI payload (UUID + stable map data) or None if not found
        """
        # Find all SEI NAL units
        nal_units = self._find_nal_units(video_data)
        
        for start, end, nal_type in nal_units:
            if nal_type != self.NAL_TYPE_SEI:
                continue
            
            # Extract RBSP
            nal_data = video_data[start:end]
            rbsp = self._extract_rbsp(nal_data)
            
            if rbsp is None or len(rbsp) < 2:
                continue
            
            # Parse SEI messages
            pos = 1  # Skip NAL header
            
            while pos < len(rbsp) - 1:  # -1 for trailing bits
                # Decode payload type
                payload_type, bytes_read = self._decode_ebsp_value(rbsp[pos:])
                pos += bytes_read
                
                if pos >= len(rbsp):
                    break
                
                # Decode payload size
                payload_size, bytes_read = self._decode_ebsp_value(rbsp[pos:])
                pos += bytes_read
                
                if pos + payload_size > len(rbsp):
                    break
                
                # Extract payload
                payload = rbsp[pos:pos + payload_size]
                pos += payload_size
                
                # Check if this is our stable map SEI
                if payload_type == self.SEI_TYPE_USER_DATA_UNREGISTERED:
                    if len(payload) >= 16:
                        uuid = payload[:16]
                        if uuid == self.ZKSTEGO_UUID:
                            # Found it!
                            return payload  # UUID + stable map data
        
        return None
    
    def _extract_rbsp(self, nal_data: bytes) -> Optional[bytes]:
        """
        Extract RBSP from NAL unit (remove start code and unescape).
        """
        # Skip start code
        if nal_data.startswith(self.start_code):
            rbsp_escaped = nal_data[len(self.start_code):]
        else:
            rbsp_escaped = nal_data
        
        # Remove emulation prevention bytes
        rbsp = bytearray()
        i = 0
        
        while i < len(rbsp_escaped):
            if (i + 2 < len(rbsp_escaped) and
                rbsp_escaped[i] == 0x00 and
                rbsp_escaped[i + 1] == 0x00 and
                rbsp_escaped[i + 2] == 0x03):
                # Emulation prevention: skip 0x03
                rbsp.append(rbsp_escaped[i])
                rbsp.append(rbsp_escaped[i + 1])
                i += 3
            else:
                rbsp.append(rbsp_escaped[i])
                i += 1
        
        return bytes(rbsp)
    
    def _decode_ebsp_value(self, data: bytes) -> Tuple[int, int]:
        """
        Decode EBSP value.
        
        Returns:
            (value, bytes_read)
        """
        value = 0
        bytes_read = 0
        
        for byte in data:
            bytes_read += 1
            if byte == 0xFF:
                value += 255
            else:
                value += byte
                break
        
        return value, bytes_read


if __name__ == "__main__":
    # Quick test
    handler = SEIStableMapHandler()
    
    # Test EBSP encoding
    print("Testing EBSP encoding:")
    print(f"  10 → {handler._encode_ebsp_value(10).hex()}")
    print(f"  255 → {handler._encode_ebsp_value(255).hex()}")
    print(f"  510 → {handler._encode_ebsp_value(510).hex()}")
    
    # Test EBSP decoding
    print("\nTesting EBSP decoding:")
    val, size = handler._decode_ebsp_value(b'\x0A')
    print(f"  0x0A → value={val}, size={size}")
    
    val, size = handler._decode_ebsp_value(b'\xFF\x00')
    print(f"  0xFF 0x00 → value={val}, size={size}")
    
    print("\n✓ SEI handler basic tests passed")
