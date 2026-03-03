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
from .bitstream_io import BitstreamReader


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
        
        # DEBUG: Track bit consumption for first MB
        pos_start = self.reader.position
        debug_first_mb = False  # Disabled for production
        
        # 1. Read mb_type
        mb.mb_type = self._read_mb_type()
        mb.mb_type_enum = self._interpret_mb_type(mb.mb_type)
        
        if debug_first_mb:
            pos_after_type = self.reader.position
            print(f"    [MB_BITS] After mb_type: Pos:{pos_after_type} (consumed {pos_after_type - pos_start} bits)")
        
        # CRITICAL FIX: Validate mb_type and recover from errors
        if mb.mb_type_enum is None:
            # Unknown mb_type - this shouldn't happen after fix in _interpret_mb_type
            # but add safety check anyway
            print(f"[ERROR] Unknown mb_type={mb.mb_type} in slice_type={self.slice_type}!")
            print(f"[RECOVERY] Using I_4x4 fallback")
            mb.mb_type_enum = MBType.I_4x4  # Safe default

        # ADDITIONAL CHECK: Validate we're not too far off alignment
        if mb.mb_type > 100:  # Sanity check - no valid mb_type should be this high
            print(f"[ERROR] mb_type={mb.mb_type} suggests severe bitstream corruption!")
            print(f"[RECOVERY] Attempting to continue with fallback")

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
            if debug_first_mb:
                pos_after_pred = self.reader.position
                print(f"    [MB_BITS] After intra_4x4_pred_mode: Pos:{pos_after_pred} (consumed {pos_after_pred - pos_after_type} bits)")

        # PRIORITY 2 FIX: Parse chroma pred mode for ALL Intra MBs (I_4x4 AND I_16x16)
        # H.264 Spec: intra_chroma_pred_mode exists for both I_NxN and I_16x16!
        # Also applies to I-type MBs within P-slices (not just pure I-slices).
        if self._current_is_intra and mb.mb_type_enum != MBType.I_PCM:
            mb.intra_chroma_pred_mode = self.reader.read_ue()

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
                # CRITICAL FIX: mb_type > 25 indicates bitstream misalignment
                # Instead of returning None (which causes cascade failures),
                # treat as I_4x4 to allow parsing to continue
                print(f"[WARN] mb_type={mb_type} > 25 in I-slice (slice_type={self.slice_type})")
                print(f"[FIX] Treating as I_4x4 to prevent cascade failure")
                return MBType.I_4x4  # Fallback to most common type
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
                # CRITICAL FIX: Invalid mb_type in P-slice
                print(f"[WARN] mb_type={mb_type} > 30 in P-slice (slice_type={self.slice_type})")
                print(f"[FIX] Treating as P_L0_16x16 to prevent cascade failure")
                return MBType.P_L0_16x16  # Fallback
        else:
            # Unknown slice type
            print(f"[WARN] Unknown slice_type={self.slice_type}, mb_type={mb_type}")
            return MBType.I_4x4  # Safe fallback
        
        return MBType.I_4x4  # Default fallback
    
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
            # DEBUG: Log CBP mapping for first few MBs
            if pos_before < 100:
                pos_after = self.reader.position
                print(f"    [CBP_READ] Pos:{pos_before} UE:{me_val} -> CBP:{cbp} (I-type) (consumed {pos_after - pos_before} bits)")
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
        
        # Debug nC calculation for first few blocks
        debug_nC = False
        if use_global_addr and mb_global_addr < 2 and blk_idx < 4:
            debug_nC = True
            print(f"        [nC_CALC] MB={mb_global_addr}, Blk={blk_idx} ({blk_x},{blk_y})")
            print(f"        [nC_CALC] Left: key={left_key}, nA={nA}")
            print(f"        [nC_CALC] Top:  key={top_key}, nB={nB}")
            if len(neighbor_coeffs) <= 10:
                print(f"        [nC_CALC] Cache: {dict(list(neighbor_coeffs.items())[:10])}")
        
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
        
        if debug_nC:
            print(f"        [nC_CALC] Result: nC={nC}")
        
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
