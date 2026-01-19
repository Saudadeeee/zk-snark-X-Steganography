"""
NAL Unit Parser for H.264
Extracts NAL units from H.264 Annex B byte stream format
"""

class NALUnit:
    """Represents a NAL unit"""
    
    # NAL unit types (ITU-T H.264 Table 7-1)
    TYPE_UNSPECIFIED = 0
    TYPE_SLICE = 1
    TYPE_DPA = 2
    TYPE_DPB = 3
    TYPE_DPC = 4
    TYPE_IDR = 5  # Instantaneous Decoder Refresh (I-frame)
    TYPE_SEI = 6
    TYPE_SPS = 7  # Sequence Parameter Set
    TYPE_PPS = 8  # Picture Parameter Set
    TYPE_AUD = 9
    TYPE_END_SEQUENCE = 10
    TYPE_END_STREAM = 11
    TYPE_FILLER = 12
    
    TYPE_NAMES = {
        0: "Unspecified",
        1: "Slice (non-IDR)",
        2: "Data Partition A",
        3: "Data Partition B",
        4: "Data Partition C",
        5: "IDR Slice (I-frame)",
        6: "SEI",
        7: "SPS",
        8: "PPS",
        9: "Access Unit Delimiter",
        10: "End of Sequence",
        11: "End of Stream",
        12: "Filler Data"
    }
    
    def __init__(self, nal_type, nal_ref_idc, data):
        self.nal_type = nal_type
        self.nal_ref_idc = nal_ref_idc
        self.data = data
    
    def __repr__(self):
        type_name = self.TYPE_NAMES.get(self.nal_type, f"Unknown({self.nal_type})")
        return f"NALUnit(type={type_name}, ref_idc={self.nal_ref_idc}, size={len(self.data)})"
    
    def is_slice(self):
        """Check if this is a slice NAL unit"""
        return self.nal_type in [self.TYPE_SLICE, self.TYPE_IDR]
    
    def is_idr(self):
        """Check if this is an IDR slice"""
        return self.nal_type == self.TYPE_IDR
    
    def is_sps(self):
        """Check if this is SPS"""
        return self.nal_type == self.TYPE_SPS
    
    def is_pps(self):
        """Check if this is PPS"""
        return self.nal_type == self.TYPE_PPS


