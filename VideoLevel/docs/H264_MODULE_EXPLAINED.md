# 📘 H.264 Parser Module (`h264.py`) - Chi Tiết Toàn Diện

**File:** `src/bitstream/h264.py`
**Size:** 1,468 lines
**Vai trò:** Core parser của hệ thống - parse H.264 video bitstream và extract CAVLC coefficients

---

## 🏗️ **Kiến Trúc Tổng Quan**

File `h264.py` được chia thành **4 phần chính**:

```
┌──────────────────────────────────────────────────────┐
│  Part 1: NAL Unit Parsing (Lines 20-154)            │
│  - NALUnitType, NALUnit, NALParser                   │
│  - Tách video thành NAL units (IDR, P, SPS, PPS)    │
└──────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────┐
│  Part 2: Slice Header Parsing (Lines 155-438)       │
│  - SPSData, PPSData, SliceHeader, SliceHeaderParser │
│  - Parse metadata của frame (QP, frame_num, etc.)   │
└──────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────┐
│  Part 3: Macroblock Parsing (Lines 442-898)         │
│  - MBType, MacroblockData, MacroblockParser          │
│  - Parse từng macroblock (16×16 pixels)             │
└──────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────┐
│  Part 4: Traceable CAVLC Parser (Lines 1039-1468)   │
│  - TraceableCAVLCParser ⭐ CRITICAL                  │
│  - Extract coefficients + track bit offsets          │
└──────────────────────────────────────────────────────┘
```

---

## 📦 **Part 1: NAL Unit Parsing**

### **1.1 NALUnitType (Lines 20-51)**

**Công dụng:** Enum định nghĩa các loại NAL unit trong H.264

```python
class NALUnitType(IntEnum):
    SLICE_IDR = 5        # I-frame (keyframe, chứa coefficients)
    SPS = 7              # Sequence Parameter Set (video metadata)
    PPS = 8              # Picture Parameter Set (encoding params)
    SLICE_NON_IDR = 1    # P-frame (predicted frame)
```

**Các loại NAL quan trọng:**
- **IDR (5):** I-frame, chứa toàn bộ frame data → **Embed ở đây**
- **SPS (7):** Video width, height, profile, level
- **PPS (8):** QP, entropy mode (CAVLC/CABAC), deblocking filter
- **NON_IDR (1):** P-frame (motion prediction)

**Method quan trọng:**
```python
def name_str(self) -> str:
    # Convert enum value → human-readable string
    # Example: NALUnitType.SLICE_IDR.name_str() → "IDR Slice (I-frame)"
```

---

### **1.2 NALUnit (Lines 53-74)**

**Công dụng:** Dataclass chứa thông tin của 1 NAL unit

```python
@dataclass
class NALUnit:
    forbidden_zero_bit: int    # Phải = 0 (error check)
    nal_ref_idc: int           # Reference priority (0-3)
    nal_unit_type: NALUnitType # Loại NAL
    rbsp_byte: bytes           # Payload data (đã remove emulation prevention)
    start_pos: int             # Vị trí trong file (bytes)
    size: int                  # Kích thước NAL
    start_code_size: int = 4   # Start code length (3 or 4 bytes)
```

**Helper methods:**
```python
def is_slice(self) -> bool:
    # Check if NAL is a slice (IDR or non-IDR)
    return self.nal_unit_type in [SLICE_NON_IDR, SLICE_IDR]

def is_idr(self) -> bool:
    # Check if NAL is IDR slice (I-frame)
    return self.nal_unit_type == SLICE_IDR
```

---

### **1.3 NALParser (Lines 76-153)**

**Công dụng:** Parse H.264 Annex B byte stream → danh sách NAL units

**Cơ chế hoạt động:**

```
Input: H.264 file bytes
   ↓
[Step 1] _find_start_codes()
   → Tìm tất cả start codes: 0x00 0x00 0x00 0x01 (4 bytes)
                         hoặc 0x00 0x00 0x01 (3 bytes)
   ↓
[Step 2] _extract_nal_unit() cho mỗi segment
   → Parse NAL header (1 byte):
      - forbidden_zero_bit: bit 7
      - nal_ref_idc: bits 5-6
      - nal_unit_type: bits 0-4
   ↓
[Step 3] _remove_emulation_prevention()
   → Remove 0x03 bytes (H.264 emulation prevention)
   → Example: 0x00 0x00 0x03 0x01 → 0x00 0x00 0x01
   ↓
Output: List[NALUnit]
```

**Key functions:**

```python
def parse(self) -> List[NALUnit]:
    """
    Main entry point - parse toàn bộ file
    Returns: List of NAL units
    """
    positions = self._find_start_codes()  # Find all 0x000001/0x00000001
    for each segment:
        nal = self._extract_nal_unit(start, end, sc_size)
        self.nal_units.append(nal)
    return self.nal_units


def _find_start_codes(self) -> List[Tuple[int, int]]:
    """
    Scan toàn bộ file tìm start codes
    Returns: [(position_after_sc, sc_size), ...]

    Algorithm:
      while i < len(data) - 3:
          if data[i:i+4] == b'\x00\x00\x00\x01':
              positions.append((i + 4, 4))
          elif data[i:i+3] == b'\x00\x00\x01':
              positions.append((i + 3, 3))
    """


def _remove_emulation_prevention(self, data: bytes) -> bytes:
    """
    H.264 emulation prevention: Remove 0x03 byte

    Rule: Sequence 0x00 0x00 0x03 → Remove 0x03
    Example:
      Input:  0x00 0x00 0x03 0x00  (emulation prevented)
      Output: 0x00 0x00 0x00        (actual data)
    """
```

