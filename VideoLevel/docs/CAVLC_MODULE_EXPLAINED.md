# CAVLC Module Explained: Entropy Coding for H.264 Residuals

**File:** `src/bitstream/cavlc.py` (1,827 lines)
**Purpose:** Implement CAVLC (Context-Adaptive Variable-Length Coding) encoder and decoder for H.264 residual data
**Key Classes:** `CAVLCDecoder`, `CAVLCEncoder`, `CoefficientBlock`, `BlockAnalysis`
**Reference:** ITU-T H.264 Specification Section 9.2

---

## Table of Contents

1. [CAVLC Overview](#cavlc-overview)
2. [Architecture](#architecture)
3. [VLC Tables Section](#vlc-tables-section)
4. [CAVLCDecoder Explained](#cavlcdecoder-explained)
5. [CAVLCEncoder Explained](#cavlcencoder-explained)
6. [Integration with H.264 System](#integration-with-h264-system)
7. [Steganographic Implications](#steganographic-implications)
8. [Critical Fixes](#critical-fixes)
9. [API Reference](#api-reference)
10. [Performance Characteristics](#performance-characteristics)

---

## CAVLC Overview

### What is CAVLC?

CAVLC (Context-Adaptive Variable-Length Coding) is a **lossless entropy codec** used in H.264 to compress quantized DCT coefficients. It's the alternative to CABAC (Context-Adaptive Binary Arithmetic Coding) and is mandatory to support in decoders.

**Key Properties:**
- **Context-adaptive**: VLC table selection depends on neighbor coefficient counts (nC value)
- **Variable-length**: More frequent patterns use shorter bit codes
- **Residual-specific**: Optimized for the statistical properties of quantized transformation coefficients
- **Nested structure**: Encodes multiple parameters (count, signs, values, zeros, runs) in a specific order

### Why CAVLC?

After DCT transformation and quantization, coefficients have these characteristics:
1. **Most coefficients are zero** (sparse blocks)
2. **Many ±1 values** exist (quantization granularity)
3. **Non-zeros cluster** at high frequencies (after zigzag reordering)
4. **Coefficients are signed** integers (−32 to +31 typically)

CAVLC exploits these statistics by:
- Using special encoding for the **count of non-zero coefficients**
- Fast encoding for **trailing ±1 values** (common in high frequencies)
- **Adaptive suffix length** for remaining coefficient magnitudes (switches between tables based on actual values)
- **Implicit zero runs** (not individually encoded; derived from position information)

### H.264 Zigzag Order

Before CAVLC encoding, coefficients are reordered in **zigzag scan order** (high frequency → low frequency):

```
0   1   5   6  14  15  27  28
2   4   7  13  16  26  29  42
3   8  12  17  25  30  41  43
9  11  18  24  31  40  44  53
10 19  23  32  39  45  52  54
20 22  33  38  46  51  55  60
21 34  37  47  50  56  59  61
35 36  48  49  57  58  62  63
```

**Important:** CAVLC processes coefficients **from high frequency to low frequency** (reverse zigzag order).

---

## Architecture

### Module Structure

```
cavlc.py (1,827 lines)
│
├─ CAVLC TABLES SECTION (lines 19–1017)
│  ├─ coeff_token VLC tables (NC 0-1, 2-3, 4-5, 6-7, 8+, Chroma DC)
│  ├─ level prefix/suffix encoding tables
│  ├─ total_zeros VLC tables (by total coefficient count)
│  ├─ run_before VLC tables (by remaining zeros)
│  └─ Lookup/reversal functions
│
├─ CAVLC DECODER SECTION (lines 1019–1403)
│  ├─ CoefficientBlock (dataclass)
│  ├─ CAVLCDecoder class
│  │  ├─ decode_block_cavlc()         [Main entry point]
│  │  ├─ _decode_coeff_token()        [Step 1]
│  │  ├─ _decode_levels()             [Step 3]
│  │  ├─ _decode_total_zeros()        [Step 4]
│  │  ├─ _decode_runs()               [Step 5]
│  │  └─ _reconstruct_coefficients()  [Step 6]
│  └─ Helper functions
│
├─ CAVLC ENCODER SECTION (lines 1405–1820)
│  ├─ BlockAnalysis (dataclass)
│  ├─ CAVLCEncoder class
│  │  ├─ encode_block_cavlc()         [Main entry point]
│  │  ├─ _analyze_block()             [Analysis phase]
│  │  ├─ _encode_levels()             [Levels encoding]
│  │  └─ _encode_run_before()         [run_before encoding]
│  └─ VLC code lookup functions
│
└─ UTILITY FUNCTIONS (throughout)
   ├─ get_coeff_token_table(nC)
   ├─ decode_vlc()
   ├─ find_coeff_token_code()
   └─ Table reversal/lookup functions
```

### Data Flow

#### Parsing (Decoder)

```
H.264 Bitstream
    ↓
[coeff_token VLC] → Extract total_coeffs, trailing_ones
    ↓
[trailing_sign bits] → 1 bit per trailing ±1 (signs of last coefficients)
    ↓
[level values] → Adaptive VLC: magnitudes of remaining non-zero coefficients
    ↓
[total_zeros VLC] → Count zeros before last non-zero (if not all 16/15 filled)
    ↓
[run_before VLC] → Position zeros between non-zero coefficients (loop per coeff)
    ↓
CoefficientBlock (16 or 15 values with zeros in correct positions)
```

#### Encoding (Encoder)

```
Coefficients (quantized DCT, may include modifications)
    ↓
[Analyze block] → Count non-zeros, trailing ±1s, measure gaps
    ↓
[Encode coeff_token] → VLC code for (total_coeffs, trailing_ones)
    ↓
[Encode trailing signs] → 1 bit per trailing ±1
    ↓
[Encode levels] → Adaptive VLC for coefficient magnitudes
    ↓
[Encode total_zeros] → VLC code for zero count
    ↓
[Encode run_before] → VLC codes for zero runs (one per non-trailing coefficient)
    ↓
H.264 Bitstream (variable length, length-preserving modifications possible)
```

---

## VLC Tables Section

### Overview

Lines 19–1017 contain **lookup tables for all CAVLC variable-length codes**. These are derived from ITU-T H.264 Tables 9-5 to 9-10.

### coeff_token Tables (Most Important)

**What it encodes:**
- `TotalCoeff (TC)`: Count of non-zero coefficients (0–16)
- `TrailingOnes (T1)`: Count of trailing ±1 values (0–3)

**Context:**
- `nC`: Predicted coefficient count from neighboring blocks (−2 to 7+)

#### Table Variants by nC Range

| nC Range | Table | Code Length | Purpose |
|----------|-------|-------------|---------|
| 0–1 | `COEFF_TOKEN_NC_0_1` | 1–16 bits | Lowest neighbor context (few neighbors have non-zeros) |
| 2–3 | `COEFF_TOKEN_NC_2_3` | 2–16 bits | Medium neighbor context |
| 4–5 | `COEFF_TOKEN_NC_4_5` | 4–16 bits | Higher neighbor context |
| 6–7 | `COEFF_TOKEN_NC_6_7` | 6–16 bits | High neighbor context |
| ≥8 | FLC (Fixed 6-bit) | 6 bits | Tabletop: `(T1 << 4) \| TC` |
| −1 | `COEFF_TOKEN_CHROMA_DC` | 2–8 bits | Special for chroma DC coefficients |
| −2 | `COEFF_TOKEN_CHROMA_DC_ER` | 3–4 bits | Error recovery chroma DC |

**Key Insight:** Lower nC → longer codes (because low context = unpredictable). Higher nC → shorter codes.

```python
# Example: nC=0, TC=2, T1=0
# COEFF_TOKEN_NC_0_1 maps '00000111' → (2, 0)
# So encoder writes 8 bits: 00000111

# Example: nC=4, TC=2, T1=0
# COEFF_TOKEN_NC_4_5 maps '001001' → (2, 0)
# So encoder writes 6 bits: 001001
# Result: Lower nC uses 8 bits; higher nC uses 6 bits for same (TC, T1)
```

### level_prefix and levelSuffixSize Tables

**What:** Encode magnitude of non-zero coefficients after trailing ±1s.

**Key Table:** H.264 Section 9.2.2.1 Table 9-6

**Structure:**
- **levelCode** = magnitude × 2 + sign bit (or magnitude × 2 + sign with special case for T1==3)
- **levelPrefix** → Encodes high bits (unary: `1 1 1 ... 1 0`)
- **levelSuffix** → Context-adaptive suffix bits

**suffixLength** adapts based on:
1. **Initial**: `suffixLength = (TC > 10) ? 1 : 0`; if TC > 3 AND T1 == 3, increment
2. **Per level**: After encoding each coefficient, if `|level| > 3 × (1 << (suffixLength − 1))`, increment `suffixLength` (up to max 6)

**Example:**
```python
# Block: [5, 0, 0, 3, 0, 0, 0, 0, ...]
# TC=2, T1=0 (no ±1s) → suffixLength = 0 initially
#
# Level[0] = 5: levelCode = (5 - 1) * 2 + 0 = 8
#   → levelPrefix = 4 (unary: 11110), levelSuffix = 4 bits for (8 >> 0) & 0xF
#   → 5 > 3*(1<<(0-1)) is impossible (1<<(-1) undefined, but check triggers on suffix==0)
#   → suffixLength becomes 1
#
# Level[1] = 3: levelCode = (3 - 1) * 2 + 0 = 4
#   → suffixLength = 1: levelPrefix = (4 >> 1) = 2, levelSuffix = 4 & 1 = 0
```

### total_zeros Tables

**What:** Encodes count of zero-valued coefficients **before the last non-zero coefficient** in zigzag order.

**Context:** Total coefficient count (1–15). Different table for each TC.

**Example:**
```python
# Coefficients (zigzag): [5, 0, 0, 0, 3, 0, 0, ...]
# TC = 2 (two non-zeros: 5 at pos 0, 3 at pos 4)
# Last non-zero at position 4
# Zeros before last = 3 (positions 1, 2, 3)
# total_zeros = 3
#
# Use TOTAL_ZEROS_TABLE[TC=2][total_zeros=3] to find VLC code
```

**Storage:** `TOTAL_ZEROS_TABLE[total_coeffs]` is a dict mapping bit_string → zeros_count.

### run_before Tables

**What:** Encodes count of zero-valued coefficients **before each individual non-zero coefficient**.

**Context:** Zeros remaining to encode (1–14). Different table for each `zeros_left`.

**Encoding Loop:**
```python
zeros_left = total_zeros
for each coefficient (from high freq to low freq, except last):
    run_before = count of zeros before this coefficient
    encode VLC for (run_before, zeros_left)
    zeros_left -= run_before
```

**Example:**
```python
# Coefficients: [5, 0, 0, 0, 3, 0, 0, ...]
# TC=2, total_zeros=5 (positions 1,2,3,5,6)
#
# Loop processes in REVERSE zigzag (high freq first then lower):
# Coefficient 3 (pos 4): run_before = 0 (no zeros before it in high-freq scan)
#                        zeros_left = 5
# Coefficient 5 (pos 0): run_before = 3 (zeros at pos 1,2,3 before it)
#                        zeros_left = 5 - 0 = 5 (updated for this coeff)
```

### Lookup/Reversal Functions

**Key Functions:**
- `get_coeff_token_table(nC)` → Returns forward table for coeff_token given nC
- `build_reverse_coeff_token_table(nC)` → Reverses table for encoding (key = (TC, T1), value = bit_string)
- `find_coeff_token_code(TC, T1, nC)` → Direct lookup for encoder (with FLC fallback)
- `find_total_zeros_code(total_zeros, TC)` → Lookup total_zeros VLC
- `find_run_before_code(run, zeros_left)` → Lookup run_before VLC

**Design Pattern:**
```python
# Decoder: Forward table
# Input: bit_string read from stream
# Output: (TC, T1) or (zeros) or (run)
table_forward = get_coeff_token_table(nC)
for bit_string, (tc, t1) in table_forward.items():
    if bitstream_starts_with(bit_string):
        return (tc, t1)

# Encoder: Reverse table
# Input: (TC, T1)
# Output: bit_string to write
table_reverse = build_reverse_coeff_token_table(nC)
bit_string = table_reverse[(tc, t1)]
write(bit_string)
```

---

## CAVLCDecoder Explained

### Class Overview

```python
class CAVLCDecoder:
    """Decode CAVLC-encoded residual data"""

    def __init__(self, reader: BitstreamReader):
        self.reader = reader

    def decode_block_cavlc(self, nC, max_num_coeff=16, debug_key=None)
        → CoefficientBlock
```

### Main Decoding Function: `decode_block_cavlc()`

**Six-step CAVLC decoding process** (ITU-T H.264 Section 9.2.1):

#### Step 1: Decode coeff_token (Total Coefficients + Trailing Ones)

```python
def _decode_coeff_token(self, nC: int) -> Tuple[int, int]:
    """Returns (total_coeffs, trailing_ones)"""
```

**Algorithm:**
1. Get VLC table for nC (`COEFF_TOKEN_NC_X_Y` or FLC6)
2. Read bits from stream and match against table
3. Extract (TC, T1) from matched code
4. Return values or raise error

**Error Recovery:**
- If primary table fails, try **fallback table** (nC±1 nearby value)
- This handles nC mismatches from upstream decode errors
- Prevents complete bitstream desync (prioritizes robustness over accuracy)

**Special Cases:**
- `nC >= 8`: Use FLC (Fixed 6-bit) encoding: `code = (TC << 2) | T1`
- `nC == -1` (DC chroma): Use special `COEFF_TOKEN_CHROMA_DC` table
- `TC > max_num_coeff`: Raise error (bitstream corruption)

**Output:**
- `total_coeffs`: 0–16 (or 0–15 for chroma DC)
- `trailing_ones`: 0–3

#### Step 2: Decode Trailing Ones Signs

```python
trailing_signs = []
for _ in range(trailing_ones):
    sign_bit = reader.read_bits(1)
    trailing_signs.append(-1 if sign_bit else +1)
```

**Logic:**
- One bit per trailing ±1 (0 = positive, 1 = negative)
- Signs are read **in the order they appear in bitstream** (high freq → low freq)

**Example:**
```python
# trailing_ones = 2
# Bits in stream: 0 1 ...
# trailing_signs = [+1, -1]
# (At reconstruction: becomes last two coefficients: ±1, ∓1 in reverse)
```

#### Step 3: Decode Remaining Coefficient Levels

```python
def _decode_levels(self, levels_remaining: int,
                   trailing_ones: int,
                   total_coeffs: int) -> List[int]:
    """Decode non-trailing coefficient magnitudes with adaptive suffix"""
```

**Algorithm:**
1. Initialize `suffixLength`:
   - `suffixLength = 0` if `TC <= 10` else `1`
   - If `TC > 3` AND `T1 == 3`, increment `suffixLength`

2. **For each of the `TC - T1` remaining levels:**
   - Read `levelPrefix` (unary: `1 1 1 ... 1 0`)
   - Read `levelSuffix` (adaptive bits based on `suffixLength`)
   - Reconstruct magnitude from prefix + suffix
   - **Update `suffixLength`** if coefficient exceeds threshold

**Unary Decoding:**
```python
# levelPrefix is unary-coded: count leading 1s before first 0
# bits: 0           → prefix = 0
# bits: 10          → prefix = 1
# bits: 110         → prefix = 2
# bits: 1110        → prefix = 3
#       ...
# bits: 111111110   → prefix = 8
```

**Level Reconstruction from Prefix + Suffix:**
```python
# suffixLength = 0:
#   if levelPrefix < 14:
#       levelCode = levelPrefix
#   elif levelPrefix == 14:
#       levelCode = 14 + (4-bit suffix)
#   else: (levelPrefix >= 15)
#       levelCode = 30 + (12-bit suffix) + extended bits
#
# suffixLength = 1 or higher:
#   levelCode = (levelPrefix << suffixLength) + levelSuffix
#   ... (with special cases for escape codes)
```

**Sign Extraction:**
```python
# Sign is embedded in levelCode for first level:
# If (trailing_ones == 3):
#     magnitude = (levelCode >> 1) + 2
#     sign = levelCode & 1
# Else:
#     magnitude = (levelCode >> 1) + 1
#     sign = levelCode & 1
```

**suffixLength Adaptation (Per-Level):**
```python
# TWO separate conditions (not if/elif!):
#
# Condition 1: After first non-trailing level
if i == 0 and suffixLength == 0:
    suffixLength = 1
#
# Condition 2: If magnitude exceeds threshold
if abs(magnitude) > (3 << (suffixLength - 1)) and suffixLength < 6:
    suffixLength += 1
```

**Critical:** Both conditions must be checked independently. Using `elif` would skip condition 2 when condition 1 is true, causing divergence from spec (and from FFmpeg).

#### Step 4: Decode Total Zeros

```python
def _decode_total_zeros(self, total_coeffs: int,
                       max_num_coeff: int,
                       is_chroma_dc: bool = False) -> int:
    """Decode count of zeros before last non-zero coefficient"""
```

**Algorithm:**
1. If `TC == max_num_coeff`, skip (all positions filled, zero zeros implicitly)
2. Select VLC table based on `TC` and special handling for chroma DC
3. Read VLC bits and return zeros count (0 to `max_num_coeff - TC`)

**Example:**
```python
# max_num_coeff = 16, TC = 2
# Can have 0 to 14 zeros before last non-zero
# Use TOTAL_ZEROS_TABLE[2] (dict keyed by bit_string)
# Example: '01' → 5 zeros
```

#### Step 5: Decode run_before Values

```python
def _decode_runs(self, total_coeffs: int, total_zeros: int) -> List[int]:
    """Decode zero runs before each coefficient"""
```

**Algorithm:**
1. Initialize `zeros_left = total_zeros`
2. **For each of the `TC - 1` coefficients** (exclude last which is implicit):
   ```python
   zeros_left = total_zeros
   for coeff_index in range(total_coeffs - 1):
       # Select table for current zeros_left value
       run_before = decode_vlc(RUN_BEFORE_TABLE[zeros_left])
       zeros_left -= run_before
       if zeros_left == 0:
           break  # Remaining implicitly zero
   ```

**Example:**
```python
# TC=3, total_zeros=5
#
# Coefficient 0 (high freq): zeros_left=5
#   Read: '10' → run=1
#   zeros_left = 5 - 1 = 4
# Coefficient 1: zeros_left=4
#   Read: '11' → run=2
#   zeros_left = 4 - 2 = 2
# Coefficient 2 (last): implicit (no run_before encoded)
#   run = zeros_left = 2 (remaining zeros)
```

**Decoder Stops Early:** When `zeros_left == 0`, decoder stops reading `run_before` codes (remaining implicitly 0).

#### Step 6: Reconstruct Coefficient Array

```python
def _reconstruct_coefficients(self, all_levels: List[int],
                              runs: List[int],
                              max_num_coeff: int) -> List[int]:
    """Place coefficients and zeros in correct zigzag positions"""
```

**Algorithm:**
1. Output array: 16 or 15 zeros
2. **Place coefficients from high frequency to low frequency** (reverse zigzag iteration):
   ```python
   output_pos = max_num_coeff - 1
   for level, run in zip(levels, runs):
       output_pos -= run            # Skip zeros
       output[output_pos] = level   # Place coefficient
       output_pos -= 1              # Move to next position
   ```

**Example:**
```python
# levels = [3, 5], runs = [0, 3]
# max_num_coeff = 16, output_pos starts at 15
#
# Iteration 0: level=3, run=0
#   output_pos -= 0 → 15
#   output[15] = 3
#   output_pos -= 1 → 14
#
# Iteration 1: level=5, run=3
#   output_pos -= 3 → 11
#   output[11] = 5
#   output_pos -= 1 → 10
#
# Result: [0,0,0,0,0,0,0,0,0,0, 5,0,0,0,0, 3]
#         (positions: 10,15 contain coefficients)
```

**Order Handling:**
```python
# Decoder processes coefficients from high frequency (reverse zigzag)
# But reconstruction needs to place them correctly in zigzag order
#
# Solution: Decode collects levels/runs in REVERSE zigzag order
# Then reconstruction places them back in FORWARD zigzag order
# (by iterating backwards through output array)
```

### CoefficientBlock Dataclass

```python
@dataclass
class CoefficientBlock:
    levels: List[int]       # All 16 (or 15) coefficient values
    total_coeffs: int       # Count of non-zeros
    trailing_ones: int      # Count of trailing ±1s
    total_zeros: int        # Zeros before last non-zero
```

**Purpose:** Encapsulates decoder output with metadata for downstream processing (safety filter, patcher).

---

## CAVLCEncoder Explained

### Class Overview

```python
class CAVLCEncoder:
    """Encode quantized coefficients using CAVLC"""

    def __init__(self, writer: BitstreamWriter):
        self.writer = writer

    def encode_block_cavlc(self, coeffs: List[int], nC: int,
                          max_num_coeff: int = 16,
                          override_total_coeffs: int = None,
                          override_trailing_ones: int = None)
```

### Analysis Phase: `_analyze_block()`

**Purpose:** Extract encoding parameters before writing bits.

**Key Steps:**

#### 1. Strip Trailing Zeros

```python
# CRITICAL: H.264 only encodes coefficients up to last non-zero
# Trailing zeros are IMPLICIT (not in bitstream)
last_nonzero_idx = -1
for i in range(len(coeffs) - 1, -1, -1):
    if coeffs[i] != 0:
        last_nonzero_idx = i
        break

if last_nonzero_idx == -1:
    return BlockAnalysis(total_coeffs=0, ...)  # All zeros

active_coeffs = coeffs[:last_nonzero_idx + 1]
```

**Why?** If encoder encodes trailing zeros, decoder has no way to know when to stop (no terminator). By convention, decoder stops at last non-zero.

#### 2. Extract Non-Zero Positions

```python
non_zero_indices = [i for i, c in enumerate(active_coeffs) if c != 0]
actual_total_coeffs = len(non_zero_indices)
```

#### 3. Count Trailing ±1s (From High Frequency)

```python
# Extract levels in REVERSE zigzag (high freq first)
levels = [active_coeffs[i] for i in reversed(non_zero_indices)]

# Count leading ±1s from start of levels array
trailing_ones = 0
trailing_signs = []
for level in levels:
    if abs(level) == 1 and trailing_ones < 3:
        trailing_ones += 1
        trailing_signs.append(level)
    else:
        break  # Stop at first non-±1
```

**Example:**
```python
# coeffs = [5, 0, 0, 1, 0, -1, 0, 0, ...]
# Reverse zigzag indices: [5, 4, 2, 0]
# levels = [coeffs[5], coeffs[4], coeffs[2], coeffs[0]]
#        = [-1, 0, 0, 5]
# Scan levels from start:
#   -1: |−1| == 1 → trailing_ones=1, trailing_signs=[-1]
#   0: |0| ≠ 1 → break
# Result: trailing_ones=1, trailing_signs=[-1]
```

**Important:** Trailing ones are the **closest to high frequency** (last non-zeros in scan order) that have magnitude ±1, not necessarily the last non-zeros overall.

#### 4. Apply Overrides (For Reconstruction)

```python
# override_total_coeffs: Preserve original TC for suffixLength calc
# (when re-encoding modified block)
total_coeffs_for_suffix = override_total_coeffs if override_total_coeffs else actual_total_coeffs

# override_trailing_ones: Cap at override value
# (original encoder may have encoded fewer T1s even if more exist)
if override_trailing_ones is not None:
    trailing_ones = min(override_trailing_ones, trailing_ones)
    trailing_signs = trailing_signs[:trailing_ones]
```

#### 5. Calculate Zero Runs

```python
# Build list of zero run lengths between non-zero coefficients
runs = []
prev_idx = -1
for idx in non_zero_indices:
    run = idx - prev_idx - 1  # Zeros between prev and current
    runs.append(run)
    prev_idx = idx

# Reverse to match encoding order (high freq first)
runs = list(reversed(runs))

# total_zeros = sum of all runs (zeros before last non-zero)
total_zeros = sum(runs)
```

**Example:**
```python
# active_coeffs = [5, 0, 0, 1, 0, -1, 0, ...]
# non_zero_indices = [0, 3, 5]
#
# Runs calculation:
#   idx=0: run = 0 - (-1) - 1 = 0 (no zeros before first) → runs=[0]
#   idx=3: run = 3 - 0 - 1 = 2 (zeros at 1,2) → runs=[0, 2]
#   idx=5: run = 5 - 3 - 1 = 1 (zero at 4) → runs=[0, 2, 1]
#
# Reverse: [1, 2, 0]
# total_zeros = 1 + 2 + 0 = 3
```

### BlockAnalysis Dataclass

```python
@dataclass
class BlockAnalysis:
    total_coeffs: int                  # Actual non-zero count (for coeff_token)
    total_coeffs_for_suffix: int       # For suffixLength calc (may use override)
    trailing_ones: int                 # Count of trailing ±1s
    trailing_signs: List[int]          # +1 or -1 for each trailing ±1
    levels: List[int]                  # All non-zero values (in reverse zigzag)
    total_zeros: int                   # Zeros before last non-zero
    runs: List[int]                    # Run lengths before each coefficient
```

### Encoding Phase

#### Step 1: Encode coeff_token

```python
coeff_token_code = find_coeff_token_code(
    analysis.total_coeffs,
    analysis.trailing_ones,
    nC
)
writer.write_bit_string(coeff_token_code)
```

#### Step 2: Encode Trailing Ones Signs

```python
for sign in analysis.trailing_signs:
    writer.write_bit(1 if sign < 0 else 0)
```

#### Step 3: Encode Levels (with adaptive suffix)

```python
def _encode_levels(self, analysis: BlockAnalysis):
    """Encode non-trailing coefficient magnitudes"""

    # Initialize suffixLength
    if analysis.total_coeffs_for_suffix > 10:
        suffixLength = 1
    else:
        suffixLength = 0

    if analysis.total_coeffs_for_suffix > 3 and analysis.trailing_ones == 3:
        suffixLength += 1

    # Encode each non-trailing level
    for i, level in enumerate(analysis.levels[analysis.trailing_ones:]):
        # Calculate levelCode (sign embedded)
        abs_level = abs(level)
        sign = 1 if level < 0 else 0

        if i == 0 and analysis.trailing_ones == 3:
            levelCode = (abs_level - 2) * 2 + sign
        else:
            levelCode = (abs_level - 1) * 2 + sign

        # Determine prefix and suffix based on suffixLength
        # ... (complex VLC derivation, see lines 1713–1763)

        # Write prefix (unary) and suffix (binary)
        writer.write_unary(levelPrefix)
        if levelSuffixSize > 0:
            writer.write_bits(levelSuffixSize, levelSuffix)

        # Update suffixLength (TWO SEPARATE CONDITIONS!)
        if suffixLength == 0:
            suffixLength = 1
        if abs_level > (3 << (suffixLength - 1)) and suffixLength < 6:
            suffixLength += 1
```

**Critical:** The two `if` statements for `suffixLength` update are **not `elif`**. Both must be evaluated independently:

1. First `if`: After initial level (when `suffixLength == 0`), always set to 1
2. Second `if`: If magnitude exceeds threshold, increment further

Failing to use two separate `if`s causes divergence from H.264 spec.

#### Step 4: Encode total_zeros

```python
if analysis.total_coeffs < max_num_coeff:
    total_zeros_code = find_total_zeros_code(
        analysis.total_zeros,
        analysis.total_coeffs
    )
    writer.write_bit_string(total_zeros_code)
```

#### Step 5: Encode run_before Values

```python
def _encode_run_before(self, analysis: BlockAnalysis):
    zeros_left = analysis.total_zeros

    # Encode all runs except last (which is implicit)
    for run in analysis.runs[:-1]:
        if zeros_left == 0:
            break  # No runs possible

        # Clamp run to zeros_left
        if run > zeros_left:
            run = zeros_left

        run_before_code = find_run_before_code(run, zeros_left)
        writer.write_bit_string(run_before_code)
        zeros_left -= run
```

**Key:** When `zeros_left == 0`, encoder MUST stop writing `run_before` codes. Decoder assumes remaining implicitly 0.

---

## Integration with H.264 System

### Data Flow in Complete System

#### Extraction (Parsing)

```
H.264 File
    ↓
[BitstreamParser (h264.py)]
    ├─ Identifies NAL units
    ├─ Parses slice headers
    ├─ Identifies macroblocks
    ↓
[CAVLCDecoder (cavlc.py)] ← Uses nC from:
    ├─ Decodes residual data     │  h264.MacroblockParser
    ├─ Produces CoefficientBlock │  (nC calculated from neighbor TC values)
    ↓
[CAVLCSafetyFilter (embedder.py)]
    ├─ Analyzes block for modification safety
    ├─ Identifies safe T1 positions
    ↓
[Embedding Payload]
    ├─ Selects safe positions
    ├─ Modifies coefficients (LSB flips)
    ↓
[BitstreamPatcher/CAVLCEncoder (bitstream_ops.py & cavlc.py)]
    ├─ Re-encodes modified blocks
    ├─ Patches bitstream at offset
    ↓
Modified H.264 File (with embedded payload)
```

#### Reconstruction (Patching)

```
Original H.264 File + Modifications (coefficients)
    ↓
[CAVLCEncoder.encode_block_cavlc()]
    ├─ Analyzes modified coefficients
    ├─ With override_total_coeffs (preserve original TC)
    ├─ With override_trailing_ones (preserve original T1)
    ├─ Generates variable-length CAVLC bitstream
    ↓
[BitstreamPatcher (bitstream_ops.py)]
    ├─ Calculates bit offset for this block (from h264.py metadata)
    ├─ Pads/removes bits to preserve block length
    ├─ Patches bitstream at offset
    ↓
Modified H.264 File
```

### Neighbor Context (nC) Integration

**CAVLCDecoder needs nC from h264.py:**

```python
# From h264.py MacroblockParser
nC = calculate_nC(
    left_neighbor_TC,    # TotalCoeff of left block
    top_neighbor_TC,     # TotalCoeff of top block
    is_chroma=False       # For chroma DC: nC = -1 always
)

# Pass to decoder
decoder = CAVLCDecoder(bitstream_reader)
block = decoder.decode_block_cavlc(nC=nC)
```

**nC Calculation (from h264.py):**
```python
# For luma blocks:
left_tc = neighbor_left.total_coeffs if neighbor_left else -1
top_tc = neighbor_top.total_coeffs if neighbor_top else -1

if left_tc < 0 or top_tc < 0:
    nC = (left_tc + top_tc + 1) // 2
else:
    nC = (left_tc + top_tc) // 2

# For chroma DC: always nC = -1
# For chroma AC: nC = average of luma TCs
```

### Safety Filter Integration

**CAVLCSafetyFilter (embedder.py) analyzes CoefficientBlock:**

```python
# From CAVLCSafetyFilter._detect_trailing_ones()
# Analyzes decoder output to identify T1 positions

positions = []
for mb_idx, block_idx in sorted_blocks:
    coeff_block = decoder_output[(mb_idx, block_idx)]

    # Find positions of trailing ±1s
    trailing_ones_positions = analyze_block(coeff_block.levels)

    # These are SAFE for sign flipping (CAVLC structure preserved)
    positions.extend(trailing_ones_positions)
```

---

## Steganographic Implications

### Why Trailing Ones are Embedding Targets

**Observation:** Flipping sign of a ±1 coefficient is CAVLC-safe:
- **Total Coeffs unchanged** (still non-zero)
- **Trailing Ones unchanged** (still ±1)
- **Magnitude unchanged** (still 1)
- **Bitstream length unchanged** (T1 sign is single bit; level unary+suffix doesn't change)

**Example:**
```python
# Original: [5, 0, 0, -1, 0, ...]
# Coefficient: +1 or -1 (can toggle)
#
# Original encoding:
#   coeff_token: (TC=2, T1=1) → VLC code
#   trailing_sign: 1 (for -1)
#   levels: [5] with levelCode, prefix, suffix
#   total_zeros: ...
#   run_before: ...
#
# After flipping sign to +1:
#   coeff_token: (TC=2, T1=1) → SAME VLC code!
#   trailing_sign: 0 (for +1)
#   levels: [5] SAME prefix/suffix
#   total_zeros: SAME
#   run_before: SAME
#
# Result: Only 1 bit changes in bitstream (the sign bit)!
```

### Embedding Workflow

1. **Identify T1 positions** from CAVLCSafetyFilter analysis
2. **Modulate signs** (flip bit 0 of signs array: `0 ↔ 1`)
3. **Re-encode block with override flags:**
   ```python
   encoder.encode_block_cavlc(
       coeffs=modified_coeffs,
       override_total_coeffs=original_TC,  # Preserve original TC
       override_trailing_ones=original_T1  # Preserve original T1
   )
   ```
4. **Patch bitstream** at pre-calculated offset (from h264.py metadata)

### FFmpeg Validation Requirement

**Caveat:** Sign flips of T1 are CAVLC-valid but not always **pixel-valid**.

Some T1 sign flips trigger **intra prediction errors** in FFmpeg's decoder:
- Modified pixel values don't match prediction model
- Decoder's error handler clips/zeros pixels
- Visual result: distorted regions or PSNR degradation

**Solution:** Use FFmpeg pixel validator (Fix #3 in bitstream_ops.py) to test each position individually.

---

## Critical Fixes

### Fix #4: Trailing Ones Detection Bug

**Location:** `CAVLCSafetyFilter._detect_trailing_ones()` in embedder.py

**Bug:** Original code scanned backward from last non-zero but stopped at zeros.

```python
# WRONG (original):
for i in range(last_nonzero, -1, -1):
    if coeffs[i] == 0:
        break  # ← BUG: Stops scan at first zero
    if abs(coeffs[i]) == 1:
        trailing_ones += 1
    else:
        break

# EXAMPLE: [1, 0, 0, -1, 0]
# Scan backward from last nonzero (idx=3):
#   idx=3: abs(-1)==1 → trailing_ones=1
#   idx=2: coeff==0 → BREAK (before reaching idx=1)
# Result: Misses T1 at idx=1
```

**Fix:** Collect non-zero positions first, then count leading ±1s from high frequency:

```python
# CORRECT (fixed):
non_zero_indices = [i for i, c in enumerate(coeffs) if c != 0]
non_zero_values = [coeffs[i] for i in reversed(non_zero_indices)]

trailing_ones = 0
for val in non_zero_values:
    if abs(val) == 1:
        trailing_ones += 1
    else:
        break

# Same example: non_zero_indices=[1,3], reversed order: values=[-1, 1]
# Scan forward:
#   val=-1: abs(-1)==1 → trailing_ones=1
#   val=1: abs(1)==1 → trailing_ones=2
# Result: Correctly identifies 2 T1s
```

**Impact:** Before fix, embedder under-counted T1 positions → fewer embedding slots → lower capacity. After fix, matches encoder behavior → ~+10% more safe positions identified.

### Fix in Encoding: Two Separate `if` Conditions for suffixLength

**Location:** `_encode_levels()` method

**Issue:** Some implementations use `if/elif` for suffixLength updates:

```python
# WRONG:
if i == 0 and suffixLength == 0:
    suffixLength = 1
elif abs_level > (3 << (suffixLength - 1)) and suffixLength < 6:  # ← SKIPPED if first condition true!
    suffixLength += 1
```

**Correct (spec-compliant):**

```python
# RIGHT:
if i == 0 and suffixLength == 0:
    suffixLength = 1
if abs_level > (3 << (suffixLength - 1)) and suffixLength < 6:  # ← Always checked!
    suffixLength += 1
```

**Why:** H.264 spec (Section 9.2.2.1) specifies two **independent** conditions:

1. After first non-trailing level: set `suffixLength = 1` (if was 0)
2. After encoding any level: increment if magnitude is large

Condition 1 is a one-time initialization; condition 2 is an adaptive threshold. Both must be checked.

**Impact:** Encoder diverges from FFmpeg (which uses two `if`s). Causes bit mismatches and decoder failures.

---

## API Reference

### CAVLCDecoder

```python
class CAVLCDecoder:
    def __init__(self, reader: BitstreamReader)
        """Initialize with bitstream reader positioned at residual data"""

    def decode_block_cavlc(self, nC: int, max_num_coeff: int = 16,
                          debug_key: Tuple[int, int] = None)
        → CoefficientBlock:
        """
        Decode one 4x4 block of residual coefficients.

        Args:
            nC: Neighbor coefficient count (context for VLC table selection)
               Range: -2 to 8+ (use get_coeff_token_table() to map)
            max_num_coeff: 16 for luma, 15 for chroma DC
            debug_key: Optional (mb_idx, block_idx) for logging

        Returns:
            CoefficientBlock with decoded levels and metadata

        Raises:
            ValueError: If bitstream is corrupted or TC > max_num_coeff
        """

    def _decode_coeff_token(self, nC: int) → Tuple[int, int]:
        """Decode coeff_token VLC code. Returns (total_coeffs, trailing_ones)"""

    def _decode_levels(self, levels_remaining: int, trailing_ones: int,
                      total_coeffs: int) → List[int]:
        """Decode non-trailing coefficient magnitudes (with adaptive suffix)"""

    def _decode_total_zeros(self, total_coeffs: int, max_num_coeff: int,
                           is_chroma_dc: bool = False) → int:
        """Decode count of zeros before last non-zero coefficient"""

    def _decode_runs(self, total_coeffs: int, total_zeros: int) → List[int]:
        """Decode zero runs before each coefficient"""

    def _reconstruct_coefficients(self, all_levels: List[int], runs: List[int],
                                 max_num_coeff: int) → List[int]:
        """Place coefficients at correct zigzag positions"""
```

### CAVLCEncoder

```python
class CAVLCEncoder:
    def __init__(self, writer: BitstreamWriter):
        """Initialize with bitstream writer"""

    def encode_block_cavlc(self, coeffs: List[int], nC: int, max_num_coeff: int = 16,
                          debug_key: Tuple[int, int] = None,
                          override_total_coeffs: int = None,
                          override_trailing_ones: int = None):
        """
        Encode one block of coefficients using CAVLC.

        Args:
            coeffs: List of 16 (or 15) coefficient values in zigzag order
            nC: Neighbor coefficient count (context)
            max_num_coeff: 16 for luma, 15 for chroma DC
            debug_key: Optional (mb_idx, block_idx) for logging
            override_total_coeffs: Force TC for suffixLength calc (re-encoding)
            override_trailing_ones: Force T1 count (re-encoding)

        Notes:
            - Modifies internal writer state (bits are written)
            - Trailing zeros are NOT encoded (implicit in bitstream)
            - Use override_* flags when re-encoding modified block to preserve
              bitstream length for patching
        """

    def _analyze_block(self, coeffs: List[int], max_num_coeff: int,
                      override_total_coeffs: int = None,
                      override_trailing_ones: int = None) → BlockAnalysis:
        """Extract encoding parameters from coefficient block"""

    def _encode_levels(self, analysis: BlockAnalysis):
        """Encode non-trailing coefficient levels with adaptive suffix length"""

    def _encode_run_before(self, analysis: BlockAnalysis):
        """Encode zero runs before each coefficient"""
```

### Helper Functions

```python
def get_coeff_token_table(nC: int) → Union[dict, str]:
    """
    Get VLC table for coeff_token given nC value.

    Returns:
        - Dict mapping bit_string → (TC, T1) for nC < 8
        - 'FLC6' for nC >= 8 (use 6-bit fixed-length code)
    """

def find_coeff_token_code(total_coeffs: int, trailing_ones: int, nC: int) → str:
    """Lookup/generate VLC code for coeff_token. Returns bit string."""

def find_total_zeros_code(total_zeros: int, total_coeffs: int) → str:
    """Lookup VLC code for total_zeros. Returns bit string."""

def find_run_before_code(run_before: int, zeros_left: int) → str:
    """Lookup VLC code for run_before. Returns bit string."""

def decode_vlc(reader, table: dict, max_bits: int = 16) → Any:
    """Generic VLC decoder: reads bits until match found in table."""
```

### Dataclasses

```python
@dataclass
class CoefficientBlock:
    levels: List[int]       # All 16 (or 15) coefficients
    total_coeffs: int       # Count non-zeros
    trailing_ones: int      # Count trailing ±1s
    total_zeros: int        # Zeros before last non-zero

@dataclass
class BlockAnalysis:
    total_coeffs: int               # Non-zero count for coeff_token
    total_coeffs_for_suffix: int    # For suffixLength (may be overridden)
    trailing_ones: int              # Count trailing ±1s
    trailing_signs: List[int]       # +1 or -1 per trailing ±1
    levels: List[int]               # All non-zero values (reverse zigzag)
    total_zeros: int                # Zeros before last non-zero
    runs: List[int]                 # Zero run counts
```

---

## Performance Characteristics

### Decoding Complexity

| Component | Operations | Notes |
|-----------|------------|-------|
| coeff_token lookup | O(log N) | VLC table lookup, N = table size |
| Trailing sign bits | O(T1) | T1 ≤ 3, so O(1) |
| Level decoding | O(TC) | Unary + suffix per level |
| Zero/run decoding | O(TC) | VLC lookups per coefficient |
| **Total per block** | **O(TC log N)** | TC ≤ 16, typically TC ≈ 3–5 |

### Encoding Complexity

| Component | Operations |
|-----------|------------|
| Block analysis | O(16) = strip zeros + find non-zeros |
| coeff_token lookup | O(1) lookup in reverse table (16×4 entries) |
| Level encoding | O(TC × suffixLength) unary + binary writes |
| **Total per block** | **O(16 + TC × log(max_suffix))** |

### Typical Bitstream Sizes

| Block Type | Typical TC | Bits (w/o T1) | Bits (average) |
|-----------|-----------|---|---|
| Sparse (no T1s) | 2–3 | 10–15 bits | ~15 bits |
| T1-heavy | 4–6 | 8–12 bits + signs | ~12 bits |
| Dense | 12+ | 20–40 bits | ~30 bits |

**For a 16×16 macroblock:**
- 16 luma 4×4 blocks: ~270 bits average (16 blocks × ~17 bits/block)
- 2 chroma 2×2 DC blocks: ~5 bits total
- **Total:** ~275 bits per macroblock (~34 bytes)

### Memory Usage

```python
# CAVLCDecoder: ~5 KB (reader state + temp lists for levels/runs)
# CAVLCEncoder: ~5 KB (writer state + temp BlockAnalysis objects)
# VLC tables: ~150 KB (lookup tables loaded at module init)
```

### Optimization Opportunities

1. **Lazy table generation:** Tables are computed on-demand, not pre-allocated
2. **Bitwise operations:** Suffix/prefix encoding uses bit shifts instead of loops
3. **Reverse table caching:** Encoder could cache reverse tables (currently built per-call)
4. **Vectorization:** Multiple blocks could be decoded/encoded in parallel (future)

---

## Summary

**CAVLC Module Architecture:**

```
CAVLC.py (1,827 lines)
│
├─ VLC Tables (19–1017)
│  └─ Pre-computed code lookups for coeff_token, levels, zeros, runs
│
├─ CAVLCDecoder (1019–1403)
│  └─ Six-step parsing of bitstream → CoefficientBlock
│
├─ CAVLCEncoder (1405–1820)
│  └─ Block analysis + five-step encoding → Bitstream
│
└─ Helpers & utility functions
```

**Key Mechanisms:**

1. **VLC Table Context:** coeff_token table selected by nC value (neighbor prediction)
2. **Adaptive Suffixes:** Level encoding switches tables based on coefficient magnitudes
3. **Implicit Zeros:** Trailing zeros not encoded; decoder stops at last non-zero
4. **Run-Length Coding:** Zero positions encoded as run lengths (compact representation)
5. **Sign Embedding:** Sign bits integrated into level codes (single bit per non-trailing coefficient)

**Steganographic Use:**

- **T1 sign flips:** CAVLC-valid, single-bit modifications
- **Safety filter:** Analyzes block structure to find safe positions
- **Re-encoding:** Uses `override_total_coeffs` and `override_trailing_ones` to preserve bitstream length
- **FFmpeg validation:** Empirical testing required (some flips cause intra prediction errors)

**Critical Fixes Applied:**

- **Fix #4:** Trailing ones detection (doesn't stop at intermediate zeros)
- **Two separate `if` statements:** suffixLength update (not `elif`) for spec compliance

---

## Integration Examples

### Extraction (Example: Parsing MB 0, Block 0)

```python
from src.bitstream.h264 import H264BitstreamParser
from src.bitstream.cavlc import CAVLCDecoder

# Parse H.264 header + macroblock header
parser = H264BitstreamParser(video_file)
nal = parser.read_next_nal_unit()
slice_header = parser.read_slice_header(nal)
mb_header = parser.read_macroblock_header(nal, slice_header)

# Calculate nC from neighboring blocks
nC = mb_header.calculate_nC(mb_idx=0, block_idx=0)

# Decode luma 4×4 block
decoder = CAVLCDecoder(nal.bitstream_reader)
coeff_block = decoder.decode_block_cavlc(nC=nC, max_num_coeff=16)

# Use for safety filter
from src.embedder.embedder import CAVLCSafetyFilter
safety_filter = CAVLCSafetyFilter()
safe_positions = safety_filter.get_safe_positions(coeff_block)
```

### Reconstruction (Example: Modify & Re-encode)

```python
from src.bitstream.cavlc import CAVLCEncoder
from src.bitstream.bitstream_io import BitstreamWriter

# Modify coefficients (e.g., flip T1 sign)
modified_coeffs = coeff_block.levels.copy()
modified_coeffs[15] = -modified_coeffs[15]  # Flip last ±1

# Re-encode with overrides
writer = BitstreamWriter()
encoder = CAVLCEncoder(writer)
encoder.encode_block_cavlc(
    coeffs=modified_coeffs,
    nC=nC,
    override_total_coeffs=coeff_block.total_coeffs,
    override_trailing_ones=coeff_block.trailing_ones
)

# Patch bitstream
new_bitstring = writer.get_bits()
# (offset from h264.py metadata) → BitstreamPatcher.patch_block()
```

---

**End of CAVLC Module Explanation**
