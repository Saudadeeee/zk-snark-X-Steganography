"""
H.264 NAL/Slice Parsing, Macroblock Parser, and Traceable CAVLC Parser
=======================================================================

Merged module combining:
  - NAL unit types, parsing (NALUnitType, NALUnit, NALParser, H264BitstreamParser)
  - Slice header parsing (SliceHeader, SliceHeaderParser, SPSData, PPSData)
  - Macroblock layer parsing (MacroblockParser, MBType)
  - Traceable CAVLC parser with bit-offset tracking (TraceableCAVLCParser)

References:
  - ITU-T H.264 Sections 7, 8, 9
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
        # Step 1: Basic fields (always present)
        first_mb = self.reader.read_ue()
        slice_type = self.reader.read_ue()
        pps_id = self.reader.read_ue()

        # Step 2: frame_num (always present)
        frame_num = self.reader.read_bits(self.sps.log2_max_frame_num_minus4 + 4)

        # Step 3: field_pic_flag and bottom_field_flag (conditional on frame_mbs_only_flag)
        field_pic_flag = 0
        bottom_field_flag = 0
        if not self.sps.frame_mbs_only_flag:
            field_pic_flag = self.reader.read_bits(1)
            if field_pic_flag:
                bottom_field_flag = self.reader.read_bits(1)

        # Step 4: idr_pic_id (conditional on NAL unit type)
        idr_pic_id = None
        if self.nal_unit.is_idr():
            idr_pic_id = self.reader.read_ue()
        
        # Parse picture order count fields based on SPS settings
        # H.264 spec 7.3.3: MANDATORY for proper bitstream alignment!
        if self.sps.pic_order_cnt_type == 0:
            # pic_order_cnt_lsb: u(v) bits where v = log2_max_pic_order_cnt_lsb_minus4 + 4
            num_bits = self.sps.log2_max_pic_order_cnt_lsb_minus4 + 4
            pic_order_cnt_lsb = self.reader.read_bits(num_bits)
        elif self.sps.pic_order_cnt_type == 1:
            # delta_pic_order_cnt[0] and [1] for type 1
            # Not implementing for now, but would be needed for complete parsing
            pass
        # pic_order_cnt_type == 2: no additional fields

        # CRITICAL FIX: Parse num_ref_idx_active_override - H.264 spec 7.3.3
        # This is MANDATORY for P and B slices!
        num_ref_idx_active_override_flag = False
        num_ref_idx_l0_active_minus1 = 0
        num_ref_idx_l1_active_minus1 = 0
        if slice_type % 5 in [0, 1]:  # P or B slice
            num_ref_idx_active_override_flag = self.reader.read_bits(1)
            if num_ref_idx_active_override_flag:
                num_ref_idx_l0_active_minus1 = self.reader.read_ue()
                if slice_type % 5 == 1:  # B slice
                    num_ref_idx_l1_active_minus1 = self.reader.read_ue()

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
        elif slice_type % 5 in [0, 1]:  # P or B slice
            # Non-IDR reference frames have adaptive marking flag
            adaptive_ref_pic_marking_mode_flag = self.reader.read_bits(1)
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

        # CRITICAL FIX: Parse redundant_pic_cnt - H.264 spec 7.3.3
        # This is MANDATORY if PPS has redundant_pic_cnt_present_flag set!
        redundant_pic_cnt = 0
        if self.pps.redundant_pic_cnt_present_flag:
            redundant_pic_cnt = self.reader.read_ue()

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


class H264BitstreamParser:
    """
    File-based H.264 NAL unit parser.

    Thin wrapper around NALParser that accepts a video file path.
    Formerly in h264_parser.py (merged here to eliminate duplication).
    """

    def __init__(self, video_path: str):
        self.video_path = video_path
        self.nal_units: List[NALUnit] = []

    def parse(self) -> List[NALUnit]:
        """Parse entire bitstream and return NAL units."""
        with open(self.video_path, 'rb') as f:
            data = f.read()
        parser = NALParser(data)
        self.nal_units = parser.parse()
        return self.nal_units



# =============================================================================
# MACROBLOCK PARSER  (formerly macroblock_parser.py)
# =============================================================================




class MBType(IntEnum):
    """Macroblock types for I and P slices"""
    # I slice types (Table 7-11)
    I_4x4 = 0
    I_16x16_0_0_0 = 1  # pred_mode=0, CBP_chroma=0, CBP_luma=0
    I_16x16_1_0_0 = 2
    I_16x16_2_0_0 = 3
    I_16x16_3_0_0 = 4
    I_16x16_0_1_0 = 5
    I_16x16_1_1_0 = 6
    I_16x16_2_1_0 = 7
    I_16x16_3_1_0 = 8
    I_16x16_0_2_0 = 9
    I_16x16_1_2_0 = 10
    I_16x16_2_2_0 = 11
    I_16x16_3_2_0 = 12
    I_16x16_0_0_1 = 13
    I_16x16_1_0_1 = 14
    I_16x16_2_0_1 = 15
    I_16x16_3_0_1 = 16
    I_16x16_0_1_1 = 17
    I_16x16_1_1_1 = 18
    I_16x16_2_1_1 = 19
    I_16x16_3_1_1 = 20
    I_16x16_0_2_1 = 21
    I_16x16_1_2_1 = 22
    I_16x16_2_2_1 = 23
    I_16x16_3_2_1 = 24
    I_PCM = 25
    
    # P slice types (simplified - Baseline profile)
    P_L0_16x16 = 100
    P_L0_L0_16x8 = 101
    P_L0_L0_8x16 = 102
    P_8x8 = 103
    P_8x8ref0 = 104
    P_SKIP = 105


@dataclass
class MacroblockData:
    """Parsed macroblock information"""
    mb_type: int
    mb_type_enum: Optional[MBType]
    
    # Transform info
    transform_size_8x8_flag: bool = False
    
    # Coded Block Pattern
    coded_block_pattern: int = 0  # 6 bits: [luma(4 bits)][chroma_dc][chroma_ac]
    
    # QP
    mb_qp_delta: int = 0
    
    # Prediction modes (for I_4x4)
    intra_4x4_pred_mode: List[int] = None
    intra_chroma_pred_mode: int = 0  # For I slices
    
    # Residual info
    luma_4x4_blocks: List[bool] = None  # Which 4x4 blocks have residual
    chroma_dc_present: bool = False
    chroma_ac_present: bool = False
    
    def __post_init__(self):
        if self.intra_4x4_pred_mode is None:
            self.intra_4x4_pred_mode = []
        if self.luma_4x4_blocks is None:
            self.luma_4x4_blocks = [False] * 16


class MacroblockParser:
    """
    Parse macroblock layer from H.264 slice data
    """

    def __init__(self, reader: BitstreamReader, slice_type: int,
                 num_ref_idx_l0_active_minus1: int = 0):
        self.reader = reader
        self.slice_type = slice_type
        self.is_i_slice = slice_type in [2, 7]  # I or IDR
        self.is_p_slice = slice_type in [0, 5]  # P slice
        self.num_ref_idx_l0_active_minus1 = num_ref_idx_l0_active_minus1

        # Current QP (starts from PPS QP, updated by mb_qp_delta)
        self.current_qp = 26  # Default, should be from PPS

        # Track whether the MB currently being parsed is intra type
        # (used for CBP mapping selection for I-MBs within P-slices)
        self._current_is_intra = True
    
    def parse_macroblock(self) -> MacroblockData:
        """
        Parse one macroblock from bitstream
        
        Returns:
            MacroblockData with all parsed information
        """
        mb = MacroblockData(mb_type=0, mb_type_enum=None)

        pos_start = self.reader.position

        # 1. Read mb_type
        mb.mb_type = self._read_mb_type()
        mb.mb_type_enum = self._interpret_mb_type(mb.mb_type)

        # Detect bitstream desync: mb_type out of valid range
        if mb.mb_type_enum is None or (self.is_i_slice and mb.mb_type > 25):
            self.reader.pos = pos_start
            raise ValueError(f"mb_type_desync: mb_type={mb.mb_type} slice_type={self.slice_type}")

        # 2. Handle I_PCM special case
        if mb.mb_type_enum == MBType.I_PCM:
            self._parse_i_pcm(mb)
            return mb

        # Determine if this MB is an intra type (used for CBP mapping below)
        self._current_is_intra = self.is_i_slice or self._is_intra_type(mb.mb_type_enum)

        # 2b. For P-slices: read motion prediction data (ref_idx + MVDs) for P-type MBs
        # This MUST happen before reading CBP.
        # For I-type MBs inside a P-slice, skip this (they have no motion vectors).
        if self.is_p_slice and not self._is_intra_type(mb.mb_type_enum):
            self._parse_p_mb_prediction(mb)

        # 3. Parse prediction mode for I_4x4 (luma pred modes only)
        if mb.mb_type_enum == MBType.I_4x4:
            self._parse_intra_4x4_pred_mode(mb)  # Parse luma modes

        # PRIORITY 2 FIX: Parse chroma pred mode for ALL Intra MBs (I_4x4 AND I_16x16)
        # H.264 Spec: intra_chroma_pred_mode exists for both I_NxN and I_16x16!
        # Also applies to I-type MBs within P-slices (not just pure I-slices).
        if self._current_is_intra and mb.mb_type_enum != MBType.I_PCM:
            mb.intra_chroma_pred_mode = self.reader.read_ue()
            if mb.intra_chroma_pred_mode > 3:
                self.reader.pos = pos_start
                raise ValueError(f"chroma_pred_desync: intra_chroma_pred_mode={mb.intra_chroma_pred_mode}")

        # 4. Parse Coded Block Pattern (if not I_16x16)
        if not self._is_i16x16(mb.mb_type_enum):
            mb.coded_block_pattern = self._read_coded_block_pattern()
        else:
            # I_16x16: CBP is encoded in mb_type
            mb.coded_block_pattern = self._extract_cbp_from_i16x16(mb.mb_type_enum)
        
        # Validate CBP range for non-I_16x16 MBs (table values: 0-47)
        # I_16x16 MBs can have CBP up to 63 (bits[5:4] = 0b11 for DC+AC chroma)
        if not self._is_i16x16(mb.mb_type_enum):
            if mb.coded_block_pattern < 0 or mb.coded_block_pattern > 47:
                print(f"[WARN] Suspicious CBP={mb.coded_block_pattern} (valid: 0-47)")
                print(f"[FIX] Clamping CBP to valid range")
                mb.coded_block_pattern = min(max(mb.coded_block_pattern, 0), 47)
        
        # 5. Parse QP delta
        if mb.coded_block_pattern > 0 or self._is_i16x16(mb.mb_type_enum):
            mb.mb_qp_delta = self.reader.read_se()
            
            # CRITICAL FIX: Validate and clamp QP delta
            if mb.mb_qp_delta < -26 or mb.mb_qp_delta > 25:
                print(f"[WARN] Suspicious QP_delta={mb.mb_qp_delta} (valid: -26 to +25) - bitstream misalignment likely!")
                print(f"[FIX] Clamping QP_delta to valid range")
                mb.mb_qp_delta = min(max(mb.mb_qp_delta, -26), 25)  # Clamp to [-26, 25]
            
            self.current_qp = (self.current_qp + mb.mb_qp_delta + 52) % 52
        
        # 6. Determine which blocks have residual
        self._decode_cbp_to_blocks(mb)
        
        return mb
    
    def parse_macroblock_type_only(self) -> int:
        """
        Quick parse to just get mb_type for counting macroblocks
        Used for estimating MB count without full parsing
        """
        mb_type = self.reader.read_ue()
        return mb_type
    
    def _read_mb_type(self) -> int:
        """Read mb_type using Exp-Golomb (simplified)"""
        return self.reader.read_ue()
    
    def _interpret_mb_type(self, mb_type: int) -> Optional[MBType]:
        """Convert mb_type value to MBType enum with robust error handling"""
        if self.is_i_slice:
            if mb_type <= 25:
                return MBType(mb_type)
            else:
                return None  # Invalid mb_type — parse_macroblock() will raise desync
        elif self.is_p_slice:
            # P slice mapping (simplified)
            if mb_type == 0:
                return MBType.P_L0_16x16
            elif mb_type == 1:
                return MBType.P_L0_L0_16x8
            elif mb_type == 2:
                return MBType.P_L0_L0_8x16
            elif mb_type == 3:
                return MBType.P_8x8
            elif mb_type == 4:
                return MBType.P_8x8ref0
            # I types in P slice (offset by 5)
            elif mb_type >= 5 and mb_type <= 30:
                # Map to I-slice types: mb_type 5→0, 6→1, ..., 30→25
                i_type_val = mb_type - 5
                return MBType(i_type_val)
            else:
                return None  # Invalid mb_type — parse_macroblock() will raise desync
        else:
            # Unknown slice type
            print(f"[WARN] Unknown slice_type={self.slice_type}, mb_type={mb_type}")
            return MBType.I_4x4  # Safe fallback
    
    def _is_i16x16(self, mb_type: Optional[MBType]) -> bool:
        """Check if macroblock is I_16x16 type"""
        if mb_type is None:
            return False
        return MBType.I_16x16_0_0_0 <= mb_type <= MBType.I_16x16_3_2_1

    def _is_intra_type(self, mb_type: Optional[MBType]) -> bool:
        """Check if macroblock is any intra type (I_4x4 or I_16x16)"""
        if mb_type is None:
            return False
        return mb_type == MBType.I_4x4 or MBType.I_16x16_0_0_0 <= mb_type <= MBType.I_16x16_3_2_1

    def _parse_p_mb_prediction(self, mb: MacroblockData):
        """
        Read motion prediction syntax for P-type MBs in P-slices.

        H.264 Section 7.3.5.2: sub_mb_pred / mb_pred for P slices.
        Must be read BEFORE coded_block_pattern.

        Partitions:
          P_L0_16x16  (raw mb_type=0) : 1 partition
          P_L0_L0_16x8 (raw mb_type=1) : 2 partitions
          P_L0_L0_8x16 (raw mb_type=2) : 2 partitions
          P_8x8       (raw mb_type=3) : 4 sub-MBs (reads sub_mb_type first)
          P_8x8ref0   (raw mb_type=4) : 4 sub-MBs, all ref=0
        """
        raw_mb_type = mb.mb_type  # Original raw value in P-slice

        if raw_mb_type <= 2:
            # Simple 16x16 (1 partition) or 16x8/8x16 (2 partitions)
            num_partitions = 1 if raw_mb_type == 0 else 2
            for _ in range(num_partitions):
                # ref_idx_l0: te(v) — only written when max > 0 (i.e. >1 reference frame)
                if self.num_ref_idx_l0_active_minus1 > 0:
                    self.reader.read_ue()  # te(v) approximated as ue(v)
                # Motion vector difference (horizontal, then vertical)
                self.reader.read_se()   # mvd_l0 x
                self.reader.read_se()   # mvd_l0 y

        elif raw_mb_type == 3:  # P_8x8
            # Step 1: sub_mb_type for each of the 4 sub-MBs
            sub_mb_types = [self.reader.read_ue() for _ in range(4)]
            # Step 2: ref_idx for each sub-MB (if >1 reference)
            if self.num_ref_idx_l0_active_minus1 > 0:
                for _ in range(4):
                    self.reader.read_ue()  # ref_idx_l0[s]
            # Step 3: MVDs per sub-partition
            for smt in sub_mb_types:
                # Number of sub-partitions per sub-MB type:
                #   0 → P_L0_8x8  : 1 sub-partition
                #   1 → P_L0_8x4  : 2 sub-partitions
                #   2 → P_L0_4x8  : 2 sub-partitions
                #   3 → P_L0_4x4  : 4 sub-partitions
                num_subparts = 4 if smt == 3 else (2 if smt in (1, 2) else 1)
                for _ in range(num_subparts):
                    self.reader.read_se()  # mvd x
                    self.reader.read_se()  # mvd y

        elif raw_mb_type == 4:  # P_8x8ref0
            # Step 1: sub_mb_type for each of the 4 sub-MBs
            sub_mb_types = [self.reader.read_ue() for _ in range(4)]
            # No ref_idx (reference is always 0)
            # Step 2: MVDs per sub-partition
            for smt in sub_mb_types:
                num_subparts = 4 if smt == 3 else (2 if smt in (1, 2) else 1)
                for _ in range(num_subparts):
                    self.reader.read_se()  # mvd x
                    self.reader.read_se()  # mvd y
        # else: unknown P-type, skip gracefully (no motion data consumed)
    
    def _parse_i_pcm(self, mb: MacroblockData):
        """Parse I_PCM macroblock (raw pixel data)"""
        # Byte align
        while not self.reader.is_byte_aligned():
            self.reader.read_bits(1)
        
        # Read 256 luma samples (16x16)
        for _ in range(256):
            self.reader.read_bits(8)
        
        # Read 128 chroma samples (2 * 8x8 for 4:2:0)
        for _ in range(128):
            self.reader.read_bits(8)
    
    def _parse_intra_4x4_pred_mode(self, mb: MacroblockData):
        """Parse LUMA prediction modes for I_4x4 blocks (chroma mode moved to main flow)"""
        mb.intra_4x4_pred_mode = []
        
        for blk_idx in range(16):
            prev_intra4x4_pred_mode_flag = self.reader.read_bits(1)
            
            if prev_intra4x4_pred_mode_flag:
                # Use predicted mode
                mb.intra_4x4_pred_mode.append(-1)  # Predicted
            else:
                # Read rem_intra4x4_pred_mode (3 bits)
                rem_mode = self.reader.read_bits(3)
                mb.intra_4x4_pred_mode.append(rem_mode)
        
        # NOTE: intra_chroma_pred_mode is now parsed in parse_macroblock() for both I_4x4 and I_16x16
    
    def _read_coded_block_pattern(self) -> int:
        """
        Read Coded Block Pattern using me(v) mapping (Table 9-4)
        
        Returns:
            CBP value (0-47)
        """
        # Read me(v) value using Exp-Golomb
        pos_before = self.reader.position
        me_val = self.reader.read_ue()
        
        # Map using Table 9-4 (CodedBlockPatternMapping) - Intra
        # H.264 Table 9-4(a) for Intra macroblocks
        cbp_mapping_intra = [
            47, 31, 15, 0, 23, 27, 29, 30, 7, 11, 13, 14, 39, 43, 45, 46,
            16, 3, 5, 10, 12, 19, 21, 26, 28, 35, 37, 42, 44, 1, 2, 4,
            8, 17, 18, 20, 24, 6, 9, 22, 25, 32, 33, 34, 36, 40, 38, 41
        ]
        
        # Map using Table 9-4(b) for Inter macroblocks
        cbp_mapping_inter = [
            0, 16, 1, 2, 4, 8, 32, 3, 5, 10, 12, 15, 47, 7, 11, 13,
            14, 6, 9, 31, 35, 37, 42, 44, 33, 34, 36, 40, 39, 43, 45, 46,
            17, 18, 20, 24, 19, 21, 26, 28, 23, 27, 29, 30, 22, 25, 38, 41
        ]
        
        # Use intra mapping for intra MBs (I-slice or I-type within P-slice)
        if self._current_is_intra and me_val < len(cbp_mapping_intra):
            cbp = cbp_mapping_intra[me_val]
            return cbp
        elif not self._current_is_intra and me_val < len(cbp_mapping_inter):
            return cbp_mapping_inter[me_val]
        else:
            return me_val  # Fallback
    
    def _extract_cbp_from_i16x16(self, mb_type: MBType) -> int:
        """
        Extract CBP from I_16x16 macroblock type
        
        I_16x16_<Intra16x16PredMode>_<CodedBlockPatternChroma>_<CodedBlockPatternLuma>
        
        According to H.264 spec Table 9-1:
        - mb_type values 1-24 encode I_16x16 macroblocks
        - Format: I_16x16_<pred>_<cbp_chroma>_<cbp_luma>
        - Decoding: type_offset = mb_type - 1
          - cbp_luma = type_offset % 2 (0 or 1)
          - cbp_chroma = (type_offset % 4) // 2 (0, 1, or 2)
          - pred_mode = (type_offset % 12) // 4 (0-3)
        
        Returns:
            CBP value (6 bits: [chroma_cbp(2)][luma_cbp(4)])
        """
        if mb_type < MBType.I_16x16_0_0_0 or mb_type > MBType.I_16x16_3_2_1:
            return 0
        
        # Decode from mb_type
        type_offset = mb_type - MBType.I_16x16_0_0_0
        
        # H.264 I_16x16 CBP encoding:
        # type_offset = pred(0-3) + chroma(0-2)*4 + luma(0-1)*12
        # Therefore: luma_flag = type_offset // 12  (0 for offsets 0-11, 1 for 12-23)
        # NOT type_offset % 2 (which alternates every 2, not every 12!)
        cbp_luma_flag = type_offset // 12
        luma_cbp = 15 if cbp_luma_flag else 0

        # Chroma: (type_offset % 12) // 4 → 0=no chroma, 1=DC only, 2=DC+AC
        chroma_idx = (type_offset % 12) // 4  # 0, 1, or 2
        # 0 → no chroma residual
        # 1 → chroma DC only
        # 2 → chroma DC + AC
        if chroma_idx == 0:
            chroma_cbp = 0  # No chroma
        elif chroma_idx == 1:
            chroma_cbp = 0b01  # DC only (bit 4)
        else:  # chroma_idx == 2
            chroma_cbp = 0b11  # DC + AC (bits 4 and 5)
        
        # Combine: [chroma(2 bits)][luma(4 bits)]
        return (chroma_cbp << 4) | luma_cbp
    
    def _decode_cbp_to_blocks(self, mb: MacroblockData):
        """
        Decode CBP value to determine which blocks have residual
        
        CBP format:
        - Bits 0-3: Luma blocks (one bit per 4 4x4 blocks)
        - Bit 4: Chroma DC
        - Bit 5: Chroma AC
        """
        cbp = mb.coded_block_pattern
        
        # Luma blocks (4 bits, each covers 4 4x4 blocks)
        luma_cbp = cbp & 0x0F
        
        # Decode luma CBP (bit pattern to block pattern)
        # Each bit in luma_cbp represents 4 4x4 blocks
        for i in range(4):
            if luma_cbp & (1 << i):
                # Blocks i*4 to i*4+3 have residual
                for j in range(4):
                    mb.luma_4x4_blocks[i * 4 + j] = True
        
        # Chroma
        mb.chroma_dc_present = bool((cbp >> 4) & 1)
        mb.chroma_ac_present = bool((cbp >> 5) & 1)
    
    def get_luma_blocks_to_decode(self, mb: MacroblockData) -> List[int]:
        """
        Get list of luma 4x4 block indices that need CAVLC decoding
        
        Returns:
            List of block indices (0-15)
        """
        return [i for i in range(16) if mb.luma_4x4_blocks[i]]
    
    def calculate_nC(self, mb_x: int, mb_y: int, blk_idx: int, 
                     neighbor_coeffs: dict, mb_width: Optional[int] = None) -> int:
        """
        Calculate nC (prediction for number of coefficients) from neighbors
        
        Args:
            mb_x, mb_y: Macroblock coordinates
            blk_idx: 4x4 block index within macroblock (0-15)
            neighbor_coeffs: Dict of {(mb_global_addr, blk_idx): num_coeffs} OR legacy {(mb_x, mb_y, blk_idx): num_coeffs}
            mb_width: Picture width in MBs (required for global addr conversion)
        
        Returns:
            nC value for CAVLC table selection
        """
        # PRIORITY 3: Support both legacy (mb_x, mb_y, blk) and new (mb_global, blk) cache formats
        # Detect which format by checking a sample key
        use_global_addr = False
        if neighbor_coeffs and mb_width is not None:
            # Check first key to determine format
            first_key = next(iter(neighbor_coeffs.keys()))
            if len(first_key) == 2:  # (mb_global_addr, blk_idx)
                use_global_addr = True
        
        # Convert mb_x, mb_y to global MB address if using new format
        if use_global_addr and mb_width is not None:
            mb_global_addr = mb_y * mb_width + mb_x
        
        # Get left and top blocks
        # (Simplified - proper implementation needs full neighbor logic)
        
        # Get left and top blocks
        # Correctly map block_idx (0-15) to (x,y) in 4x4 grid
        # H.264 scan order:
        # 0 1 | 4 5
        # 2 3 | 6 7
        # -----+-----
        # 8 9 |12 13
        # 10 11|14 15
        
        # blk_idx to (x,y) mapping table
        # x: 0..3, y: 0..3
        BLOCK_XY = [
            (0,0), (1,0), (0,1), (1,1),
            (2,0), (3,0), (2,1), (3,1),
            (0,2), (1,2), (0,3), (1,3),
            (2,2), (3,2), (2,3), (3,3)
        ]
        
        if blk_idx < 16:
            blk_x, blk_y = BLOCK_XY[blk_idx]
        elif blk_idx < 20: # DC Chroma (U, V) - handled separately or mapped?
             # Chroma DC is 2x2 blocks for 4:2:0? No, 1 block per component usually for 4:2:0 YUV
             # But here block_idx 16..19 usually means:
             # 16: Cb DC
             # 17: Cr DC
             # This depends on format.
             # For nC calculation of Chroma, rules are different.
             # We simplify: return 0 or -1?
             # Standard says Chroma uses different nC logic (often nC=-1 for Chroma DC).
             return -1 # Chroma DC uses nC = -1
        else: # AC Chroma
             # 20-39 for 4:2:0 (8 AC blocks per component: 4 Cb + 4 Cr)
             # H.264 standard: Chroma AC uses nC = -2 (different VLC table)
             return -2 # Chroma AC uses nC = -2
        
        # Left neighbor
        if blk_x > 0:
             # Find neighbors in same MB
             # We need to find block_idx that has (blk_x-1, blk_y)
             # Reverse lookup? 
             # Or precompute:
             # (1,0)->0 (idx 1->0), (3,0)->2 (idx 5->4)
             # (0,1)->Left is neighbor MB
             
             # Map (blk_x-1, blk_y) back to index
             left_x = blk_x - 1
             left_y = blk_y
             # Scan BLOCK_XY to find index
             # Optimization:
             left_idx = -1
             for i, (bx, by) in enumerate(BLOCK_XY):
                 if bx == left_x and by == left_y:
                     left_idx = i
                     break
             
             # Use appropriate cache key format
             if use_global_addr:
                 left_key = (mb_global_addr, left_idx)
             else:
                 left_key = (mb_x, mb_y, left_idx)
        else:
             # Neighbor MB (Left)
             # Rightmost column of left MB is x=3
             # y matches
             left_x = 3
             left_y = blk_y
             left_idx = -1
             for i, (bx, by) in enumerate(BLOCK_XY):
                 if bx == left_x and by == left_y:
                     left_idx = i
                     break
             
             # Use appropriate cache key format
             if use_global_addr and mb_width is not None:
                 # Left MB is at (mb_x - 1, mb_y)
                 if mb_x > 0:  # Check boundary
                     left_mb_global = mb_y * mb_width + (mb_x - 1)
                     left_key = (left_mb_global, left_idx)
                 else:
                     left_key = None  # No left neighbor at edge
             else:
                 left_key = (mb_x - 1, mb_y, left_idx) if mb_x > 0 else None
             
        # Top neighbor
        if blk_y > 0:
             top_x = blk_x
             top_y = blk_y - 1
             top_idx = -1
             for i, (bx, by) in enumerate(BLOCK_XY):
                 if bx == top_x and by == top_y:
                     top_idx = i
                     break
             
             # Use appropriate cache key format
             if use_global_addr:
                 top_key = (mb_global_addr, top_idx)
             else:
                 top_key = (mb_x, mb_y, top_idx)
        else:
             # Neighbor MB (Top)
             top_x = blk_x
             top_y = 3
             top_idx = -1
             for i, (bx, by) in enumerate(BLOCK_XY):
                 if bx == top_x and by == top_y:
                     top_idx = i
                     break
             
             # Use appropriate cache key format
             if use_global_addr and mb_width is not None:
                 # Top MB is at (mb_x, mb_y - 1)
                 if mb_y > 0:  # Check boundary
                     top_mb_global = (mb_y - 1) * mb_width + mb_x
                     top_key = (top_mb_global, top_idx)
                 else:
                     top_key = None  # No top neighbor at edge
             else:
                 top_key = (mb_x, mb_y - 1, top_idx) if mb_y > 0 else None
             
        # Get neighbor counts (handle None keys for edges)
        nA = neighbor_coeffs.get(left_key, None) if left_key is not None else None
        nB = neighbor_coeffs.get(top_key, None) if top_key is not None else None

        # Calculate nC per H.264 spec Table 9-4
        # If both neighbors available: nC = (nA + nB + 1) >> 1
        # If only one available: use that one
        # If none available: nC = 0
        if nA is not None and nB is not None:
            nC = (nA + nB + 1) >> 1
        elif nA is not None:
            nC = nA
        elif nB is not None:
            nC = nB
        else:
            nC = 0

        return nC


# =============================================================================
# TRACEABLE CAVLC PARSER  (formerly traceable_cavlc_parser.py)
# =============================================================================

from typing import Dict, Tuple, Optional
from .cavlc import CAVLCDecoder


def _scan_for_mb_start(reader, from_pos, max_scan=3000):
    """
    Scan forward from from_pos to find the next valid I-slice MB start.

    For each candidate bit position, validates:
      - mb_type UE ≤ 25
      - intra_chroma_pred_mode UE ≤ 3 (for I_4x4 / I_16x16)
      - CBP me(v) ≤ 47 (for I_4x4)
      - mb_qp_delta SE in [-26, 25]

    Returns the first bit-position that passes all checks, or None if none found.
    """
    total_bits = len(reader.data) * 8
    end_scan = min(from_pos + max_scan, total_bits - 100)
    saved = reader.pos

    for candidate in range(from_pos, end_scan):
        try:
            reader.pos = candidate
            mb_type = reader.read_ue()
            if mb_type > 25:
                continue

            if mb_type == 0:           # I_4x4
                for _ in range(16):
                    prev = reader.read_bits(1)
                    if not prev:
                        reader.read_bits(3)    # rem_intra4x4_pred_mode
                icpm = reader.read_ue()
                if icpm > 3:
                    continue
                cbp_me = reader.read_ue()
                if cbp_me >= 48:
                    continue
                qp = reader.read_se()
                if qp < -26 or qp > 25:
                    continue
            elif 1 <= mb_type <= 24:   # I_16x16
                icpm = reader.read_ue()
                if icpm > 3:
                    continue
                qp = reader.read_se()
                if qp < -26 or qp > 25:
                    continue
            # mb_type == 25 (I_PCM): accept without further checks

            reader.pos = saved
            return candidate
        except Exception:
            pass

    reader.pos = saved
    return None


class TraceableCAVLCParser:
    """
    Parser that tracks bit positions while extracting coefficients.
    
    Returns both:
    - blocks: {(mb_idx, block_idx): [coeffs]}
    - offsets: {(mb_idx, block_idx): {'start_bit': int, 'end_bit': int, 'bit_length': int}}
    """
    
    def __init__(self):
        self.neighbor_coeffs = {}
        self.block_offsets = {}  # Track bit offsets
    
    def extract_with_offsets(self, nal, sps: SPSData, pps: PPSData, global_mb_idx: int = 0) -> Dict:
        """
        Extract coefficients AND track bit offsets for each block.
        
        Args:
            nal: NAL unit to parse
            sps: SPS data
            pps: PPS data
            global_mb_idx: Starting macroblock index
            
        Returns:
            {
                'blocks': {(mb_idx, block_idx): [16 coeffs]},
                'offsets': {(mb_idx, block_idx): {'start_bit': int, 'end_bit': int, 'bit_length': int}},
                'mb_metadata': {mb_idx: {'mb_type': ..., 'cbp': ...}}
            }
        """
        # Reset tracking
        self.block_offsets = {}
        self.neighbor_coeffs = {}
        
        try:
            # CRITICAL: Check if video uses CABAC (not supported)
            if hasattr(pps, 'entropy_coding_mode_flag') and pps.entropy_coding_mode_flag:
                print(f"[TraceableParser] ERROR: Video uses CABAC encoding, not CAVLC!")
                print(f"[TraceableParser] This system only supports Baseline Profile with CAVLC.")
                print(f"[TraceableParser] Please re-encode video with: ffmpeg -i input.mp4 -profile:v baseline -level 3.0 output.h264")
                return {
                    'blocks': {},
                    'offsets': {},
                    'mb_metadata': {},
                    'error': 'CABAC_NOT_SUPPORTED'
                }
            
            # Create reader from NAL data
            reader = BitstreamReader(nal.rbsp_byte)

            # Parse slice header
            slice_parser = SliceHeaderParser(reader, nal, sps, pps)
            slice_header = slice_parser.parse()
            
            # Calculate QP
            slice_qp = 26 + pps.pic_init_qp_minus26 + slice_header.slice_qp_delta
            
            mb_parser = MacroblockParser(reader, slice_header.slice_type)
            cavlc_decoder = CAVLCDecoder(reader)
            
            blocks = {}  # {(mb_idx, block_idx): [coeffs]}
            mb_metadata = {}  # {mb_idx: {'mb_type': ..., 'cbp': ...}}
            
            # Calculate max MBs in frame
            max_mbs_in_frame = (sps.pic_width_in_mbs_minus1 + 1) * (sps.pic_height_in_map_units_minus1 + 1)
            mb_width = sps.pic_width_in_mbs_minus1 + 1
            
            slice_mb_idx_counter = 0
            current_mb_addr = slice_header.first_mb_in_slice
            
            total_bits = len(reader.data) * 8
            
            # Parse all MBs in slice (FIXED: use proper termination condition)
            while slice_mb_idx_counter < max_mbs_in_frame:
                # Check if we have enough bits left
                if total_bits - reader.pos <= 8:
                    break
                
                mb_idx = current_mb_addr
                
                try:
                    # Handle mb_skip_run for P/B slices
                    if not mb_parser.is_i_slice:
                        mb_skip_run = reader.read_ue()
                        if mb_skip_run > 0:
                            # Skip MBs - all zero coefficients
                            for skip_i in range(mb_skip_run):
                                skip_mb_idx = current_mb_addr + skip_i
                                
                                # Record all blocks as zero with NO offset (not coded)
                                for block_idx in range(24):
                                    blocks[(skip_mb_idx, block_idx)] = [0] * 16
                                    # Skip blocks don't have offsets (not in bitstream)
                                
                                mb_metadata[skip_mb_idx] = {
                                    'mb_type': None,
                                    'cbp': 0,
                                    'is_skip_mb': True
                                }
                                slice_mb_idx_counter += 1
                            
                            current_mb_addr += mb_skip_run
                            mb_idx = current_mb_addr
                    
                    # Parse MB header
                    try:
                        mb_data = mb_parser.parse_macroblock()
                    except ValueError as header_err:
                        err_str = str(header_err)
                        if "desync" in err_str:
                            # reader.pos has been reset to this MB's start by parse_macroblock()
                            # Skip at least 100 bits past the corrupted MB start before scanning
                            scan_from = reader.pos + 100
                            resync_pos = _scan_for_mb_start(reader, scan_from, max_scan=3000)
                            if resync_pos is not None:
                                print(f"[TraceableParser] Resync: skipped MB {mb_idx}, next MB at bit {resync_pos}")
                                reader.pos = resync_pos
                            else:
                                print(f"[TraceableParser] Resync failed at MB {mb_idx} — stopping IDR parse")
                                break
                            current_mb_addr += 1
                            slice_mb_idx_counter += 1
                            continue
                        if mb_idx < 10:
                            print(f"    [MB_HDR_ERR] MB={mb_idx}: {header_err}")
                        current_mb_addr += 1
                        slice_mb_idx_counter += 1
                        continue
                    except Exception as header_err:
                        if mb_idx < 10:
                            print(f"    [MB_HDR_ERR] MB={mb_idx}: {header_err}")
                        # Skip this MB and continue
                        current_mb_addr += 1
                        slice_mb_idx_counter += 1
                        continue

                    # Determine MB type and decoding order
                    is_i16x16 = mb_data.mb_type >= 1 and mb_data.mb_type <= 24
                    luma_blocks = mb_parser.get_luma_blocks_to_decode(mb_data)

                    # Store MB metadata
                    mb_metadata[mb_idx] = {
                        'mb_type': mb_data.mb_type,
                        'cbp': mb_data.coded_block_pattern,
                        'is_skip_mb': mb_data.coded_block_pattern == 0,
                        'is_i16x16': is_i16x16
                    }
                    
                    # CRITICAL FIX: Parse I_16x16 DC block first (H.264 spec 8.5.6)
                    if is_i16x16:
                        # nC for I_16x16 luma DC: per H.264 spec Section 9.2.1, nC is
                        # derived ONLY from adjacent I_16x16 DC neighbors (sentinel key -1).
                        # If neighbor MB is NOT I_16x16, it does NOT contribute (nA/nB = 0).
                        # Using nC=-1 is WRONG (chroma DC table); using regular 4x4 TCs is also
                        # WRONG. x264 uses nC=0 when no I_16x16 DC neighbors are available.
                        mb_x_dc = mb_idx % mb_width
                        mb_y_dc = mb_idx // mb_width
                        dc_left_tc = None
                        dc_top_tc = None
                        if mb_x_dc > 0:
                            dc_left_tc = self.neighbor_coeffs.get((mb_idx - 1, -1))
                        if mb_y_dc > 0:
                            dc_top_tc = self.neighbor_coeffs.get((mb_idx - mb_width, -1))
                        if dc_left_tc is not None and dc_top_tc is not None:
                            nC_dc = (dc_left_tc + dc_top_tc + 1) >> 1
                        elif dc_left_tc is not None:
                            nC_dc = dc_left_tc
                        elif dc_top_tc is not None:
                            nC_dc = dc_top_tc
                        else:
                            nC_dc = 0  # No I_16x16 DC neighbors → encoder uses nC=0
                        # Parse Intra16x16DCLevel (4x4 DC coefficients, max_num_coeff=16)
                        try:
                            luma_dc_block = cavlc_decoder.decode_block_cavlc(nC_dc, max_num_coeff=16)
                            self.neighbor_coeffs[(mb_idx, -1)] = luma_dc_block.total_coeffs
                        except Exception as e:
                            self.neighbor_coeffs[(mb_idx, -1)] = 0
                            pass  # Skip on error
                    
                    # Parse luma AC blocks (0-15) for all MB types
                    luma_parsed_count = 0
                    cavlc_block_failed = False
                    for block_idx in range(16):
                        should_decode = (block_idx in luma_blocks)
                        
                        if should_decode:
                            # Calculate nC from neighbors
                            mb_x = mb_idx % mb_width
                            mb_y = mb_idx // mb_width
                            
                            cache_key = (mb_idx, block_idx)
                            
                            # CRITICAL: calculate_nC expects (mb_global, blk) format in dict
                            # We're using cache_key = (mb_idx, block_idx) which IS mb_global format
                            # Pass mb_width to signal we're using global addressing
                            nC = mb_parser.calculate_nC(mb_x, mb_y, block_idx, self.neighbor_coeffs, mb_width=mb_width)
                            
                            # KEY: Track bit position BEFORE decoding
                            block_start_bit = reader.position

                            try:
                                # Decode block (use 15 coeffs for I_16x16 AC, 16 for others)
                                max_coeffs = 15 if is_i16x16 else 16
                                block = cavlc_decoder.decode_block_cavlc(nC, max_coeffs)

                                # KEY: Track bit position AFTER decoding
                                block_end_bit = reader.position

                                # SANITY CHECK: TC must be in [0, max_coeffs] — reject desync'd blocks
                                if block.total_coeffs < 0 or block.total_coeffs > max_coeffs:
                                    raise ValueError(f"TC={block.total_coeffs} out of valid range [0,{max_coeffs}] — parser desync!")
                                
                                # CRITICAL FIX: Always store 16 coefficients (pad if I_16x16 AC)
                                # Encoder expects 16-element arrays for 4x4 blocks
                                coeffs_16 = block.levels[:16] + [0] * (16 - len(block.levels))
                                
                                # Store coefficients
                                blocks[cache_key] = coeffs_16
                                
                                # 🎯 CRITICAL: Store bit offset ONLY if block has actual bits
                                # If bit_length=0, it means decode_vlc failed and rewound the reader.
                                # That signals a VLC decode failure — no real bitstream data here.
                                # Storing bit_length=0 offsets causes patcher to try patching 0-bit
                                # regions (always fails with our_enc=N vs NAL=0 mismatch).
                                if block_end_bit > block_start_bit:
                                    self.block_offsets[cache_key] = {
                                        'start_bit': block_start_bit,
                                        'end_bit': block_end_bit,
                                        'bit_length': block_end_bit - block_start_bit,
                                        'nC': nC  # CRITICAL: Store nC for BitstreamPatcher
                                    }
                                # else: bit_length==0 → VLC decode failure (reader rewound) — no valid offset
                                
                                # Update neighbor cache WITH SAME KEY FORMAT
                                # CRITICAL: Clamp to valid range [0,16] to prevent nC corruption
                                self.neighbor_coeffs[cache_key] = min(max(block.total_coeffs, 0), 16)
                                
                                luma_parsed_count += 1
                                
                            except Exception as decode_err:
                                # Decoder failed - reader position is now unreliable
                                # Stop decoding remaining blocks to prevent cascade desync
                                blocks[cache_key] = [0] * 16
                                self.neighbor_coeffs[cache_key] = 0

                                # No offset stored for failed blocks
                                cavlc_block_failed = True
                                break  # Stop decoding remaining blocks - reader position is unreliable
                        else:
                            # Block not coded - all zeros
                            cache_key = (mb_idx, block_idx)
                            blocks[cache_key] = [0] * 16
                            self.neighbor_coeffs[cache_key] = 0
                            # No offset (block not in bitstream)
                    
                    # CRITICAL FIX: Parse ChromaDC and ChromaAC blocks (H.264 spec Table 7-11)
                    # cbp_chroma = bits 5:4 of CBP (together, not independently)
                    #   0 = no chroma residual
                    #   1 = chroma DC only
                    #   2 = chroma DC + chroma AC
                    cbp = mb_data.coded_block_pattern
                    cbp_chroma = (cbp >> 4) & 3  # 2-bit field: bits 5 and 4
                    chroma_dc_present = cbp_chroma >= 1
                    chroma_ac_present = cbp_chroma >= 2
                    
                    if not cavlc_block_failed and chroma_dc_present:
                        # Parse 2 ChromaDC blocks (Cb and Cr, each 2x2)
                        for chroma_idx in range(2):  # 0=Cb, 1=Cr
                            try:
                                # nC for ChromaDC = -1 (Table 9-4)
                                chroma_dc_block = cavlc_decoder.decode_block_cavlc(nC=-1, max_num_coeff=4)
                                # Parse to advance bitstream
                            except:
                                pass  # Skip on error

                    if not cavlc_block_failed and chroma_ac_present:
                        # Parse 8 ChromaAC blocks (4 Cb + 4 Cr, each 4x4 minus DC)
                        # nC derived from chroma-plane neighbors (same component only)
                        _CHROMA_BXY     = [(0,0),(1,0),(0,1),(1,1)]
                        _CHROMA_BXY_INV = {v: i for i, v in enumerate(_CHROMA_BXY)}
                        _mb_x = mb_idx % mb_width
                        _mb_y = mb_idx // mb_width

                        for chroma_block_idx in range(8):  # blocks 16-23
                            comp       = chroma_block_idx // 4   # 0=Cb, 1=Cr
                            local_idx  = chroma_block_idx %  4
                            bx, by     = _CHROMA_BXY[local_idx]
                            blk_offset = 16 + comp * 4           # 16→Cb, 20→Cr
                            abs_blk    = blk_offset + local_idx  # 16-23

                            # Left chroma neighbor (nA) - same component
                            # x264 initializes non_zero_count to 2 for out-of-frame
                            # neighbors (frame boundary), rather than 0 as per spec.
                            # Use 2 for truly out-of-frame boundaries to match encoder.
                            if bx > 0:
                                nA_c = self.neighbor_coeffs.get(
                                    (mb_idx, blk_offset + _CHROMA_BXY_INV[(bx-1, by)]))
                            elif _mb_x > 0:
                                nA_c = self.neighbor_coeffs.get(
                                    (mb_idx - 1, blk_offset + _CHROMA_BXY_INV[(1, by)]))
                            else:
                                nA_c = 2  # out-of-frame left boundary

                            # Top chroma neighbor (nB) - same component
                            if by > 0:
                                nB_c = self.neighbor_coeffs.get(
                                    (mb_idx, blk_offset + _CHROMA_BXY_INV[(bx, by-1)]))
                            elif _mb_y > 0:
                                nB_c = self.neighbor_coeffs.get(
                                    (mb_idx - mb_width, blk_offset + _CHROMA_BXY_INV[(bx, 1)]))
                            else:
                                nB_c = 2  # out-of-frame top boundary

                            # nC for chroma AC: derived from same-component neighbors
                            if nA_c is not None and nB_c is not None:
                                nC_chroma = (nA_c + nB_c + 1) >> 1
                            elif nA_c is not None:
                                nC_chroma = nA_c
                            elif nB_c is not None:
                                nC_chroma = nB_c
                            else:
                                nC_chroma = 0

                            try:
                                pos_blk_start = reader.position
                                chroma_ac_block = cavlc_decoder.decode_block_cavlc(
                                    nC=nC_chroma, max_num_coeff=15)
                                self.neighbor_coeffs[(mb_idx, abs_blk)] = min(
                                    max(chroma_ac_block.total_coeffs, 0), 15)
                            except Exception as cac_err:
                                reader.seek(pos_blk_start)  # reset on decode failure
                                self.neighbor_coeffs[(mb_idx, abs_blk)] = 0

                    current_mb_addr += 1
                    slice_mb_idx_counter += 1
                    
                except Exception as mb_err:
                    print(f"[TraceableParser] MB {slice_mb_idx_counter} error: {mb_err}")
                    break
            
            print(f"[TraceableParser] Extracted {len(blocks)} blocks with {len(self.block_offsets)} offsets")
            
            return {
                'blocks': blocks,
                'offsets': self.block_offsets,
                'mb_metadata': mb_metadata,
                'num_mbs': slice_mb_idx_counter  # CRITICAL: actual MB count including SKIP MBs
            }
            
        except Exception as e:
            print(f"[TraceableParser] Extraction error: {e}")
            import traceback
            traceback.print_exc()
            return {
                'blocks': {},
                'offsets': {},
                'mb_metadata': {}
            }