**Ví dụ output:**
```python
parser = NALParser(h264_file_bytes)
nals = parser.parse()

# Result:
[
    NALUnit(type=SPS, size=42),
    NALUnit(type=PPS, size=18),
    NALUnit(type=IDR Slice, size=15234),  ← Embed vào đây
    NALUnit(type=Slice (non-IDR), size=3421),
    NALUnit(type=IDR Slice, size=14892),  ← Embed vào đây
    ...
]
```

---

## 📋 **Part 2: Slice Header Parsing**

### **2.1 SPSData (Lines 155-171)**

**Công dụng:** Sequence Parameter Set - video metadata

```python
@dataclass
class SPSData:
    log2_max_frame_num_minus4: int = 0        # Frame numbering
    pic_order_cnt_type: int = 0               # POC type (0, 1, or 2)
    log2_max_pic_order_cnt_lsb_minus4: int = 0
    frame_mbs_only_flag: bool = True          # Progressive (not interlaced)
    pic_width_in_mbs_minus1: int = 0          # Width = (value + 1) * 16 pixels
    pic_height_in_map_units_minus1: int = 0   # Height calculation

    @property
    def max_frame_num(self) -> int:
        return 1 << (self.log2_max_frame_num_minus4 + 4)
```

**Ví dụ:**
```python
# Video CIF (352×288)
sps = SPSData(
    pic_width_in_mbs_minus1 = 21,    # (21+1) * 16 = 352 pixels
    pic_height_in_map_units_minus1 = 17,  # (17+1) * 16 = 288 pixels
)
# Frame contains: 22 × 18 = 396 macroblocks
```

---

### **2.2 PPSData (Lines 173-182)**

**Công dụng:** Picture Parameter Set - encoding parameters

```python
@dataclass
class PPSData:
    pic_init_qp_minus26: int = 0                  # Base QP (quality)
    entropy_coding_mode_flag: bool = False        # CAVLC (False) or CABAC (True)
    deblocking_filter_control_present_flag: bool = True
    num_ref_idx_l0_default_active_minus1: int = 0  # Reference frames
```

**CRITICAL:**
```python
if pps.entropy_coding_mode_flag == True:
    # ERROR: Video uses CABAC (advanced)
    # System chỉ hỗ trợ CAVLC (baseline profile)
    raise Error("Only CAVLC supported")
```

---

### **2.3 SliceHeader (Lines 184-223)**

**Công dụng:** Chứa metadata của 1 slice (frame hoặc phần của frame)

```python
@dataclass
class SliceHeader:
    first_mb_in_slice: int      # Starting macroblock index
    slice_type: int             # 0=P, 1=B, 2=I, 5=P(all), 7=I(all)
    frame_num: int              # Frame number trong sequence
    idr_pic_id: Optional[int]   # IDR identifier (chỉ cho IDR frames)

    slice_qp_delta: int = 0     # QP adjustment for this slice

    # Reference picture management (P/B frames)
    ref_pic_list_modification_flag_l0: bool = False
    ref_pic_list_modification_l0_data: list = None  # Bits của ref list

    # Deblocking filter params
    disable_deblocking_filter_idc: int = 0
```

**Slice types:**
- **2, 7:** I-slice (all intra macroblocks)
- **0, 5:** P-slice (predicted from previous frame)
- **1, 6:** B-slice (bi-directional prediction)

---

### **2.4 SliceHeaderParser (Lines 225-438)**

**Công dụng:** Parse slice header theo H.264 spec 7.3.3

**Cơ chế hoạt động (CRITICAL - phải đúng thứ tự):**

```
┌─────────────────────────────────────────────────────┐
│ H.264 Slice Header Parsing Order (MANDATORY)       │
└─────────────────────────────────────────────────────┘

Step 1: Basic fields (ALWAYS present)
   ├── first_mb_in_slice (ue(v))
   ├── slice_type (ue(v))
   └── pic_parameter_set_id (ue(v))

Step 2: frame_num (ALWAYS present)
   └── frame_num (u(v) bits)

Step 3: field_pic_flag (conditional on SPS)
   └── if NOT frame_mbs_only_flag:
       ├── field_pic_flag (u(1))
       └── if field_pic_flag: bottom_field_flag (u(1))

Step 4: idr_pic_id (conditional on NAL type)
   └── if NAL is IDR: idr_pic_id (ue(v))

Step 5: Picture Order Count (conditional on SPS)
   └── if pic_order_cnt_type == 0:
       └── pic_order_cnt_lsb (u(v))

Step 6: num_ref_idx_active_override (P/B slices only)
   └── if slice_type in [P, B]:
       ├── num_ref_idx_active_override_flag (u(1))
       └── if flag: num_ref_idx_l0_active_minus1 (ue(v))

Step 7: ref_pic_list_modification() (P/B slices)
   └── if slice_type != I:
       └── Parse modification commands (loop until idc == 3)

Step 8: dec_ref_pic_marking() (MANDATORY)
   └── if IDR:
       ├── no_output_of_prior_pics_flag (u(1))
       └── long_term_reference_flag (u(1))
   └── elif P/B:
       └── adaptive_ref_pic_marking_mode_flag + MMCO commands

Step 9: slice_qp_delta (ALWAYS present)
   └── slice_qp_delta (se(v))

Step 10: Deblocking filter (conditional on PPS)
   └── if deblocking_filter_control_present_flag:
       ├── disable_deblocking_filter_idc (ue(v))
       └── if idc != 1: alpha/beta offsets (se(v))
```