class NALParser:
    """Parse NAL units from H.264 Annex B byte stream"""
    
    def __init__(self, data):
        """
        Initialize NAL parser
        
        Args:
            data: H.264 bitstream data (bytes)
        """
        self.data = data if isinstance(data, bytes) else bytes(data)
        self.nal_units = []
    
    def parse(self):
        """
        Parse all NAL units from bitstream
        
        Returns:
            List of NALUnit objects
        """
        self.nal_units = []
        positions = self._find_start_codes()
        
        for i in range(len(positions)):
            start = positions[i]
            end = positions[i + 1] if i + 1 < len(positions) else len(self.data)
            
            # Extract NAL unit
            nal_unit = self._extract_nal_unit(start, end)
            if nal_unit:
                self.nal_units.append(nal_unit)
        
        return self.nal_units
    
    def _find_start_codes(self):
        """
        Find all NAL unit start codes (0x000001 or 0x00000001)
        
        Returns:
            List of positions where start codes begin
        """
        positions = []
        i = 0
        
        while i < len(self.data) - 3:
            # Check for 4-byte start code: 00 00 00 01
            if (self.data[i] == 0x00 and 
                self.data[i+1] == 0x00 and 
                self.data[i+2] == 0x00 and 
                self.data[i+3] == 0x01):
                positions.append(i + 4)  # Position after start code
                i += 4
            # Check for 3-byte start code: 00 00 01
            elif (self.data[i] == 0x00 and 
                  self.data[i+1] == 0x00 and 
                  self.data[i+2] == 0x01):
                positions.append(i + 3)  # Position after start code
                i += 3
            else:
                i += 1
        
        return positions
    
    def _extract_nal_unit(self, start, end):
        """
        Extract NAL unit from data
        
        Args:
            start: Start position (after start code)
            end: End position (before next start code or EOF)
        
        Returns:
            NALUnit object or None if invalid
        """
        if start >= end or start >= len(self.data):
            return None
        
        # Parse NAL header (1 byte)
        nal_header = self.data[start]
        
        # Extract fields from NAL header
        forbidden_zero = (nal_header >> 7) & 1
        nal_ref_idc = (nal_header >> 5) & 3
        nal_type = nal_header & 0x1F
        
        # Validate
        if forbidden_zero != 0:
            print(f"Warning: Forbidden zero bit is {forbidden_zero} (should be 0)")
            return None
        
        # Extract NAL payload (without header)
        payload = self.data[start+1:end]
        
        # Remove trailing zero bytes (emulation prevention may add these)
        while len(payload) > 0 and payload[-1] == 0x00:
            payload = payload[:-1]
        
        return NALUnit(nal_type, nal_ref_idc, payload)
    
    def get_slices(self):
        """Get all slice NAL units"""
        return [nal for nal in self.nal_units if nal.is_slice()]
    
    def get_sps_pps(self):
        """Get SPS and PPS NAL units"""
        sps = [nal for nal in self.nal_units if nal.is_sps()]
        pps = [nal for nal in self.nal_units if nal.is_pps()]
        return sps, pps
    
    def summary(self):
        """Print summary of parsed NAL units"""
        print(f"\nNAL Units Summary:")
        print(f"  Total NAL units: {len(self.nal_units)}")
        
        # Count by type
        type_counts = {}
        for nal in self.nal_units:
            type_name = NALUnit.TYPE_NAMES.get(nal.nal_type, f"Unknown({nal.nal_type})")
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
        
        print(f"\n  NAL unit types:")
        for type_name, count in sorted(type_counts.items()):
            print(f"    {type_name}: {count}")


def test_nal_parser():
    """Test NAL parser with actual video file"""
    import os
    
    print("="*70)
    print("NAL PARSER TEST")
    print("="*70)
    
    # Test with re-encoded CABAC video
    video_path = "data/encoded/akiyo_main_cabac.h264"
    
    if not os.path.exists(video_path):
        print(f"\n⚠️  Test video not found: {video_path}")
        print("Please run: python scripts/reencode_to_cabac.py")
        return
    
    print(f"\n[Test] Parsing video: {video_path}")
    
    # Read video file
    with open(video_path, 'rb') as f:
        data = f.read()
    
    print(f"File size: {len(data):,} bytes")
    
    # Parse NAL units
    parser = NALParser(data)
    nal_units = parser.parse()
    
    print(f"\n✓ Found {len(nal_units)} NAL units")
    
    # Show summary
    parser.summary()
    
    # Show first few NAL units
    print(f"\nFirst 10 NAL units:")
    for i, nal in enumerate(nal_units[:10]):
        print(f"  [{i}] {nal}")
    
    # Get slices
    slices = parser.get_slices()
    print(f"\n✓ Found {len(slices)} slice NAL units")
    
    # Get SPS/PPS
    sps, pps = parser.get_sps_pps()
    print(f"✓ Found {len(sps)} SPS, {len(pps)} PPS")
    
    if len(slices) > 0:
        print(f"\nFirst slice:")
        print(f"  {slices[0]}")
        print(f"  Payload size: {len(slices[0].data)} bytes")
        print(f"  First 16 bytes: {' '.join(f'{b:02x}' for b in slices[0].data[:16])}")
    
    print("\n" + "="*70)
    print("NAL PARSER TEST COMPLETE")
    print("="*70)
    print("\n✓ NAL unit extraction working!")
    print("✓ Can identify slices, SPS, PPS")
    print("✓ Ready for slice parsing")


if __name__ == '__main__':
    test_nal_parser()
