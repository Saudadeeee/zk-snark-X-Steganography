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
    start_code_size: int = 4  # Start code length in bytes (3 or 4)
    
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
            start, sc_size = positions[i]
            end = positions[i + 1][0] if i + 1 < len(positions) else len(self.data)

            # Extract NAL unit
            nal = self._extract_nal_unit(start, end, sc_size)
            if nal:
                self.nal_units.append(nal)

        return self.nal_units

    def _find_start_codes(self) -> List[Tuple[int, int]]:
        """Find all NAL unit start codes. Returns list of (position_after_sc, sc_size)."""
        positions = []
        i = 0
        while i < len(self.data) - 3:
            if self.data[i:i+4] == b'\x00\x00\x00\x01':
                positions.append((i + 4, 4))
                i += 4
            elif self.data[i:i+3] == b'\x00\x00\x01':
                positions.append((i + 3, 3))
                i += 3
            else:
                i += 1
        return positions

    def _extract_nal_unit(self, start: int, end: int, sc_size: int = 4) -> Optional[NALUnit]:
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
            start_pos=start - sc_size,
            size=end - start + 1,
            start_code_size=sc_size,
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
    entropy_coding_mode_flag: bool = False  # False = CAVLC, True = CABAC
    num_slice_groups_minus1: int = 0  # For FMO support check

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
    ref_pic_list_modification_flag_l0: bool = False
    ref_pic_list_modification_flag_l1: bool = False
    ref_pic_list_modification_l0_data: list = None  # List of bits
    ref_pic_list_modification_l1_data: list = None  # List of bits
    no_output_of_prior_pics_flag: bool = False
    long_term_reference_flag: bool = False
    adaptive_ref_pic_marking_mode_flag: bool = False
    dec_ref_pic_marking_data: list = None  # List of bits for MMCO commands
    slice_qp_delta: int = 0
    disable_deblocking_filter_idc: int = 0
    slice_alpha_c0_offset_div2: int = 0
    slice_beta_offset_div2: int = 0
    
    def __post_init__(self):
        # Convert slice_type > 4 to 0-4
        if self.slice_type > 4:
            self.slice_type -= 5
        # Initialize None lists to empty lists
        if self.ref_pic_list_modification_l0_data is None:
            self.ref_pic_list_modification_l0_data = []
        if self.ref_pic_list_modification_l1_data is None:
            self.ref_pic_list_modification_l1_data = []
        if self.dec_ref_pic_marking_data is None:
            self.dec_ref_pic_marking_data = []