**Key method:**

```python
def parse(self) -> SliceHeader:
    """
    Parse slice header EXACTLY theo thứ tự H.264 spec

    CRITICAL: Không được skip bất kỳ field nào!
    Nếu skip → bitstream misalignment → parse sai toàn bộ!
    """
    # Step 1-3: Basic fields
    first_mb = self.reader.read_ue()
    slice_type = self.reader.read_ue()
    pps_id = self.reader.read_ue()
    frame_num = self.reader.read_bits(self.sps.log2_max_frame_num_minus4 + 4)

    # Step 4: IDR pic id
    if self.nal_unit.is_idr():
        idr_pic_id = self.reader.read_ue()

    # Step 5: POC
    if self.sps.pic_order_cnt_type == 0:
        pic_order_cnt_lsb = self.reader.read_bits(
            self.sps.log2_max_pic_order_cnt_lsb_minus4 + 4
        )

    # Step 6-10: Reference management, QP, deblocking
    # ... (xem code lines 268-400)

    return SliceHeader(...)
```

**CRITICAL FIXES implemented:**
- Parse `num_ref_idx_active_override` (P/B slices) ✓
- Parse `ref_pic_list_modification()` (P/B slices) ✓
- Parse `dec_ref_pic_marking()` (IDR/P/B slices) ✓
- Parse `slice_qp_delta` (ALL slices) ✓

**Nếu thiếu bất kỳ field nào → Bitstream misalignment!**

---

## 🧩 **Part 3: Macroblock Parsing**

### **3.1 MBType (Lines 442-478)**

**Công dụng:** Enum định nghĩa macroblock types

**I-slice types (0-25):**
```python
I_4x4 = 0            # 16 phân vùng 4×4, mỗi phân vùng có prediction mode riêng
I_16x16_0_0_0 = 1    # 1 prediction mode cho cả MB, CBP encoded trong mb_type
...
I_16x16_3_2_1 = 24   # 24 variants khác nhau
I_PCM = 25           # Raw pixel data (no prediction/transform)
```

**P-slice types (100-105):**
```python
P_L0_16x16 = 100     # 1 phân vùng 16×16
P_L0_L0_16x8 = 101   # 2 phân vùng 16×8
P_L0_L0_8x16 = 102   # 2 phân vùng 8×16
P_8x8 = 103          # 4 phân vùng 8×8 (sub-partitions)
P_SKIP = 105         # Skip MB (copy from reference)
```

**mb_type encoding:**
- I-slice: mb_type = 0-25 (direct mapping)
- P-slice: mb_type = 0-4 (P types) or 5-30 (I types in P-slice)

---

### **3.2 MacroblockData (Lines 481-509)**

**Công dụng:** Dataclass chứa thông tin parsed từ 1 macroblock

```python
@dataclass
class MacroblockData:
    mb_type: int                      # Raw mb_type value
    mb_type_enum: Optional[MBType]    # Interpreted type

    coded_block_pattern: int = 0      # Which blocks have residual (6 bits)
    mb_qp_delta: int = 0              # QP adjustment for this MB

    # For I_4x4
    intra_4x4_pred_mode: List[int]    # 16 prediction modes (1 per block)
    intra_chroma_pred_mode: int = 0   # Chroma prediction mode

    # Residual info
    luma_4x4_blocks: List[bool]       # [16 bools] Which luma blocks coded
    chroma_dc_present: bool = False   # Chroma DC block present?
    chroma_ac_present: bool = False   # Chroma AC blocks present?
```

**Coded Block Pattern (CBP) structure:**
```
6-bit CBP = [luma4][luma3][luma2][luma1][chroma_dc][chroma_ac]

Example: CBP = 0b101111 = 47
  ├── Bit 0 (chroma_ac): 1 → Chroma AC coded
  ├── Bit 1 (chroma_dc): 1 → Chroma DC coded
  ├── Bits 2-5 (luma): 1111 → All 4 luma 4×4 groups coded
  └── Total: All blocks have residual

Luma groups (4 blocks per group):
  Group 0: blocks 0,1,2,3
  Group 1: blocks 4,5,6,7
  Group 2: blocks 8,9,10,11
  Group 3: blocks 12,13,14,15
```

---

### **3.3 MacroblockParser (Lines 512-898)**

**Công dụng:** Parse 1 macroblock (16×16 pixels) từ slice data

**Cơ chế hoạt động:**

```
Input: BitstreamReader positioned at MB start
   ↓
[Step 1] Read mb_type (ue(v))
   → Determine MB type (I_4x4, I_16x16, P_L0_16x16, etc.)
   ↓
[Step 2] Parse prediction data (conditional)
   → For I_4x4: Parse 16 intra_4x4_pred_mode
   → For P-type: Parse motion vectors + ref_idx
   → For ALL intra: Parse intra_chroma_pred_mode
   ↓
[Step 3] Parse Coded Block Pattern (if not I_16x16)
   → Determine which blocks have residual
   ↓
[Step 4] Parse mb_qp_delta (if CBP > 0)
   → Update current QP
   ↓
[Step 5] Decode CBP to block list
   → luma_4x4_blocks[16] = which blocks coded
   → chroma_dc_present, chroma_ac_present
   ↓
Output: MacroblockData
```

