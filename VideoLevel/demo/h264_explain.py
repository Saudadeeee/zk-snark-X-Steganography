"""Pure H.264 Baseline math used by the deep demo trace (no I/O, no FFmpeg).

Everything here re-derives, from the bitstream and the decoded neighbours, values
that the native parser and FFmpeg already produce, so the demo can show each
intermediate step and then check it against those independent implementations.
References are to ITU-T H.264 (clauses 7.3.5, 8.3.1, 8.5.6, 8.5.12, 9.1, 9.2).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Table 9-4 (intra column): coded_block_pattern for me(v) codeNum 0..47.
INTRA_CBP_FROM_CODENUM = (
    47, 31, 15, 0, 23, 27, 29, 30, 7, 11, 13, 14, 39, 43, 45, 46,
    16, 3, 5, 10, 12, 19, 21, 26, 28, 35, 37, 42, 44, 1, 2, 4,
    8, 17, 18, 20, 24, 6, 9, 22, 25, 32, 33, 34, 36, 40, 38, 41,
)
# Zig-zag scan position -> raster index in a 4x4 block (Table 8-13, frame scan).
ZIGZAG_4x4 = (0, 1, 4, 8, 5, 2, 3, 6, 9, 12, 13, 10, 7, 11, 14, 15)
INTRA4x4_MODE_NAMES = ("Vertical", "Horizontal", "DC", "Diagonal_Down_Left", "Diagonal_Down_Right",
                       "Vertical_Right", "Horizontal_Down", "Vertical_Left", "Horizontal_Up")
INTRA16x16_MODE_NAMES = ("Vertical", "Horizontal", "DC", "Plane")
CHROMA_MODE_NAMES = ("DC", "Horizontal", "Vertical", "Plane")
# normAdjust4x4 (8.5.9) for qP % 6, by coefficient parity class.
_NORM_ADJUST = ((10, 16, 13), (11, 18, 14), (13, 20, 16), (14, 23, 18), (16, 25, 20), (18, 29, 23))
# Encoder-side multiplication factors (informative, same parity classes).
_QUANT_MF = ((13107, 5243, 8066), (11916, 4660, 7490), (10082, 4194, 6554),
             (9362, 3647, 5825), (8192, 3355, 5243), (7282, 2893, 4559))
FORWARD_CORE = ((1, 1, 1, 1), (2, 1, -1, -2), (1, -1, -1, 1), (1, -2, 2, -1))

Matrix = list[list[int]]


# --------------------------------------------------------------------------- bits

@dataclass
class Field:
    """One syntax element: where it sits in the RBSP, its raw bits and its value."""
    name: str
    start: int
    bits: str
    value: object
    note: str = ""


class TracingBitReader:
    """MSB-first RBSP reader that records every syntax element it reads."""

    def __init__(self, rbsp: bytes, position: int = 0) -> None:
        self.rbsp = rbsp
        self.position = position
        self.fields: list[Field] = []

    def bit(self, offset: int) -> int:
        if offset < 0 or offset >= len(self.rbsp) * 8:
            raise ValueError(f"RBSP bit {offset} is outside the NAL")
        return (self.rbsp[offset // 8] >> (7 - offset % 8)) & 1

    def bits(self, start: int, end: int) -> str:
        return "".join(str(self.bit(i)) for i in range(start, end))

    def _record(self, name: str, start: int, value: object, note: str = "") -> object:
        self.fields.append(Field(name, start, self.bits(start, self.position), value, note))
        return value

    def u(self, count: int, name: str, note: str = "") -> int:
        start, value = self.position, 0
        for _ in range(count):
            value = (value << 1) | self.bit(self.position)
            self.position += 1
        return self._record(name, start, value, note)  # type: ignore[return-value]

    def _ue_raw(self) -> int:
        zeros = 0
        while self.bit(self.position) == 0:
            zeros += 1
            self.position += 1
            if zeros > 31:
                raise ValueError("Exp-Golomb prefix longer than 31 bits")
        self.position += 1
        suffix = 0
        for _ in range(zeros):
            suffix = (suffix << 1) | self.bit(self.position)
            self.position += 1
        return (1 << zeros) - 1 + suffix

    def ue(self, name: str, note: str = "") -> int:
        start = self.position
        return self._record(name, start, self._ue_raw(), note)  # type: ignore[return-value]

    def se(self, name: str, note: str = "") -> int:
        start = self.position
        code = self._ue_raw()
        value = (code + 1) // 2 if code % 2 else -(code // 2)
        return self._record(name, start, value, f"codeNum={code}" + (f"; {note}" if note else ""))  # type: ignore[return-value]


# ---------------------------------------------------------------- macroblock header

def parse_i_macroblock_header(reader: TracingBitReader) -> dict:
    """Parse one I-slice macroblock_layer header (7.3.5) with a field-level trace."""
    mb_type = reader.ue("mb_type", "0=I_NxN (I4x4); 1..24=I_16x16; 25=I_PCM")
    header: dict = {"mb_type": mb_type, "rem_intra4x4": [-1] * 16}
    if mb_type == 0:
        for block in range(16):
            flag = reader.u(1, f"prev_intra4x4_pred_mode_flag[{block}]", "1=dung mode du doan")
            if not flag:
                header["rem_intra4x4"][block] = reader.u(3, f"rem_intra4x4_pred_mode[{block}]")
        header["intra_chroma_pred_mode"] = reader.ue("intra_chroma_pred_mode")
        code_num_start = reader.position
        code_num = reader._ue_raw()
        cbp = INTRA_CBP_FROM_CODENUM[code_num]
        reader._record("coded_block_pattern", code_num_start, cbp,
                       f"me(v): codeNum={code_num} -> CBP={cbp} (luma={cbp & 15:04b}, chroma={cbp >> 4})")
        header["cbp"] = cbp
        if cbp:
            header["mb_qp_delta"] = reader.se("mb_qp_delta")
        else:
            header["mb_qp_delta"] = 0
    elif 1 <= mb_type <= 24:
        header["intra_chroma_pred_mode"] = reader.ue("intra_chroma_pred_mode")
        luma = 15 if mb_type >= 13 else 0
        header["cbp"] = (((mb_type - 1) // 4) % 3) << 4 | luma
        header["intra16x16_pred_mode"] = (mb_type - 1) % 4
        header["mb_qp_delta"] = reader.se("mb_qp_delta")
    else:
        raise ValueError("I_PCM / invalid mb_type is outside the supported demo profile")
    return header


# ------------------------------------------------------------------ CAVLC block

def _match_vlc(reader: TracingBitReader, table: dict, name: str) -> object:
    start, code = reader.position, ""
    while len(code) < 16:
        code += str(reader.bit(reader.position))
        reader.position += 1
        if code in table:
            return reader._record(name, start, table[code])
    raise ValueError(f"{name}: no VLC code matched at bit {start}")


def segment_cavlc_block(rbsp: bytes, block: dict, coeff_token_table: dict, max_coeff: int,
                        total_zeros_tables: dict, run_before_tables: dict) -> list[Field]:
    """Split one native-decoded residual block into its CAVLC syntax elements (9.2).

    The native parser supplies where the block starts and its nC; this function
    independently re-reads every element, so its values cross-check the native ones.
    """
    reader = TracingBitReader(rbsp, block["coeff_token_bit"])
    if coeff_token_table is None:
        # nC >= 8: Table 9-5 uses a fixed 6-bit code xxxxyy = (TotalCoeff-1, TrailingOnes); 000011 = no coefficient.
        code = reader.u(6, "coeff_token")
        total_coeff, trailing_ones = (0, 0) if code == 3 else ((code >> 2) + 1, code & 3)
        reader.fields[-1].value = (total_coeff, trailing_ones)
    else:
        total_coeff, trailing_ones = _match_vlc(reader, coeff_token_table, "coeff_token")  # type: ignore[misc]
    reader.fields[-1].note = f"(TotalCoeff, TrailingOnes) = ({total_coeff}, {trailing_ones}); nC={block['n_c']}"
    for index in range(trailing_ones):
        reader.u(1, f"trailing_ones_sign_flag[{index}]", "0 -> +1, 1 -> -1")
    suffix_length = 1 if total_coeff > 10 and trailing_ones < 3 else 0
    for index in range(total_coeff - trailing_ones):
        start = reader.position
        prefix = 0
        while reader.bit(reader.position) == 0:
            prefix += 1
            reader.position += 1
        reader.position += 1
        if prefix == 14 and suffix_length == 0:
            suffix_size = 4
        elif prefix >= 15:
            suffix_size = prefix - 3
        else:
            suffix_size = suffix_length
        suffix = 0
        for _ in range(suffix_size):
            suffix = (suffix << 1) | reader.bit(reader.position)
            reader.position += 1
        level_code = (min(15, prefix) << suffix_length) + suffix
        if prefix >= 15 and suffix_length == 0:
            level_code += 15
        if prefix >= 16:
            level_code += (1 << (prefix - 3)) - 4096
        if index == 0 and trailing_ones < 3:
            level_code += 2
        level = (level_code + 2) >> 1 if level_code % 2 == 0 else (-level_code - 1) >> 1
        reader._record(f"level[{index}]", start, level,
                       f"level_prefix={prefix}, suffixLength={suffix_length}, level_suffix={suffix} "
                       f"({suffix_size} bit), levelCode={level_code}")
        if suffix_length == 0:
            suffix_length = 1
        if abs(level) > (3 << (suffix_length - 1)) and suffix_length < 6:
            suffix_length += 1
    total_zeros = 0
    if 0 < total_coeff < max_coeff:
        total_zeros = _match_vlc(reader, total_zeros_tables[total_coeff], "total_zeros")  # type: ignore[assignment]
    zeros_left = total_zeros
    for index in range(max(0, total_coeff - 1)):
        if zeros_left <= 0:
            break
        run = _match_vlc(reader, run_before_tables[min(zeros_left, 7)], f"run_before[{index}]")
        reader.fields[-1].note = f"zerosLeft={zeros_left}"
        zeros_left -= run  # type: ignore[operator]
    if reader.position != block["end_bit"]:
        raise ValueError(f"CAVLC re-read ended at bit {reader.position}, native says {block['end_bit']}")
    return reader.fields


# --------------------------------------------------------- scan / matrices

def scan_to_matrix(scan: list[int]) -> Matrix:
    """Inverse zig-zag: 16 scan-order coefficients -> 4x4 matrix c[row][col]."""
    if len(scan) != 16:
        raise ValueError("a 4x4 luma block has 16 coefficients")
    raster = [0] * 16
    for position, value in zip(ZIGZAG_4x4, scan):
        raster[position] = value
    return [raster[row * 4:row * 4 + 4] for row in range(4)]


def _parity_class(row: int, col: int) -> int:
    if row % 2 == 0 and col % 2 == 0:
        return 0
    if row % 2 == 1 and col % 2 == 1:
        return 1
    return 2


def level_scale_matrix(qp: int) -> Matrix:
    """LevelScale4x4 for flat scaling lists (Baseline): 16 * normAdjust4x4."""
    return [[16 * _NORM_ADJUST[qp % 6][_parity_class(r, c)] for c in range(4)] for r in range(4)]


def dequantize(coefficients: Matrix, qp: int) -> Matrix:
    """8.5.12.1 scaling for a 4x4 block whose DC is not separately transformed."""
    scale = level_scale_matrix(qp)
    shift = qp // 6
    out: Matrix = []
    for r in range(4):
        row = []
        for c in range(4):
            product = coefficients[r][c] * scale[r][c]
            row.append(product << (shift - 4) if qp >= 24 else (product + (1 << (3 - shift))) >> (4 - shift))
        out.append(row)
    return out


def _inverse_1d(d: list[int]) -> list[int]:
    e0, e1 = d[0] + d[2], d[0] - d[2]
    e2, e3 = (d[1] >> 1) - d[3], d[1] + (d[3] >> 1)
    return [e0 + e3, e1 + e2, e1 - e2, e0 - e3]


def inverse_transform(scaled: Matrix) -> tuple[Matrix, Matrix, Matrix]:
    """8.5.12.2: rows, then columns, then (x + 32) >> 6. Returns (after rows, after cols, residual)."""
    rows = [_inverse_1d(list(row)) for row in scaled]
    columns_t = [_inverse_1d([rows[r][c] for r in range(4)]) for c in range(4)]
    columns = [[columns_t[c][r] for c in range(4)] for r in range(4)]
    residual = [[(value + 32) >> 6 for value in row] for row in columns]
    return rows, columns, residual


def matmul(a: Matrix | tuple, b: Matrix | tuple) -> Matrix:
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def transpose(a: Matrix | tuple) -> Matrix:
    return [[a[j][i] for j in range(4)] for i in range(4)]


def forward_transform(residual: Matrix) -> Matrix:
    """Encoder core transform W = Cf * X * Cf^T (informative, 8.5 counterpart)."""
    return matmul(matmul(FORWARD_CORE, residual), transpose(FORWARD_CORE))


def quantize_intra(transformed: Matrix, qp: int) -> Matrix:
    """Textbook intra quantizer |Z| = (|W| * MF + 2^qbits/3) >> qbits.

    x264 adds dead-zone, trellis and psy decisions, so real levels may differ;
    the demo reports how many positions agree instead of asserting equality.
    """
    qbits = 15 + qp // 6
    offset = (1 << qbits) // 3
    out: Matrix = []
    for r in range(4):
        row = []
        for c in range(4):
            magnitude = (abs(transformed[r][c]) * _QUANT_MF[qp % 6][_parity_class(r, c)] + offset) >> qbits
            row.append(magnitude if transformed[r][c] >= 0 else -magnitude)
        out.append(row)
    return out


# ------------------------------------------------------------- intra prediction

def block_xy(block_index: int) -> tuple[int, int]:
    """luma4x4BlkIdx (decode order) -> (x, y) in 4-sample units inside the MB (6.4.3)."""
    return (block_index // 4 % 2) * 2 + block_index % 2, (block_index // 8) * 2 + block_index // 2 % 2


def block_index(x: int, y: int) -> int:
    return (y // 2) * 8 + (x // 2) * 4 + (y % 2) * 2 + (x % 2)


@dataclass
class ModeDerivation:
    mode: int
    predicted: int
    left: str
    top: str
    rem: int


def derive_intra4x4_modes(macroblocks: list[dict], mb_width: int) -> dict[int, list[ModeDerivation]]:
    """8.3.1.1 for every I_NxN macroblock of a single-slice IDR picture."""
    by_address = {mb["address"]: mb for mb in macroblocks}
    modes: dict[int, list[ModeDerivation]] = {}
    for mb in sorted(macroblocks, key=lambda item: item["address"]):
        if mb["mb_type"] != 0:
            continue
        address = mb["address"]
        derived: list[ModeDerivation | None] = [None] * 16
        for blk in range(16):
            x, y = block_xy(blk)

            def neighbour(
                dx: int,
                dy: int,
                x: int = x,
                y: int = y,
                derived: list[ModeDerivation | None] = derived,
                address: int = address,
            ) -> tuple[int | None, str]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < 4 and 0 <= ny < 4:
                    return derived[block_index(nx, ny)].mode, "cung MB"  # type: ignore[union-attr]
                if nx < 0:
                    if address % mb_width == 0:
                        return None, "khong co (bien trai)"
                    other = by_address.get(address - 1)
                    nx += 4
                else:
                    if address < mb_width:
                        return None, "khong co (bien tren)"
                    other = by_address.get(address - mb_width)
                    ny += 4
                if other is None:
                    return None, "khong co"
                if other["mb_type"] != 0:
                    return 2, "MB I16x16 -> DC(2)"
                return modes[other["address"]][block_index(nx, ny)].mode, f"MB {other['address']}"

            left, left_note = neighbour(-1, 0)
            top, top_note = neighbour(0, -1)
            predicted = 2 if left is None or top is None else min(left, top)
            rem = mb["rem_intra4x4"][blk]
            mode = predicted if rem < 0 else (rem if rem < predicted else rem + 1)
            derived[blk] = ModeDerivation(mode, predicted,
                                          f"{left_note}={left}" if left is not None else left_note,
                                          f"{top_note}={top}" if top is not None else top_note, rem)
        modes[address] = derived  # type: ignore[assignment]
    return modes


@dataclass
class IntraNeighbours:
    """p[x,-1] (x=-1..7) and p[-1,y] (y=0..3) of one 4x4 block, None = unavailable."""
    top: list[int | None] = field(default_factory=list)    # index 0 -> x=-1 (corner), 1..8 -> x=0..7
    left: list[int | None] = field(default_factory=list)   # y=0..3
    notes: list[str] = field(default_factory=list)


def gather_neighbours(plane: bytes, width: int, height: int, mb_width: int,
                      address: int, blk: int) -> IntraNeighbours:
    """Collect unfiltered neighbour samples for a 4x4 luma block (8.3.1.2, 6.4.11.4)."""
    bx, by = block_xy(blk)
    mb_x, mb_y = address % mb_width, address // mb_width
    x0, y0 = mb_x * 16 + bx * 4, mb_y * 16 + by * 4

    def sample(x: int, y: int) -> int:
        return plane[y * width + x]

    left_ok = x0 > 0
    top_ok = y0 > 0
    corner_ok = left_ok and top_ok
    if by > 0 and bx < 3:
        top_right_ok = block_index(bx + 1, by - 1) < blk
    elif by > 0:
        top_right_ok = False
    elif bx < 3:
        top_right_ok = mb_y > 0
    else:
        top_right_ok = mb_y > 0 and mb_x + 1 < mb_width
    result = IntraNeighbours()
    result.top.append(sample(x0 - 1, y0 - 1) if corner_ok else None)
    result.top.extend(sample(x0 + i, y0 - 1) if top_ok else None for i in range(4))
    if top_right_ok and top_ok:
        result.top.extend(sample(x0 + i, y0 - 1) for i in range(4, 8))
    elif top_ok:
        result.top.extend([sample(x0 + 3, y0 - 1)] * 4)
        result.notes.append("C (tren-phai) khong co -> lap lai p[3,-1] cho p[4..7,-1]")
    else:
        result.top.extend([None] * 4)
    result.left.extend(sample(x0 - 1, y0 + i) if left_ok else None for i in range(4))
    if not left_ok:
        result.notes.append("A (trai) khong co")
    if not top_ok:
        result.notes.append("B (tren) khong co")
    return result


def predict_intra4x4(mode: int, n: IntraNeighbours) -> Matrix:
    """The nine Intra_4x4 predictors of 8.3.1.2.1-9; returns pred[y][x]."""
    def P(x: int, y: int) -> int:
        value = n.top[x + 1] if y == -1 else n.left[y]
        if value is None:
            raise ValueError(f"mode {INTRA4x4_MODE_NAMES[mode]} needs unavailable sample p[{x},{y}]")
        return value

    pred = [[0] * 4 for _ in range(4)]
    for y in range(4):
        for x in range(4):
            if mode == 0:
                v = P(x, -1)
            elif mode == 1:
                v = P(-1, y)
            elif mode == 2:
                top = None if n.top[1] is None else sum(P(i, -1) for i in range(4))
                left = None if n.left[0] is None else sum(P(-1, i) for i in range(4))
                if top is not None and left is not None:
                    v = (top + left + 4) >> 3
                elif left is not None:
                    v = (left + 2) >> 2
                elif top is not None:
                    v = (top + 2) >> 2
                else:
                    v = 128
            elif mode == 3:
                v = ((P(6, -1) + 3 * P(7, -1) + 2) >> 2 if x == 3 and y == 3
                     else (P(x + y, -1) + 2 * P(x + y + 1, -1) + P(x + y + 2, -1) + 2) >> 2)
            elif mode == 4:
                if x > y:
                    v = (P(x - y - 2, -1) + 2 * P(x - y - 1, -1) + P(x - y, -1) + 2) >> 2
                elif x < y:
                    v = (P(-1, y - x - 2) + 2 * P(-1, y - x - 1) + P(-1, y - x) + 2) >> 2
                else:
                    v = (P(0, -1) + 2 * P(-1, -1) + P(-1, 0) + 2) >> 2
            elif mode == 5:
                z = 2 * x - y
                if z in (0, 2, 4, 6):
                    v = (P(x - (y >> 1) - 1, -1) + P(x - (y >> 1), -1) + 1) >> 1
                elif z in (1, 3, 5):
                    v = (P(x - (y >> 1) - 2, -1) + 2 * P(x - (y >> 1) - 1, -1) + P(x - (y >> 1), -1) + 2) >> 2
                elif z == -1:
                    v = (P(-1, 0) + 2 * P(-1, -1) + P(0, -1) + 2) >> 2
                else:
                    v = (P(-1, y - 1) + 2 * P(-1, y - 2) + P(-1, y - 3) + 2) >> 2
            elif mode == 6:
                z = 2 * y - x
                if z in (0, 2, 4, 6):
                    v = (P(-1, y - (x >> 1) - 1) + P(-1, y - (x >> 1)) + 1) >> 1
                elif z in (1, 3, 5):
                    v = (P(-1, y - (x >> 1) - 2) + 2 * P(-1, y - (x >> 1) - 1) + P(-1, y - (x >> 1)) + 2) >> 2
                elif z == -1:
                    v = (P(-1, 0) + 2 * P(-1, -1) + P(0, -1) + 2) >> 2
                else:
                    v = (P(x - 1, -1) + 2 * P(x - 2, -1) + P(x - 3, -1) + 2) >> 2
            elif mode == 7:
                if y in (0, 2):
                    v = (P(x + (y >> 1), -1) + P(x + (y >> 1) + 1, -1) + 1) >> 1
                else:
                    v = (P(x + (y >> 1), -1) + 2 * P(x + (y >> 1) + 1, -1) + P(x + (y >> 1) + 2, -1) + 2) >> 2
            elif mode == 8:
                z = x + 2 * y
                if z in (0, 2, 4):
                    v = (P(-1, y + (x >> 1)) + P(-1, y + (x >> 1) + 1) + 1) >> 1
                elif z in (1, 3):
                    v = (P(-1, y + (x >> 1)) + 2 * P(-1, y + (x >> 1) + 1) + P(-1, y + (x >> 1) + 2) + 2) >> 2
                elif z == 5:
                    v = (P(-1, 2) + 3 * P(-1, 3) + 2) >> 2
                else:
                    v = P(-1, 3)
            else:
                raise ValueError(f"invalid Intra4x4PredMode {mode}")
            pred[y][x] = v
    return pred


def clip_add(pred: Matrix, residual: Matrix) -> Matrix:
    return [[min(255, max(0, pred[r][c] + residual[r][c])) for c in range(4)] for r in range(4)]


def macroblock_qps(macroblocks: list[dict], slice_qp: int) -> dict[int, int]:
    """QP_Y per macroblock: QP_prev + mb_qp_delta modulo 52 (7.4.5, 8-bit video)."""
    qps, qp = {}, slice_qp
    for mb in sorted(macroblocks, key=lambda item: item["address"]):
        qp = (qp + mb["mb_qp_delta"] + 52) % 52
        qps[mb["address"]] = qp
    return qps