class SliceHeaderParser:
    """Parse H.264 slice header"""
    
    def __init__(self, reader: BitstreamReader, nal_unit: NALUnit,
                 sps: Optional[SPSData] = None, pps: Optional[PPSData] = None):
        self.reader = reader
        self.nal_unit = nal_unit
        self.sps = sps or SPSData()
        self.pps = pps or PPSData()
        
    def parse(self) -> SliceHeader:
        # Parse slice header fields according to H.264 spec 7.3.3
        # CRITICAL: Must parse EVERY field in exact order to maintain bitstream alignment!
        pos_start = self.reader.position
        debug_first_slice = False  # Enable for debugging
        
        # Step 1: Basic fields (always present)
        first_mb = self.reader.read_ue()
        slice_type = self.reader.read_ue()
        pps_id = self.reader.read_ue()
        
        if debug_first_slice:
            pos_after_basic = self.reader.position
            print(f"  [SLICE_HDR] first_mb={first_mb}, slice_type={slice_type}, pps={pps_id}, Pos={pos_after_basic}")
        
        # Step 2: frame_num (always present)
        frame_num = self.reader.read_bits(self.sps.log2_max_frame_num_minus4 + 4)
        
        if debug_first_slice:
            pos_after_frame_num = self.reader.position
            print(f"  [SLICE_HDR] frame_num={frame_num}, Pos={pos_after_frame_num}")
        
        # Step 3: field_pic_flag and bottom_field_flag (conditional on frame_mbs_only_flag)
        field_pic_flag = 0
        bottom_field_flag = 0
        if not self.sps.frame_mbs_only_flag:
            field_pic_flag = self.reader.read_bits(1)
            if field_pic_flag:
                bottom_field_flag = self.reader.read_bits(1)
            if debug_first_slice:
                print(f"  [SLICE_HDR] field_pic={field_pic_flag}, bottom_field={bottom_field_flag}, Pos={self.reader.position}")
        
        # Step 4: idr_pic_id (conditional on NAL unit type)
        idr_pic_id = None
        if self.nal_unit.is_idr():
            idr_pic_id = self.reader.read_ue()
            if debug_first_slice:
                pos_after_idr = self.reader.position
                print(f"  [SLICE_HDR] idr_pic_id={idr_pic_id}, Pos={pos_after_idr}")
        
        # Parse picture order count fields based on SPS settings
        # H.264 spec 7.3.3: MANDATORY for proper bitstream alignment!
        if debug_first_slice:
            print(f"  [DEC_SLICE] pic_order_cnt_type={self.sps.pic_order_cnt_type}")
        if self.sps.pic_order_cnt_type == 0:
            # pic_order_cnt_lsb: u(v) bits where v = log2_max_pic_order_cnt_lsb_minus4 + 4
            num_bits = self.sps.log2_max_pic_order_cnt_lsb_minus4 + 4
            pic_order_cnt_lsb = self.reader.read_bits(num_bits)
            if debug_first_slice:
                pos_after_poc = self.reader.position
                print(f"  [DEC_SLICE] After pic_order_cnt_lsb ({num_bits} bits): Pos:{pos_after_poc}")
        elif self.sps.pic_order_cnt_type == 1:
            # delta_pic_order_cnt[0] and [1] for type 1
            # Not implementing for now, but would be needed for complete parsing
            if debug_first_slice:
                print(f"  [DEC_SLICE] WARNING: pic_order_cnt_type=1 not fully implemented!")
            pass
        # pic_order_cnt_type == 2: no additional fields
        
        # CRITICAL FIX: Parse num_ref_idx_active_override - H.264 spec 7.3.3
        # This is MANDATORY for P and B slices!
        num_ref_idx_active_override_flag = False
        num_ref_idx_l0_active_minus1 = 0
        num_ref_idx_l1_active_minus1 = 0
        if slice_type % 5 in [0, 1]:  # P or B slice
            num_ref_idx_active_override_flag = self.reader.read_bits(1)
            if debug_first_slice:
                print(f"  [DEC_SLICE] num_ref_idx_active_override_flag={num_ref_idx_active_override_flag}, Pos:{self.reader.position}")
            if num_ref_idx_active_override_flag:
                num_ref_idx_l0_active_minus1 = self.reader.read_ue()
                if debug_first_slice:
                    print(f"  [DEC_SLICE] After num_ref_idx_l0_active_minus1={num_ref_idx_l0_active_minus1}: Pos:{self.reader.position}")
                if slice_type % 5 == 1:  # B slice
                    num_ref_idx_l1_active_minus1 = self.reader.read_ue()
                    if debug_first_slice:
                        print(f"  [DEC_SLICE] After num_ref_idx_l1_active_minus1={num_ref_idx_l1_active_minus1}: Pos:{self.reader.position}")
            if debug_first_slice:
                pos_after_num_ref = self.reader.position
                print(f"  [DEC_SLICE] After num_ref_idx block: Pos:{pos_after_num_ref}")
        
        # CRITICAL FIX: Parse ref_pic_list_modification() - H.264 spec 7.3.3.1
        # This is MANDATORY for P and B slices!
        ref_pic_list_modification_flag_l0 = False
        ref_pic_list_modification_flag_l1 = False
        ref_pic_list_modification_l0_bits = []  # Store as list of bits, not bytes
        ref_pic_list_modification_l1_bits = []
        
        if slice_type % 5 != 2:  # Not I-slice (P or B slice)
            # ref_pic_list_modification_flag_l0
            pos_before_ref_mod = self.reader.position
            ref_pic_list_modification_flag_l0 = self.reader.read_bits(1)
            if debug_first_slice:
                print(f"  [DEC_SLICE] ref_pic_list_modification_flag_l0={ref_pic_list_modification_flag_l0}, Pos:{self.reader.position}")
            if ref_pic_list_modification_flag_l0:
                # Parse modification_of_pic_nums_idc commands
                while True:
                    modification_of_pic_nums_idc = self.reader.read_ue()
                    if modification_of_pic_nums_idc == 3:
                        break
                    if modification_of_pic_nums_idc in [0, 1]:
                        abs_diff_pic_num_minus1 = self.reader.read_ue()
                    elif modification_of_pic_nums_idc == 2:
                        long_term_pic_num = self.reader.read_ue()
                if debug_first_slice:
                    print(f"  [DEC_SLICE] After ref_pic_list_modification commands: Pos:{self.reader.position}")
            # Capture exact bit sequence
            pos_after_ref_mod_l0 = self.reader.position
            num_bits_l0 = pos_after_ref_mod_l0 - pos_before_ref_mod
            # Extract bits from reader's data
            for bit_offset in range(num_bits_l0):
                byte_pos = (pos_before_ref_mod + bit_offset) // 8
                bit_pos = 7 - ((pos_before_ref_mod + bit_offset) % 8)
                bit_val = (self.reader.data[byte_pos] >> bit_pos) & 1
                ref_pic_list_modification_l0_bits.append(bit_val)
            
            if slice_type % 5 == 1:  # B slice
                pos_before_ref_mod_l1 = self.reader.position
                ref_pic_list_modification_flag_l1 = self.reader.read_bits(1)
                if ref_pic_list_modification_flag_l1:
                    while True:
                        modification_of_pic_nums_idc = self.reader.read_ue()
                        if modification_of_pic_nums_idc == 3:
                            break
                        if modification_of_pic_nums_idc in [0, 1]:
                            abs_diff_pic_num_minus1 = self.reader.read_ue()
                        elif modification_of_pic_nums_idc == 2:
                            long_term_pic_num = self.reader.read_ue()
                pos_after_ref_mod_l1 = self.reader.position
                num_bits_l1 = pos_after_ref_mod_l1 - pos_before_ref_mod_l1
                for bit_offset in range(num_bits_l1):
                    byte_pos = (pos_before_ref_mod_l1 + bit_offset) // 8
                    bit_pos = 7 - ((pos_before_ref_mod_l1 + bit_offset) % 8)
                    bit_val = (self.reader.data[byte_pos] >> bit_pos) & 1
                    ref_pic_list_modification_l1_bits.append(bit_val)
        
        # CRITICAL FIX: Parse dec_ref_pic_marking() - H.264 spec 7.3.3.3
        # This is MANDATORY for IDR and P/B slices to maintain bitstream alignment!
        no_output_of_prior_pics_flag = False
        long_term_reference_flag = False
        adaptive_ref_pic_marking_mode_flag = False
        dec_ref_pic_marking_bits = []  # Store as list of bits
        
        pos_before_dec_ref = self.reader.position
        if self.nal_unit.is_idr():
            # IDR frames have 2 flags for reference picture marking
            no_output_of_prior_pics_flag = self.reader.read_bits(1)
            long_term_reference_flag = self.reader.read_bits(1)
            if debug_first_slice:
                pos_after_dec_ref = self.reader.position
                print(f"  [DEC_SLICE] After dec_ref_pic_marking (2 bits): Pos:{pos_after_dec_ref}")
        elif slice_type % 5 in [0, 1]:  # P or B slice
            # Non-IDR reference frames have adaptive marking flag
            adaptive_ref_pic_marking_mode_flag = self.reader.read_bits(1)
            if debug_first_slice:
                print(f"  [DEC_SLICE] adaptive_ref_pic_marking_mode_flag={adaptive_ref_pic_marking_mode_flag}, Pos:{self.reader.position}")
            if adaptive_ref_pic_marking_mode_flag:
                # Parse MMCO commands
                while True:
                    memory_management_control_operation = self.reader.read_ue()
                    if memory_management_control_operation == 0:
                        break
                    if memory_management_control_operation in [1, 3]:
                        difference_of_pic_nums_minus1 = self.reader.read_ue()
                    if memory_management_control_operation == 2:
                        long_term_pic_num = self.reader.read_ue()
                    if memory_management_control_operation in [3, 6]:
                        long_term_frame_idx = self.reader.read_ue()
                    if memory_management_control_operation == 4:
                        max_long_term_frame_idx_plus1 = self.reader.read_ue()
                if debug_first_slice:
                    print(f"  [DEC_SLICE] After dec_ref_pic_marking MMCO commands: Pos:{self.reader.position}")
        # Capture exact bit sequence
        pos_after_dec_ref = self.reader.position
        num_bits_dec_ref = pos_after_dec_ref - pos_before_dec_ref
        for bit_offset in range(num_bits_dec_ref):
            byte_pos = (pos_before_dec_ref + bit_offset) // 8
            bit_pos = 7 - ((pos_before_dec_ref + bit_offset) % 8)
            bit_val = (self.reader.data[byte_pos] >> bit_pos) & 1
            dec_ref_pic_marking_bits.append(bit_val)
        
        # Parse slice_qp_delta - H.264 spec 7.3.3: MANDATORY!
        # This MUST be parsed to properly align bitstream before slice data
        slice_qp_delta = self.reader.read_se()
        
        if debug_first_slice:
            pos_after_qp = self.reader.position
            print(f"  [DEC_SLICE] After slice_qp_delta: Pos:{pos_after_qp}")
        
        # CRITICAL FIX: Parse deblocking_filter_control - H.264 spec 7.3.3
        # This is MANDATORY if PPS flag is set!
        # Initialize default values
        disable_deblocking_filter_idc = 0
        slice_alpha_c0_offset_div2 = 0
        slice_beta_offset_div2 = 0
        
        if self.pps.deblocking_filter_control_present_flag:
            disable_deblocking_filter_idc = self.reader.read_ue()
            if disable_deblocking_filter_idc != 1:
                slice_alpha_c0_offset_div2 = self.reader.read_se()
                slice_beta_offset_div2 = self.reader.read_se()
            if debug_first_slice:
                pos_after_deblock = self.reader.position
                print(f"  [DEC_SLICE] After deblocking_filter_control: Pos:{pos_after_deblock}")
        
        # CRITICAL FIX: Parse redundant_pic_cnt - H.264 spec 7.3.3
        # This is MANDATORY if PPS has redundant_pic_cnt_present_flag set!
        redundant_pic_cnt = 0
        if self.pps.redundant_pic_cnt_present_flag:
            redundant_pic_cnt = self.reader.read_ue()
            if debug_first_slice:
                pos_after_redundant = self.reader.position
                print(f"  [DEC_SLICE] After redundant_pic_cnt={redundant_pic_cnt}: Pos:{pos_after_redundant}")
            
        if debug_first_slice:
            pos_final = self.reader.position
            print(f"  [DEC_SLICE] TOTAL slice header consumed: {pos_final - pos_start} bits (ENCODER writes 30 bits!)")
            
        return SliceHeader(
            first_mb_in_slice=first_mb,
            slice_type=slice_type,
            pic_parameter_set_id=pps_id,
            frame_num=frame_num,
            idr_pic_id=idr_pic_id,
            num_ref_idx_active_override_flag=num_ref_idx_active_override_flag,
            num_ref_idx_l0_active_minus1=num_ref_idx_l0_active_minus1,
            num_ref_idx_l1_active_minus1=num_ref_idx_l1_active_minus1,
            ref_pic_list_modification_flag_l0=ref_pic_list_modification_flag_l0,
            ref_pic_list_modification_flag_l1=ref_pic_list_modification_flag_l1,
            ref_pic_list_modification_l0_data=ref_pic_list_modification_l0_bits,
            ref_pic_list_modification_l1_data=ref_pic_list_modification_l1_bits,
            no_output_of_prior_pics_flag=no_output_of_prior_pics_flag,
            long_term_reference_flag=long_term_reference_flag,
            adaptive_ref_pic_marking_mode_flag=adaptive_ref_pic_marking_mode_flag,
            dec_ref_pic_marking_data=dec_ref_pic_marking_bits,
            slice_qp_delta=slice_qp_delta,
            disable_deblocking_filter_idc=disable_deblocking_filter_idc,
            slice_alpha_c0_offset_div2=slice_alpha_c0_offset_div2,
            slice_beta_offset_div2=slice_beta_offset_div2
        )
