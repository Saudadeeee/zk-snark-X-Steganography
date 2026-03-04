"""
H.264 Bitstream Parser for Quantized DCT Steganography

This module parses H.264 bitstream to access quantized DCT coefficients (levels).
Based on ITU-T H.264 specification.

Key concepts:
- NAL units: Network Abstraction Layer packets
- Slice: Group of macroblocks
- Macroblock: 16x16 pixel block
- Residual: Quantized DCT coefficients after prediction
- Levels: Integer coefficient values (what we want to modify)
"""

import struct
from typing import List, Tuple, BinaryIO
from dataclasses import dataclass
from enum import IntEnum
from .bitstream_io import BitstreamReader


from .nal_handler import NALUnit, NALUnitType


# BitstreamReader moved to bitstream_io.py


class H264BitstreamParser:
    """
    Parse H.264 bitstream to extract quantized DCT coefficients
    """
    
    def __init__(self, video_path: str):
        self.video_path = video_path
        self.nal_units: List[NALUnit] = []
        
    def parse(self) -> List[NALUnit]:
        """Parse entire bitstream and extract NAL units"""
        print(f"[*] Parsing H.264 bitstream: {self.video_path}")
        
        with open(self.video_path, 'rb') as f:
            data = f.read()
        
        # Find NAL unit start codes
        nal_units = self._find_nal_units(data)
        
        print(f"[+] Found {len(nal_units)} NAL units")
        
        # Parse each NAL unit
        for nal in nal_units:
            self._parse_nal_unit(nal)
        
        self.nal_units = nal_units
        return nal_units
    
    def _find_nal_units(self, data: bytes) -> List[NALUnit]:
        """
        Find NAL units by searching for start codes
        Start codes: 0x000001 or 0x00000001
        """
        nal_units = []
        pos = 0
        
        while pos < len(data) - 3:
            # Look for start code
            if data[pos:pos+3] == b'\x00\x00\x01':
                start_code_len = 3
                nal_start = pos + 3
            elif data[pos:pos+4] == b'\x00\x00\x00\x01':
                start_code_len = 4
                nal_start = pos + 4
            else:
                pos += 1
                continue
            
            # Find next start code
            next_pos = pos + start_code_len
            while next_pos < len(data) - 3:
                if data[next_pos:next_pos+3] == b'\x00\x00\x01' or \
                   data[next_pos:next_pos+4] == b'\x00\x00\x00\x01':
                    break
                next_pos += 1
            
            # Extract NAL unit header
            if nal_start < len(data):
                nal_header = data[nal_start]
                
                forbidden_zero_bit = (nal_header >> 7) & 1
                nal_ref_idc = (nal_header >> 5) & 3
                nal_type_value = nal_header & 0x1F
                
                # Handle unknown NAL types gracefully
                try:
                    nal_unit_type = NALUnitType(nal_type_value)
                except ValueError:
                    print(f"  ⚠️ Unknown NAL type: {nal_type_value}, using UNKNOWN")
                    nal_unit_type = NALUnitType.UNKNOWN
                
                # Extract RBSP
                nal_end = next_pos if next_pos < len(data) else len(data)
                rbsp = data[nal_start+1:nal_end]
                
                # Remove emulation prevention bytes (0x03 after 0x0000)
                rbsp = self._remove_emulation_prevention(rbsp)
                
                nal = NALUnit(
                    forbidden_zero_bit=forbidden_zero_bit,
                    nal_ref_idc=nal_ref_idc,
                    nal_unit_type=nal_unit_type,
                    rbsp_byte=rbsp,
                    start_pos=pos,
                    size=nal_end - pos,
                    start_code_size=start_code_len,
                )
                
                nal_units.append(nal)
            
            pos = next_pos if next_pos < len(data) else len(data)
        
        return nal_units
    
    def _remove_emulation_prevention(self, data: bytes) -> bytes:
        """
        Remove emulation prevention bytes (0x03)
        H.264 inserts 0x03 after 0x0000 to prevent start code emulation
        """
        result = bytearray()
        i = 0
        while i < len(data):
            if i + 2 < len(data) and data[i:i+2] == b'\x00\x00' and data[i+2] == 0x03:
                result.extend(data[i:i+2])
                i += 3  # Skip the 0x03
            else:
                result.append(data[i])
                i += 1
        return bytes(result)
    
    def _parse_nal_unit(self, nal: NALUnit):
        """Parse NAL unit contents based on type"""
        if nal.nal_unit_type == NALUnitType.SPS:
            self._parse_sps(nal)
        elif nal.nal_unit_type == NALUnitType.PPS:
            self._parse_pps(nal)
        elif nal.nal_unit_type in [NALUnitType.SLICE_NON_IDR, NALUnitType.SLICE_IDR]:
            self._parse_slice(nal)
    
    def _parse_sps(self, nal: NALUnit):
        """Parse Sequence Parameter Set (simplified)"""
        print(f"  [SPS] Sequence Parameter Set at offset {nal.start_pos}")
        # Full SPS parsing is complex - skip for now
        # We primarily need slice data for coefficients
    
    def _parse_pps(self, nal: NALUnit):
        """Parse Picture Parameter Set (simplified)"""
        print(f"  [PPS] Picture Parameter Set at offset {nal.start_pos}")
    
    def _parse_slice(self, nal: NALUnit):
        """Parse slice to extract coefficient levels"""
        print(f"  [SLICE] at offset {nal.start_pos} (size: {nal.size} bytes)")
        
        try:
            reader = BitstreamReader(nal.rbsp_byte)
            
            # Parse slice header (simplified)
            first_mb_in_slice = reader.read_ue()
            slice_type = reader.read_ue()
            pic_parameter_set_id = reader.read_ue()
            
            print(f"     First MB: {first_mb_in_slice}, Type: {slice_type}, PPS: {pic_parameter_set_id}")
            
            # TODO: Parse macroblock layer to get residual coefficients
            # This requires full H.264 syntax parsing (very complex)
            
        except Exception as e:
            print(f"     ⚠️ Parse error: {e}")
    
    def extract_coefficient_levels(self) -> List[Tuple[int, List[int]]]:
        """
        Extract quantized DCT coefficient levels from all slices
        
        Returns: List of (macroblock_index, coefficients)
        
        NOTE: This requires FULL H.264 macroblock parsing
        Currently simplified - need to implement:
        1. Macroblock prediction mode parsing
        2. Residual data parsing (CAVLC/CABAC)
        3. Coefficient level extraction
        """
        print("\n⚠️ Full coefficient extraction not yet implemented")
        print("   Requires complete CAVLC/CABAC decoder")
        
        # Placeholder
        return []
    
    def get_statistics(self):
        """Get bitstream statistics"""
        stats = {
            'total_nal_units': len(self.nal_units),
            'sps_count': sum(1 for n in self.nal_units if n.nal_unit_type == NALUnitType.SPS),
            'pps_count': sum(1 for n in self.nal_units if n.nal_unit_type == NALUnitType.PPS),
            'slice_count': sum(1 for n in self.nal_units if n.nal_unit_type in [NALUnitType.SLICE_NON_IDR, NALUnitType.SLICE_IDR]),
        }
        
        return stats


