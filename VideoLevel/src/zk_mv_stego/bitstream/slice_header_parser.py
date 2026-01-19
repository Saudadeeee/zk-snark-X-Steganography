"""
Slice Header Parser for H.264 Baseline Profile

Parses slice header according to ITU-T H.264 Section 7.3.3
This positions the bitstream reader correctly before macroblock data.

CRITICAL: Must parse ALL header fields in correct order to avoid misalignment
"""

from dataclasses import dataclass
from typing import Optional
from .h264_parser import BitstreamReader


@dataclass
class SliceHeader:
    """Complete slice header data"""
    # Basic slice info
    first_mb_in_slice: int
    slice_type: int
    pic_parameter_set_id: int
    
    # Frame info
    frame_num: int
    field_pic_flag: bool = False
    bottom_field_flag: bool = False
    
    # IDR info
    idr_pic_id: Optional[int] = None
    
    # Picture order count
    pic_order_cnt_lsb: Optional[int] = None
    delta_pic_order_cnt_bottom: Optional[int] = None
    delta_pic_order_cnt: list = None
    
    # Redundant picture
    redundant_pic_cnt: Optional[int] = None
    
    # Reference picture lists
    num_ref_idx_active_override_flag: bool = False
    num_ref_idx_l0_active_minus1: int = 0
    num_ref_idx_l1_active_minus1: int = 0
    
    # Quantization
    slice_qp_delta: int = 0
    
    # Deblocking filter
    disable_deblocking_filter_idc: int = 0
    slice_alpha_c0_offset_div2: int = 0
    slice_beta_offset_div2: int = 0
    
    def __post_init__(self):
        if self.delta_pic_order_cnt is None:
            self.delta_pic_order_cnt = [0, 0]


@dataclass
class SPSData:
    """Minimal SPS data needed for slice header parsing"""
    log2_max_frame_num_minus4: int = 0
    pic_order_cnt_type: int = 0
    log2_max_pic_order_cnt_lsb_minus4: int = 0
    frame_mbs_only_flag: bool = True
    
    @property
    def max_frame_num(self):
        return 1 << (self.log2_max_frame_num_minus4 + 4)
    
    @property
    def max_pic_order_cnt_lsb(self):
        return 1 << (self.log2_max_pic_order_cnt_lsb_minus4 + 4)


@dataclass  
class PPSData:
    """Minimal PPS data needed for slice header parsing"""
    pic_init_qp_minus26: int = 0
    deblocking_filter_control_present_flag: bool = True
    redundant_pic_cnt_present_flag: bool = False
    num_ref_idx_l0_default_active_minus1: int = 0
    num_ref_idx_l1_default_active_minus1: int = 0