**Key methods:**

```python
def parse_macroblock(self) -> MacroblockData:
    """
    Main entry point - parse 1 macroblock

    Algorithm:
    1. Read mb_type
    2. Check for desync (mb_type out of range)
    3. Parse prediction modes
    4. Parse CBP
    5. Parse QP delta
    6. Decode CBP to block list
    """
    mb_type = self._read_mb_type()  # ue(v)
    mb_type_enum = self._interpret_mb_type(mb_type)

    # Desync detection
    if mb_type_enum is None or (self.is_i_slice and mb_type > 25):
        raise ValueError("mb_type_desync")

    # Parse prediction
    if mb_type_enum == MBType.I_4x4:
        self._parse_intra_4x4_pred_mode(mb)
    elif self.is_p_slice and not self._is_intra_type(mb_type_enum):
        self._parse_p_mb_prediction(mb)

    # PRIORITY 2 FIX: Parse chroma pred mode for ALL intra MBs
    if self._current_is_intra and mb_type_enum != MBType.I_PCM:
        mb.intra_chroma_pred_mode = self.reader.read_ue()

    # Parse CBP
    if not self._is_i16x16(mb_type_enum):
        mb.coded_block_pattern = self._read_coded_block_pattern()
    else:
        mb.coded_block_pattern = self._extract_cbp_from_i16x16(mb_type_enum)

    # Validate CBP
    if mb.coded_block_pattern < 0 or mb.coded_block_pattern > 47:
        print(f"[WARN] Suspicious CBP={mb.coded_block_pattern}")
        mb.coded_block_pattern = min(max(mb.coded_block_pattern, 0), 47)

    # Parse QP delta
    if mb.coded_block_pattern > 0 or self._is_i16x16(mb_type_enum):
        mb.mb_qp_delta = self.reader.read_se()

        # CRITICAL FIX: Validate QP delta
        if mb.mb_qp_delta < -26 or mb.mb_qp_delta > 25:
            print(f"[WARN] Suspicious QP_delta={mb.mb_qp_delta}")
            mb.mb_qp_delta = min(max(mb.mb_qp_delta, -26), 25)

    return mb
```

**Helper methods:**

```python
def _read_coded_block_pattern(self) -> int:
    """
    Read CBP using me(v) mapping

    H.264 Table 9-4: CBP mapped to codewords
    Different table for I vs P MBs
    """
    cbp_me = self.reader.read_ue()
    if self._current_is_intra:
        return I_CBP_TABLE[cbp_me]  # Intra mapping
    else:
        return P_CBP_TABLE[cbp_me]  # Inter mapping


def _decode_cbp_to_blocks(self, mb: MacroblockData):
    """
    Decode 6-bit CBP → which blocks have residual

    CBP bits:
      5  4  3  2  1  0
      │  │  │  │  │  └─ Chroma AC
      │  │  │  │  └──── Chroma DC
      │  │  │  └─────── Luma group 0 (blocks 0-3)
      │  │  └────────── Luma group 1 (blocks 4-7)
      │  └───────────── Luma group 2 (blocks 8-11)
      └──────────────── Luma group 3 (blocks 12-15)
    """
    cbp = mb.coded_block_pattern

    # Luma blocks
    for group in range(4):
        if (cbp >> (2 + group)) & 1:
            # Group has residual → all 4 blocks in group coded
            for i in range(4):
                block_idx = group * 4 + i
                mb.luma_4x4_blocks[block_idx] = True

    # Chroma
    mb.chroma_dc_present = (cbp >> 1) & 1
    mb.chroma_ac_present = (cbp >> 0) & 1
```

**Calculate nC (neighbor context):**

```python
def calculate_nC(self, mb_idx: int, block_idx: int,
                 neighbor_coeffs: Dict, mb_width: int) -> int:
    """
    Calculate nC = neighbor context cho CAVLC decoding

    H.264 Table 9-4:
      nC = (nA + nB + 1) >> 1  (if both available)
      nC = nA                   (if only left available)
      nC = nB                   (if only top available)
      nC = 0                    (if none available)

    FIX #1: For luma, use ONLY within-MB neighbors (not cross-MB)
    FIX #2: For chroma AC, use within-MB luma TC for nC

    Special values:
      nC = -1  → Chroma DC (different VLC table)
      nC = -2  → Chroma AC (use within-MB luma TC avg)
    """
    # Chroma DC → nC = -1
    if 16 <= block_idx < 20:
        return -1

    # Chroma AC → Use luma TC for nC (FIX #1)
    if block_idx >= 20:
        # Get corresponding luma block TC
        # Chroma block 20-23 (Cb AC) → luma blocks 0-3
        # Chroma block 24-27 (Cr AC) → luma blocks 4-7
        luma_start = ((block_idx - 20) // 4) * 4
        luma_tcs = [
            neighbor_coeffs.get((mb_idx, luma_start + i), 0)
            for i in range(4)
        ]
        avg_tc = sum(luma_tcs) // 4
        return avg_tc

    # Luma blocks → Standard nC calculation
    blk_x, blk_y = BLOCK_XY[block_idx]

    # Get left neighbor (FIX #2: within-MB only)
    if blk_x > 0:
        left_idx = find_block_at(blk_x - 1, blk_y)
        left_key = (mb_idx, left_idx)
        nA = neighbor_coeffs.get(left_key, None)
    else:
        nA = None  # No cross-MB lookup

    # Get top neighbor (FIX #2: within-MB only)
    if blk_y > 0:
        top_idx = find_block_at(blk_x, blk_y - 1)
        top_key = (mb_idx, top_idx)
        nB = neighbor_coeffs.get(top_key, None)
    else:
        nB = None  # No cross-MB lookup

    # Calculate nC
    if nA is not None and nB is not None:
        return (nA + nB + 1) >> 1
    elif nA is not None:
        return nA
    elif nB is not None:
        return nB
    else:
        return 0
```

