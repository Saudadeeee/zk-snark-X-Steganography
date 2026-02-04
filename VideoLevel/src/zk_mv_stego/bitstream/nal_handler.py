"""
NAL Unit and Slice Header Handling
==================================

Unified module for parsing NAL units and Slice Headers.
Combines functionality from nal_parser.py and slice_header_parser.py.
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional, Tuple, Dict
from .bitstream_io import BitstreamReader

class NALUnitType(IntEnum):
    """NAL unit types (H.264 Table 7-1)"""
    UNSPECIFIED = 0
    SLICE_NON_IDR = 1
    SLICE_PARTITION_A = 2
    SLICE_PARTITION_B = 3
    SLICE_PARTITION_C = 4
    SLICE_IDR = 5
    SEI = 6
    SPS = 7  # Sequence Parameter Set
    PPS = 8  # Picture Parameter Set
    AUD = 9  # Access Unit Delimiter
    END_OF_SEQUENCE = 10
    END_OF_STREAM = 11
    FILLER = 12
    SUBSET_SPS = 15
    PREFIX_NAL = 20
    UNKNOWN = 99

    @property
    def name_str(self) -> str:
        """Get human readable name"""
        names = {
            0: "Unspecified",
            1: "Slice (non-IDR)",
            5: "IDR Slice (I-frame)",
            6: "SEI",
            7: "SPS",
            8: "PPS",
            9: "Access Unit Delimiter"
        }
        return names.get(self.value, self.name)

@dataclass
class NALUnit:
    """Represents a NAL unit"""
    forbidden_zero_bit: int
    nal_ref_idc: int
    nal_unit_type: NALUnitType
    rbsp_byte: bytes  # Raw Byte Sequence Payload
    start_pos: int  # Position in file
    size: int
    
    def __repr__(self):
        type_name = self.nal_unit_type.name_str if isinstance(self.nal_unit_type, NALUnitType) else str(self.nal_unit_type)
        return f"NALUnit(type={type_name}, ref={self.nal_ref_idc}, size={self.size})"

    def is_slice(self) -> bool:
        """Check if this is a slice NAL unit"""
        return self.nal_unit_type in [NALUnitType.SLICE_NON_IDR, NALUnitType.SLICE_IDR]
    
    def is_idr(self) -> bool:
        """Check if this is an IDR slice"""
        return self.nal_unit_type == NALUnitType.SLICE_IDR

class NALParser:
    """Parse NAL units from H.264 Annex B byte stream"""
    
    def __init__(self, data: bytes):
        self.data = data if isinstance(data, bytes) else bytes(data)
        self.nal_units: List[NALUnit] = []
    
    def parse(self) -> List[NALUnit]:
        """Parse all NAL units from bitstream"""
        self.nal_units = []
        positions = self._find_start_codes()
        
        for i in range(len(positions)):
            start = positions[i]
            end = positions[i + 1] if i + 1 < len(positions) else len(self.data)
            
            # Extract NAL unit
            nal = self._extract_nal_unit(start, end)
            if nal:
                self.nal_units.append(nal)
        
        return self.nal_units
        
    def _find_start_codes(self) -> List[int]:
        """Find all NAL unit start codes"""
        positions = []
        i = 0
        while i < len(self.data) - 3:
            if self.data[i:i+3] == b'\x00\x00\x01':
                positions.append(i + 3)
                i += 3
            elif self.data[i:i+4] == b'\x00\x00\x00\x01':
                positions.append(i + 4)
                i += 4
            else:
                i += 1
        return positions

    def _extract_nal_unit(self, start: int, end: int) -> Optional[NALUnit]:
        """Extract NAL unit from data range"""
        if start >= end or start >= len(self.data):
            return None
            
        nal_header = self.data[start]
        forbidden = (nal_header >> 7) & 1
        ref_idc = (nal_header >> 5) & 3
        unit_type = nal_header & 0x1F
        
        try:
            nal_type = NALUnitType(unit_type)
        except ValueError:
            nal_type = NALUnitType.UNKNOWN
            
        payload = self.data[start+1:end]
        
        # Remove emulation prevention bytes
        clean_payload = self._remove_emulation_prevention(payload)
        
        return NALUnit(
            forbidden_zero_bit=forbidden,
            nal_ref_idc=ref_idc,
            nal_unit_type=nal_type,
            rbsp_byte=clean_payload,
            start_pos=start - (3 if start > 2 and self.data[start-3:start] == b'\x00\x00\x01' else 4),
            size=end-start+1 # Approx size including header
        )

    def _remove_emulation_prevention(self, data: bytes) -> bytes:
        result = bytearray()
        i = 0
        while i < len(data):
            if i + 2 < len(data) and data[i:i+2] == b'\x00\x00' and data[i+2] == 0x03:
                result.extend(data[i:i+2])
                i += 3
            else:
                result.append(data[i])
                i += 1
        return bytes(result)

@dataclass
class SPSData:
    """Minimal SPS data needed for slice header parsing"""
    log2_max_frame_num_minus4: int = 0
    pic_order_cnt_type: int = 0
    log2_max_pic_order_cnt_lsb_minus4: int = 0
    frame_mbs_only_flag: bool = True
    pic_width_in_mbs_minus1: int = 0
    pic_height_in_map_units_minus1: int = 0
    
    @property
    def max_frame_num(self) -> int:
        return 1 << (self.log2_max_frame_num_minus4 + 4)
    
    @property
    def max_pic_order_cnt_lsb(self) -> int:
        return 1 << (self.log2_max_pic_order_cnt_lsb_minus4 + 4)

@dataclass
class PPSData:
    """Minimal PPS data needed for slice header parsing"""
    pic_init_qp_minus26: int = 0
    deblocking_filter_control_present_flag: bool = True
    redundant_pic_cnt_present_flag: bool = False
    num_ref_idx_l0_default_active_minus1: int = 0
    num_ref_idx_l1_default_active_minus1: int = 0

@dataclass
class SliceHeader:
    """Complete slice header data"""
    first_mb_in_slice: int
    slice_type: int
    pic_parameter_set_id: int
    frame_num: int
    field_pic_flag: bool = False
    bottom_field_flag: bool = False
    idr_pic_id: Optional[int] = None
    pic_order_cnt_lsb: int = 0
    delta_pic_order_cnt_bottom: int = 0
    delta_pic_order_cnt: Tuple[int, int] = (0, 0)
    redundant_pic_cnt: int = 0
    direct_spatial_mv_pred_flag: bool = False
    num_ref_idx_active_override_flag: bool = False
    num_ref_idx_l0_active_minus1: int = 0
    num_ref_idx_l1_active_minus1: int = 0
    slice_qp_delta: int = 0
    disable_deblocking_filter_idc: int = 0
    slice_alpha_c0_offset_div2: int = 0
    slice_beta_offset_div2: int = 0
    
    def __post_init__(self):
        # Convert slice_type > 4 to 0-4
        if self.slice_type > 4:
            self.slice_type -= 5

class SliceHeaderParser:
    """Parse H.264 slice header"""
    
    def __init__(self, reader: BitstreamReader, nal_unit: NALUnit,
                 sps: Optional[SPSData] = None, pps: Optional[PPSData] = None):
        self.reader = reader
        self.nal_unit = nal_unit
        self.sps = sps or SPSData()
        self.pps = pps or PPSData()
        
    def parse(self) -> SliceHeader:
        # Basic parsing skipping advanced features for now
        first_mb = self.reader.read_ue()
        slice_type = self.reader.read_ue()
        pps_id = self.reader.read_ue()
        frame_num = self.reader.read_bits(self.sps.log2_max_frame_num_minus4 + 4)
        
        idr_pic_id = None
        if self.nal_unit == NALUnitType.SLICE_IDR:
            idr_pic_id = self.reader.read_ue()
            
        return SliceHeader(
            first_mb_in_slice=first_mb,
            slice_type=slice_type,
            pic_parameter_set_id=pps_id,
            frame_num=frame_num,
            idr_pic_id=idr_pic_id
        )