def main():
    """Test the parser"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python h264_bitstream_parser.py <video.mp4>")
        sys.exit(1)
    
    parser = H264BitstreamParser(sys.argv[1])
    nal_units = parser.parse()
    
    stats = parser.get_statistics()
    
    print("\n" + "="*60)
    print("BITSTREAM STATISTICS")
    print("="*60)
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print("\n" + "="*60)
    print("NAL UNIT SUMMARY")
    print("="*60)
    for i, nal in enumerate(nal_units[:10]):  # Show first 10
        print(f"  [{i}] Type: {nal.nal_unit_type.name}, Size: {nal.size} bytes, Offset: {nal.start_pos}")
    
    if len(nal_units) > 10:
        print(f"  ... and {len(nal_units) - 10} more")
    
    print("\n" + "="*60)
    print("NEXT STEPS")
    print("="*60)
    print("  1. ✅ Parse NAL units (DONE)")
    print("  2. ⚠️ Parse macroblock layer (TODO)")
    print("  3. ⚠️ Decode CAVLC/CABAC (TODO - complex!)")
    print("  4. ⚠️ Extract coefficient levels (TODO)")
    print("  5. ⚠️ Modify LSBs (TODO)")
    print("  6. ⚠️ Re-encode CAVLC/CABAC (TODO - very complex!)")
    print("\n  Estimated effort: 2-4 weeks for full implementation")


if __name__ == '__main__':
    main()