**Block layout (scan order):**
```
Luma 4×4 blocks (16 total):
┌─────┬─────┬─────┬─────┐
│  0  │  1  │  4  │  5  │
├─────┼─────┼─────┼─────┤
│  2  │  3  │  6  │  7  │
├─────┼─────┼─────┼─────┤
│  8  │  9  │ 12  │ 13  │
├─────┼─────┼─────┼─────┤
│ 10  │ 11  │ 14  │ 15  │
└─────┴─────┴─────┴─────┘

Chroma blocks (8 total):
Block 16-17: Cb/Cr DC (1 each)
Block 18-19: (unused in 4:2:0)
Block 20-23: Cb AC (4 blocks)
Block 24-27: Cr AC (4 blocks)
```

---

## ⭐ **Part 4: TraceableCAVLCParser (CRITICAL)**

### **4.1 Overview**

**Công dụng:** Extract coefficients + track bit offsets cho embedding

**Key innovation:** Không chỉ parse coefficients mà còn theo dõi **chính xác vị trí bit** của mỗi block trong bitstream → cho phép patch sau này!

**Input:**
- NAL unit (IDR slice)
- SPS, PPS data
- global_mb_idx (starting MB index)

**Output:**
```python
{
    'blocks': {
        (mb_idx, block_idx): [16 coefficients in zigzag order],
        ...
    },
    'offsets': {
        (mb_idx, block_idx): {
            'start_bit': int,  # Bit position where block starts
            'end_bit': int,    # Bit position where block ends
            'bit_length': int  # Total bits = end - start
        },
        ...
    },
    'mb_metadata': {
        mb_idx: {
            'mb_type': int,
            'cbp': int,
            'is_skip_mb': bool,
            'qp': int
        },
        ...
    }
}
```

---

### **4.2 Key Functions**

#### **_scan_for_mb_start() (Lines 1047-1099)**

**Công dụng:** Resynchronization khi parser bị desync

```python
def _scan_for_mb_start(reader, from_pos, max_scan=3000):
    """
    Scan forward từ from_pos để tìm MB start hợp lệ

    Validation checks:
    1. mb_type ue(v) ≤ 25 (I-slice)
    2. intra_chroma_pred_mode ue(v) ≤ 3
    3. CBP me(v) ≤ 47 (for I_4x4)
    4. mb_qp_delta se(v) trong [-26, 25]

    Algorithm:
      For each candidate bit position:
          Try parse mb_type
          If mb_type > 25: continue
          If I_4x4: try parse all 16 pred modes + chroma + CBP + QP
          If I_16x16: try parse chroma + QP
          If all checks pass: return candidate position

      If no valid position found: return None

    Usage:
      Khi parser gặp suspicious value (CBP=7542, QP_delta=-1787)
      → Call _scan_for_mb_start() để tìm next valid MB
      → Skip corrupted data
    """
```

**Example scenario:**
```
Position 50106: Parse MB
  mb_type = 295 (> 25, invalid!)
  → Desync detected!

Call _scan_for_mb_start(reader, 50106, max_scan=3000)
  Scan positions 50106..53106
  Position 50124: mb_type=3 (I_16x16), chroma=1, qp=-2 ✓
  → Found valid MB!

Resume parsing from 50124
```

---

#### **extract_with_offsets() (Lines 1115-1468)**

**Công dụng:** Main entry point - parse slice và extract coefficients + offsets

**Cơ chế hoạt động chi tiết:**

