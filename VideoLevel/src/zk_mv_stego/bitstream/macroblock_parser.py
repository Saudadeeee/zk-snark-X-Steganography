"""
Macroblock Parser for H.264 Baseline Profile

Parses macroblock layer to extract:
- Macroblock type (I_4x4, I_16x16, P, etc.)
- Coded Block Pattern (CBP)
- Quantization Parameter delta
- Residual data locations for CAVLC decoding

References:
- ITU-T H.264 (2021) Section 7.3.5: Macroblock layer
- Section 7.4.5: Macroblock layer semantics
"""

from dataclasses import dataclass
from typing import List, Optional
from enum import IntEnum

from .h264_parser import BitstreamReader


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
    
    def __init__(self, reader: BitstreamReader, slice_type: int):
        self.reader = reader
        self.slice_type = slice_type
        self.is_i_slice = slice_type in [2, 7]  # I or IDR
        self.is_p_slice = slice_type in [0, 5]  # P slice
        
        # Current QP (starts from PPS QP, updated by mb_qp_delta)
        self.current_qp = 26  # Default, should be from PPS
    
    def parse_macroblock(self) -> MacroblockData:
        """
        Parse one macroblock from bitstream
        
        Returns:
            MacroblockData with all parsed information
        """
        mb = MacroblockData(mb_type=0, mb_type_enum=None)
        
        # 1. Read mb_type
        mb.mb_type = self._read_mb_type()
        mb.mb_type_enum = self._interpret_mb_type(mb.mb_type)
        
        # 2. Handle I_PCM special case
        if mb.mb_type_enum == MBType.I_PCM:
            self._parse_i_pcm(mb)
            return mb
        
        # 3. Parse prediction mode for I_4x4
        if mb.mb_type_enum == MBType.I_4x4:
            self._parse_intra_4x4_pred_mode(mb)
        
        # 4. Parse Coded Block Pattern (if not I_16x16)
        if not self._is_i16x16(mb.mb_type_enum):
            mb.coded_block_pattern = self._read_coded_block_pattern()
        else:
            # I_16x16: CBP is encoded in mb_type
            mb.coded_block_pattern = self._extract_cbp_from_i16x16(mb.mb_type_enum)
        
        # 5. Parse QP delta
        if mb.coded_block_pattern > 0 or self._is_i16x16(mb.mb_type_enum):
            mb.mb_qp_delta = self.reader.read_se()
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
        """Convert mb_type value to MBType enum"""
        if self.is_i_slice:
            if mb_type <= 25:
                return MBType(mb_type)
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
            # I types in P slice
            elif mb_type >= 5 and mb_type <= 30:
                return MBType(mb_type - 5)
        
        return None
    
    def _is_i16x16(self, mb_type: Optional[MBType]) -> bool:
        """Check if macroblock is I_16x16 type"""
        if mb_type is None:
            return False
        return MBType.I_16x16_0_0_0 <= mb_type <= MBType.I_16x16_3_2_1
    
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
        """Parse prediction modes for I_4x4 blocks"""
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
        
        # Parse chroma intra prediction mode (ue(v))
        if self.is_i_slice:
            mb.intra_chroma_pred_mode = self.reader.read_ue()
    
    def _read_coded_block_pattern(self) -> int:
        """
        Read Coded Block Pattern using me(v) mapping (Table 9-4)
        
        Returns:
            CBP value (0-47)
        """
        # Read me(v) value using Exp-Golomb
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
        
        # Use intra mapping if I-slice (simplified - should check mb_type)
        if self.is_i_slice and me_val < len(cbp_mapping_intra):
            return cbp_mapping_intra[me_val]
        elif not self.is_i_slice and me_val < len(cbp_mapping_inter):
            return cbp_mapping_inter[me_val]
        else:
            return me_val  # Fallback
    
    def _extract_cbp_from_i16x16(self, mb_type: MBType) -> int:
        """
        Extract CBP from I_16x16 macroblock type
        
        I_16x16_<Intra16x16PredMode>_<CodedBlockPatternChroma>_<CodedBlockPatternLuma>
        
        Returns:
            CBP value
        """
        if mb_type < MBType.I_16x16_0_0_0 or mb_type > MBType.I_16x16_3_2_1:
            return 0
        
        # Decode from mb_type
        type_idx = mb_type - MBType.I_16x16_0_0_0
        
        # Luma: 0 or 15 (all blocks)
        luma_cbp = (type_idx // 12) * 15
        
        # Chroma
        chroma_idx = (type_idx % 12) // 4
        if chroma_idx == 0:
            chroma_cbp = 0  # No chroma
        elif chroma_idx == 1:
            chroma_cbp = 0b01  # DC only
        else:  # chroma_idx == 2
            chroma_cbp = 0b11  # DC + AC
        
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
                     neighbor_coeffs: dict) -> int:
        """
        Calculate nC (prediction for number of coefficients) from neighbors
        
        Args:
            mb_x, mb_y: Macroblock coordinates
            blk_idx: 4x4 block index within macroblock (0-15)
            neighbor_coeffs: Dict of {(mb_x, mb_y, blk_idx): num_coeffs}
        
        Returns:
            nC value for CAVLC table selection
        """
        # Get left and top blocks
        # (Simplified - proper implementation needs full neighbor logic)
        
        # Block position within MB (0-15)
        blk_x = blk_idx % 4
        blk_y = blk_idx // 4
        
        # Left block
        if blk_x > 0:
            left_key = (mb_x, mb_y, blk_idx - 1)
        else:
            left_key = (mb_x - 1, mb_y, blk_idx + 3)
        
        # Top block
        if blk_y > 0:
            top_key = (mb_x, mb_y, blk_idx - 4)
        else:
            top_key = (mb_x, mb_y - 1, blk_idx + 12)
        
        # Get neighbor counts
        nA = neighbor_coeffs.get(left_key, 0)
        nB = neighbor_coeffs.get(top_key, 0)
        
        # Calculate nC
        if nA >= 0 and nB >= 0:
            nC = (nA + nB + 1) // 2
        elif nA >= 0:
            nC = nA
        elif nB >= 0:
            nC = nB
        else:
            nC = 0
        
        return nC


def parse_macroblock_layer(reader: BitstreamReader, slice_type: int, 
                           num_mbs: int) -> List[MacroblockData]:
    """
    Parse macroblock layer for entire slice
    
    Args:
        reader: BitstreamReader positioned at macroblock data
        slice_type: Slice type from slice header
        num_mbs: Number of macroblocks to parse
    
    Returns:
        List of MacroblockData
    """
    parser = MacroblockParser(reader, slice_type)
    macroblocks = []
    
    for _ in range(num_mbs):
        mb = parser.parse_macroblock()
        macroblocks.append(mb)
    
    return macroblocks