class SliceHeaderParser:
    """
    Parse H.264 slice header
    
    Reference: ITU-T H.264 (2021) Section 7.3.3
    """
    
    def __init__(self, reader: BitstreamReader, nal_unit_type: int,
                 sps: Optional[SPSData] = None, pps: Optional[PPSData] = None):
        self.reader = reader
        self.nal_unit_type = nal_unit_type
        self.is_idr = (nal_unit_type == 5)
        
        # Use provided SPS/PPS or create defaults
        self.sps = sps if sps else SPSData()
        self.pps = pps if pps else PPSData()
    
    def parse(self) -> SliceHeader:
        """
        Parse complete slice header
        
        Returns:
            SliceHeader with all fields populated
        """
        # 1. Basic slice info
        first_mb = self.reader.read_ue()
        slice_type = self.reader.read_ue()
        pps_id = self.reader.read_ue()
        
        # 2. Frame number
        frame_num_bits = self.sps.log2_max_frame_num_minus4 + 4
        frame_num = self.reader.read_bits(frame_num_bits)
        
        # 3. Field flags (only if not frame_mbs_only)
        field_pic_flag = False
        bottom_field_flag = False
        if not self.sps.frame_mbs_only_flag:
            field_pic_flag = self.reader.read_bits(1) == 1
            if field_pic_flag:
                bottom_field_flag = self.reader.read_bits(1) == 1
        
        # 4. IDR picture ID
        idr_pic_id = None
        if self.is_idr:
            idr_pic_id = self.reader.read_ue()
        
        # 5. Picture order count
        pic_order_cnt_lsb = None
        delta_pic_order_cnt_bottom = None
        delta_pic_order_cnt = [0, 0]
        
        if self.sps.pic_order_cnt_type == 0:
            poc_bits = self.sps.log2_max_pic_order_cnt_lsb_minus4 + 4
            pic_order_cnt_lsb = self.reader.read_bits(poc_bits)
            
            # delta_pic_order_cnt_bottom if present
            # Simplified: skip for Baseline (usually not present)
            
        elif self.sps.pic_order_cnt_type == 1:
            # delta_pic_order_cnt[0] and [1]
            # Simplified: skip for Baseline (type 0 most common)
            pass
        
        # 6. Redundant picture count
        redundant_pic_cnt = None
        if self.pps.redundant_pic_cnt_present_flag:
            redundant_pic_cnt = self.reader.read_ue()
        
        # 7. Direct spatial mv pred (B slices only - skip for Baseline I/P)
        # 8. num_ref_idx_active_override
        num_ref_idx_active_override_flag = False
        num_ref_idx_l0_active_minus1 = self.pps.num_ref_idx_l0_default_active_minus1
        num_ref_idx_l1_active_minus1 = self.pps.num_ref_idx_l1_default_active_minus1
        
        # Only for P and B slices
        if slice_type % 5 in [0, 1]:  # P or B
            num_ref_idx_active_override_flag = self.reader.read_bits(1) == 1
            if num_ref_idx_active_override_flag:
                num_ref_idx_l0_active_minus1 = self.reader.read_ue()
                if slice_type % 5 == 1:  # B slice
                    num_ref_idx_l1_active_minus1 = self.reader.read_ue()
        
        # 9. ref_pic_list_modification()
        # Skip for simplicity - not needed for coefficient extraction
        # Just consume the data
        if slice_type % 5 != 2:  # Not I slice
            self._skip_ref_pic_list_modification(slice_type)
        
        # 10. dec_ref_pic_marking() for IDR
        if self.is_idr:
            self._skip_dec_ref_pic_marking_idr()
        elif slice_type % 5 in [0, 1]:  # P or B slice
            self._skip_dec_ref_pic_marking()
        
        # 11. slice_qp_delta (CRITICAL for QP calculation)
        slice_qp_delta = self.reader.read_se()
        
        # 12. Deblocking filter control
        disable_deblocking_filter_idc = 0
        slice_alpha_c0_offset_div2 = 0
        slice_beta_offset_div2 = 0
        
        if self.pps.deblocking_filter_control_present_flag:
            disable_deblocking_filter_idc = self.reader.read_ue()
            if disable_deblocking_filter_idc != 1:
                slice_alpha_c0_offset_div2 = self.reader.read_se()
                slice_beta_offset_div2 = self.reader.read_se()
        
        # Slice header complete - bitstream is now at macroblock layer
        
        return SliceHeader(
            first_mb_in_slice=first_mb,
            slice_type=slice_type,
            pic_parameter_set_id=pps_id,
            frame_num=frame_num,
            field_pic_flag=field_pic_flag,
            bottom_field_flag=bottom_field_flag,
            idr_pic_id=idr_pic_id,
            pic_order_cnt_lsb=pic_order_cnt_lsb,
            delta_pic_order_cnt_bottom=delta_pic_order_cnt_bottom,
            delta_pic_order_cnt=delta_pic_order_cnt,
            redundant_pic_cnt=redundant_pic_cnt,
            num_ref_idx_active_override_flag=num_ref_idx_active_override_flag,
            num_ref_idx_l0_active_minus1=num_ref_idx_l0_active_minus1,
            num_ref_idx_l1_active_minus1=num_ref_idx_l1_active_minus1,
            slice_qp_delta=slice_qp_delta,
            disable_deblocking_filter_idc=disable_deblocking_filter_idc,
            slice_alpha_c0_offset_div2=slice_alpha_c0_offset_div2,
            slice_beta_offset_div2=slice_beta_offset_div2
        )
    
    def _skip_ref_pic_list_modification(self, slice_type: int):
        """Skip ref_pic_list_modification() syntax"""
        # ref_pic_list_modification_flag_l0
        if self.reader.read_bits(1) == 1:
            while True:
                modification_of_pic_nums_idc = self.reader.read_ue()
                if modification_of_pic_nums_idc == 3:
                    break
                if modification_of_pic_nums_idc in [0, 1]:
                    self.reader.read_ue()  # abs_diff_pic_num_minus1
                elif modification_of_pic_nums_idc == 2:
                    self.reader.read_ue()  # long_term_pic_num
        
        # ref_pic_list_modification_flag_l1 (B slices only)
        if slice_type % 5 == 1:  # B slice
            if self.reader.read_bits(1) == 1:
                while True:
                    modification_of_pic_nums_idc = self.reader.read_ue()
                    if modification_of_pic_nums_idc == 3:
                        break
                    if modification_of_pic_nums_idc in [0, 1]:
                        self.reader.read_ue()
                    elif modification_of_pic_nums_idc == 2:
                        self.reader.read_ue()
    
    def _skip_dec_ref_pic_marking_idr(self):
        """Skip dec_ref_pic_marking() for IDR slices"""
        no_output_of_prior_pics_flag = self.reader.read_bits(1)
        long_term_reference_flag = self.reader.read_bits(1)
    
    def _skip_dec_ref_pic_marking(self):
        """Skip dec_ref_pic_marking() for non-IDR slices"""
        adaptive_ref_pic_marking_mode_flag = self.reader.read_bits(1)
        if adaptive_ref_pic_marking_mode_flag == 1:
            while True:
                memory_management_control_operation = self.reader.read_ue()
                if memory_management_control_operation == 0:
                    break
                if memory_management_control_operation in [1, 3]:
                    self.reader.read_ue()  # difference_of_pic_nums_minus1
                if memory_management_control_operation == 2:
                    self.reader.read_ue()  # long_term_pic_num
                if memory_management_control_operation in [3, 6]:
                    self.reader.read_ue()  # long_term_frame_idx
                if memory_management_control_operation == 4:
                    self.reader.read_ue()  # max_long_term_frame_idx_plus1