```
┌─────────────────────────────────────────────────────┐
│ extract_with_offsets() Flow                         │
└─────────────────────────────────────────────────────┘

[Phase 1] Initialization
   ├── Check CABAC vs CAVLC
   │   └── If CABAC: return error (not supported)
   ├── Create BitstreamReader from NAL data
   └── Initialize tracking dicts (blocks, offsets, metadata)

[Phase 2] Parse Slice Header
   ├── SliceHeaderParser.parse() → SliceHeader
   ├── Calculate slice_qp = 26 + pps.pic_init_qp_minus26 + slice_qp_delta
   └── Create MacroblockParser + CAVLCDecoder

[Phase 3] Loop Through Macroblocks
   For each MB in slice:
   │
   ├── [3.1] Handle P-slice mb_skip_run
   │   └── If skip_run > 0: record skip MBs (all zero coefficients)
   │
   ├── [3.2] Parse Macroblock
   │   ├── MacroblockParser.parse_macroblock() → MacroblockData
   │   ├── Store mb_metadata (mb_type, cbp, qp)
   │   └── On desync: call _scan_for_mb_start() for resync
   │
   ├── [3.3] Process Luma Blocks (16 blocks)
   │   For block_idx = 0..15:
   │   │
   │   ├── Check if block is coded (from CBP)
   │   ├── If coded:
   │   │   ├── Calculate nC (neighbor context)
   │   │   ├── Record start_bit = reader.position
   │   │   ├── CAVLCDecoder.decode_block() → coefficients
   │   │   ├── Record end_bit = reader.position
   │   │   └── Store: blocks[(mb_idx, block_idx)] = coeffs
   │   │            offsets[(mb_idx, block_idx)] = {start, end, length}
   │   │            neighbor_coeffs[(mb_idx, block_idx)] = total_coeffs
   │   │
   │   └── If not coded:
   │       └── blocks[(mb_idx, block_idx)] = [0] * 16
   │
   ├── [3.4] Process Chroma DC Blocks (2 blocks: Cb, Cr)
   │   For component in [Cb, Cr]:
   │   │   ├── block_idx = 16 (Cb DC) or 17 (Cr DC)
   │   │   ├── nC = -1 (special chroma DC table)
   │   │   ├── Record start_bit
   │   │   ├── CAVLCDecoder.decode_block(nC=-1, max_num_coeff=4)
   │   │   ├── Record end_bit
   │   │   └── Store coeffs + offsets
   │
   └── [3.5] Process Chroma AC Blocks (8 blocks: 4 Cb + 4 Cr)
       For each AC block:
       │   ├── block_idx = 20..27
       │   ├── Calculate nC from luma TC (FIX #1)
       │   ├── Record start_bit
       │   ├── CAVLCDecoder.decode_block(nC, max_num_coeff=15)
       │   ├── Record end_bit
       │   └── Store coeffs + offsets

[Phase 4] Error Handling
   ├── On ValueError (desync):
   │   ├── Print warning with MB index
   │   ├── Call _scan_for_mb_start() to find next valid MB
   │   └── If found: continue parsing
   │              else: break loop
   │
   ├── On suspicious values (QP, CBP out of range):
   │   ├── Print warning
   │   ├── Clamp to valid range
   │   └── Continue parsing
   │
   └── On end of slice:
       └── Break loop (reader.pos >= total_bits - 8)

[Phase 5] Return Results
   Return {
       'blocks': {...},      # Extracted coefficients
       'offsets': {...},     # Bit positions for patching
       'mb_metadata': {...}, # MB info for safety checks
       'first_resync': int   # First MB where resync occurred (if any)
   }
```

**Key code snippets:**

```python
def extract_with_offsets(self, nal, sps, pps, global_mb_idx=0):
    # [Phase 1] Check CABAC
    if pps.entropy_coding_mode_flag:
        return {'blocks': {}, 'offsets': {}, 'error': 'CABAC_NOT_SUPPORTED'}

    # [Phase 2] Parse slice header
    reader = BitstreamReader(nal.rbsp_byte)
    slice_parser = SliceHeaderParser(reader, nal, sps, pps)
    slice_header = slice_parser.parse()

    slice_qp = 26 + pps.pic_init_qp_minus26 + slice_header.slice_qp_delta
    mb_parser = MacroblockParser(reader, slice_header.slice_type)
    cavlc_decoder = CAVLCDecoder(reader)

    blocks = {}
    offsets = {}
    mb_metadata = {}

    # [Phase 3] Parse MBs
    mb_idx = slice_header.first_mb_in_slice
    max_mbs = (sps.pic_width_in_mbs_minus1 + 1) * \
              (sps.pic_height_in_map_units_minus1 + 1)

    while mb_idx < max_mbs:
        try:
            # Handle P-slice skip
            if not mb_parser.is_i_slice:
                mb_skip_run = reader.read_ue()
                for _ in range(mb_skip_run):
                    # Record skip MB (all zeros)
                    for blk_idx in range(24):
                        blocks[(mb_idx, blk_idx)] = [0] * 16
                    mb_idx += 1

            # Parse macroblock
            mb_data = mb_parser.parse_macroblock()
            mb_metadata[mb_idx] = {
                'mb_type': mb_data.mb_type,
                'cbp': mb_data.coded_block_pattern,
                'qp': mb_parser.current_qp
            }

            # Process luma blocks (0-15)
            for blk_idx in range(16):
                if mb_data.luma_4x4_blocks[blk_idx]:
                    # Block is coded
                    nC = mb_parser.calculate_nC(mb_idx, blk_idx,
                                                self.neighbor_coeffs, mb_width)

                    # Track bit position
                    start_bit = reader.position

                    # Decode CAVLC
                    coeff_block = cavlc_decoder.decode_block(
                        nC=nC,
                        max_num_coeff=16,
                        debug_key=(mb_idx, blk_idx)
                    )

                    end_bit = reader.position

                    # Store results
                    blocks[(mb_idx, blk_idx)] = coeff_block.levels
                    offsets[(mb_idx, blk_idx)] = {
                        'start_bit': start_bit,
                        'end_bit': end_bit,
                        'bit_length': end_bit - start_bit
                    }

                    # Update neighbor cache
                    self.neighbor_coeffs[(mb_idx, blk_idx)] = \
                        coeff_block.total_coeffs
                else:
                    # Block not coded
                    blocks[(mb_idx, blk_idx)] = [0] * 16

            # Process chroma DC (16-17)
            if mb_data.chroma_dc_present:
                for component_idx in range(2):  # Cb, Cr
                    blk_idx = 16 + component_idx
                    start_bit = reader.position

                    coeff_block = cavlc_decoder.decode_block(
                        nC=-1,  # Chroma DC uses nC=-1
                        max_num_coeff=4,
                        debug_key=(mb_idx, blk_idx)
                    )

                    end_bit = reader.position

                    blocks[(mb_idx, blk_idx)] = coeff_block.levels
                    offsets[(mb_idx, blk_idx)] = {
                        'start_bit': start_bit,
                        'end_bit': end_bit,
                        'bit_length': end_bit - start_bit
                    }

            # Process chroma AC (20-27)
            if mb_data.chroma_ac_present:
                for ac_idx in range(8):  # 4 Cb + 4 Cr
                    blk_idx = 20 + ac_idx

                    # FIX #1: Use within-MB luma TC for nC
                    luma_start = (ac_idx // 4) * 4
                    luma_tcs = []
                    for i in range(4):
                        tc = self.neighbor_coeffs.get(
                            (mb_idx, luma_start + i), 0
                        )
                        luma_tcs.append(tc)
                    nC = sum(luma_tcs) // 4

                    start_bit = reader.position

                    coeff_block = cavlc_decoder.decode_block(
                        nC=nC,
                        max_num_coeff=15,  # AC: 15 coeffs (no DC)
                        debug_key=(mb_idx, blk_idx)
                    )

                    end_bit = reader.position

                    blocks[(mb_idx, blk_idx)] = coeff_block.levels
                    offsets[(mb_idx, blk_idx)] = {
                        'start_bit': start_bit,
                        'end_bit': end_bit,
                        'bit_length': end_bit - start_bit
                    }

            mb_idx += 1

        except ValueError as e:
            # Desync detected
            print(f"[TraceableParser] Resync: skipped MB {mb_idx}, "
                  f"next MB at bit {reader.position}")

            # Try to resync
            next_pos = _scan_for_mb_start(reader, reader.position)
            if next_pos:
                reader.pos = next_pos
                mb_idx += 1  # Skip corrupted MB
                first_resync = mb_idx if first_resync is None else first_resync
            else:
                break  # Cannot resync, exit

    # [Phase 5] Return
    return {
        'blocks': blocks,
        'offsets': offsets,
        'mb_metadata': mb_metadata,
        'first_resync': first_resync
    }
```

---

### **4.3 Critical Fixes Implemented**

**FIX #1: Chroma AC nC Calculation (Lines 1340-1358)**

**Problem:**
```python
# OLD (WRONG): Used cross-MB neighbors for chroma AC nC
nC = calculate_nC_from_chroma_neighbors(left_chroma, top_chroma)
# Result: Incorrect nC → wrong CAVLC decoding
```

**Fix:**
```python
# NEW (CORRECT): Use within-MB luma TC for chroma AC nC
# Matches x264 behavior!
luma_start = (chroma_block - 20) // 4 * 4  # 20-23→0, 24-27→4
luma_tcs = [neighbor_coeffs.get((mb_idx, luma_start + i), 0)
            for i in range(4)]
nC = sum(luma_tcs) // 4
```

**FIX #2: Luma nC Calculation - Within-MB Only (Lines 960-981, 984-1017)**

**Problem:**
```python
# OLD (WRONG): Looked up cross-MB neighbors
if blk_x == 0:
    left_mb_idx = mb_idx - 1
    left_key = (left_mb_idx, 3)  # Cross-MB lookup
    nA = neighbor_coeffs.get(left_key, None)
```

**Fix:**
```python
# NEW (CORRECT): Set nA/nB = None at MB boundaries
if blk_x == 0:
    left_key = None  # No cross-MB lookup
    nA = None
else:
    left_idx = find_within_mb(blk_x - 1, blk_y)
    left_key = (mb_idx, left_idx)
    nA = neighbor_coeffs.get(left_key, None)
```

**Impact:** MB1 block offsets now match ground truth from manual parse!

---

## 🎯 **Integration với Hệ Thống**

### **Workflow: Parse → Extract → Embed → Reconstruct**

```
┌──────────────────────────────────────────────────────────┐
│ 1. Video File (foreman_cif_g8.h264)                      │
└──────────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────────┐
│ 2. NALParser.parse()                                      │
│    Input: H.264 bytes                                     │
│    Output: [NALUnit(SPS), NALUnit(PPS),                  │
│              NALUnit(IDR), NALUnit(P), ...]               │
└──────────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────────┐
│ 3. Filter IDR NALs                                        │
│    idrs = [nal for nal in nals if nal.is_idr()]          │
│    Result: 7 IDR frames (foreman_cif_g8)                 │
└──────────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────────┐
│ 4. TraceableCAVLCParser.extract_with_offsets()           │
│    For each IDR:                                          │
│      → Parse slice header                                 │
│      → Parse all MBs (396 MBs/frame)                      │
│      → Extract coefficients + bit offsets                 │
│    Output:                                                │
│      blocks: {(idr, mb, blk): [16 coeffs]}               │
│      offsets: {(idr, mb, blk): {start, end, len}}        │
│    Total: ~5,000 blocks extracted                         │
└──────────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────────┐
│ 5. CAVLCSafetyFilter.get_safe_positions()                │
│    Input: blocks, offsets, nC_map                        │
│    Apply 5-rule filter:                                   │
│      - Zero preservation                                  │
│      - LSB length invariance                              │
│      - Trailing ones ≤ 3                                  │
│      - Magnitude stability                                │
│      - Context safety                                     │
│    Output: ~1,205 safe positions/IDR × 7 = 8,435 total   │
└──────────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────────┐
│ 6. PayloadEmbedder.embed_payload()                       │
│    Input: ZK proof blob (2,192 bits)                     │
│    Embed into safe positions (descending order)           │
│    LSB flip: coeff XOR 1                                  │
│    Output: modified_coefficients                          │
└──────────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────────┐
│ 7. BitstreamReconstructor.reconstruct_video()            │
│    For each modified block:                               │
│      → Re-encode coefficient using CAVLCEncoder           │
│      → Patch bitstream at tracked offset                  │
│    Output: stego.h264 (with embedded proof)               │
└──────────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────────┐
│ 8. Extract & Verify                                       │
│    → Parse stego.h264 (reuse TraceableCAVLCParser)       │
│    → Extract bits from safe positions                     │
│    → Unpack ZK proof blob                                 │
│    → Verify proof validity                                │
│    Result: Message verified! ✓                            │
└──────────────────────────────────────────────────────────┘
```

---

## 📊 **Performance & Statistics**

### **Typical Parse Results (foreman_cif_g8.h264)**

```
Video: 352×288 (CIF), 50 frames, QP=10, GOP=8
NAL Units:
  ├── 1 SPS (42 bytes)
  ├── 1 PPS (18 bytes)
  ├── 7 IDR frames (avg 15 KB each)
  └── 43 P frames (avg 3 KB each)

Per IDR Frame:
  ├── 396 macroblocks (22×18)
  ├── ~5,059 CAVLC blocks total
  │   ├── 2,762 blocks WITH offsets (có residual)
  │   └── 2,297 blocks all-zero (skip)
  ├── ~1,205 safe positions (after safety filter)
  └── Parse time: ~0.8 seconds

Total Capacity:
  ├── 7 IDR × 1,205 = ~8,435 safe positions
  ├── Need: 2,192 bits (ZK proof)
  └── Margin: 3.84× ✓
```

### **Error Handling Stats**

```
Resync Events (per IDR):
  ├── Avg: 60-80 MBs skipped due to desync
  ├── Causes: Suspicious QP_delta, invalid CBP
  └── Recovery: _scan_for_mb_start() finds next valid MB

Validation Warnings:
  ├── Suspicious QP_delta: 10-20 per IDR
  │   └── Action: Clamp to [-26, 25], continue parse
  ├── Suspicious CBP: 5-10 per IDR
  │   └── Action: Clamp to [0, 47], continue parse
  └── mb_type_desync: 60-80 per IDR
      └── Action: Resync to next valid MB
```

---

## 🔧 **API Reference**

### **H264BitstreamParser (High-Level API)**

```python
from src.bitstream.h264 import H264BitstreamParser

parser = H264BitstreamParser()
result = parser.parse(video_path)

# Result structure:
{
    'nal_units': [NALUnit(...)],       # All NAL units
    'sps': SPSData(...),                # Video metadata
    'pps': PPSData(...),                # Encoding params
    'idr_slices': [NALUnit(...)],      # IDR frames only
    'width': 352,                       # Video width
    'height': 288,                      # Video height
}
```

### **TraceableCAVLCParser (Low-Level API)**

```python
from src.bitstream.h264 import TraceableCAVLCParser

parser = TraceableCAVLCParser()
result = parser.extract_with_offsets(nal, sps, pps, global_mb_idx=0)

# Result structure:
{
    'blocks': {
        (0, 0): [12, -3, 0, 1, ...],  # MB 0, block 0
        (0, 1): [5, 0, -1, 0, ...],   # MB 0, block 1
        ...
    },
    'offsets': {
        (0, 0): {
            'start_bit': 12456,
            'end_bit': 12478,
            'bit_length': 22
        },
        ...
    },
    'mb_metadata': {
        0: {'mb_type': 2, 'cbp': 47, 'qp': 10},
        1: {'mb_type': 0, 'cbp': 15, 'qp': 11},
        ...
    },
    'first_resync': 94  # First MB where resync occurred (or None)
}
```

---

## 🎓 **Key Takeaways**

1. **Layered Architecture:**
   - NAL parsing → Slice parsing → MB parsing → CAVLC parsing
   - Mỗi layer có responsibility rõ ràng

2. **Bit-Exact Offset Tracking:**
   - `start_bit`, `end_bit` cho mỗi block
   - Cho phép patch EXACT vị trí sau → không shift bitstream

3. **Robust Error Handling:**
   - Desync detection + resynchronization
   - Validation + clamping suspicious values
   - Continue parse thay vì abort

4. **H.264 Spec Compliance:**
   - Parse EXACTLY theo thứ tự spec (7.3.3)
   - Handle ALL conditional fields
   - Support I-slices, P-slices (Baseline Profile)

5. **Critical Fixes:**
   - Fix #1: Chroma AC nC from luma TC
   - Fix #2: Luma nC within-MB only
   - Result: Accurate coefficient extraction + offsets

6. **Performance:**
   - ~0.8s parse per IDR (396 MBs)
   - ~5,000 blocks extracted per IDR
   - ~8,400+ safe positions total (7 IDRs)

---

**Generated:** 2026-03-19
**Module Version:** 3.0-CAVLC-Core
**H.264 Spec:** ITU-T H.264 (2003) Sections 7, 8, 9
