"""CABAC I-slice macroblock layer: one traversal shared by decoding and encoding.

``code_macroblock`` walks ``macroblock_layer()`` of ITU-T H.264 7.3.5 for I
slices with CABAC (8-bit 4:2:0, frame macroblocks).  With a
:class:`~.engine.CabacDecoder` it reads the syntax into a :class:`Macroblock`;
with a :class:`~.engine.CabacEncoder` it writes a given :class:`Macroblock`.
Context selection (9.3.3.1.1 / 9.3.3.1.3) is computed by the same code in
both directions, so a decoded slice re-encodes to the canonical encoding of
its syntax.

Residual blocks are stored as coefficient lists in coding order (scan order,
``maxNumCoeff`` entries; for AC blocks entry ``i`` is scan position ``i + 1``).
"""

from __future__ import annotations

from .tables import LAST_COEFF_FLAG_OFFSET_8X8, SIG_COEFF_FLAG_OFFSET_8X8

I_NXN = 0
I_PCM = 25
PCM_BYTES = 384  # 8-bit 4:2:0: 256 luma + 2 x 64 chroma samples

CAT_LUMA_DC, CAT_LUMA_AC, CAT_LUMA_4X4, CAT_CHROMA_DC, CAT_CHROMA_AC, CAT_LUMA_8X8 = range(6)
_CBF_BASE = (85, 89, 93, 97, 101)
_SIG_BASE = (105, 120, 134, 149, 152, 402)
_LAST_BASE = (166, 181, 195, 210, 213, 417)
_ABS_BASE = (227, 237, 247, 257, 266, 426)
_MAX_QP_DELTA_CODE = 52  # mb_qp_delta in [-26, 25] for 8-bit video
_MAX_EG_PREFIX = 30


def _blk_index(x: int, y: int) -> int:
    return 8 * (y >> 1) + 4 * (x >> 1) + 2 * (y & 1) + (x & 1)


def _neighbour_tables() -> tuple[tuple[tuple[bool, int], ...], tuple[tuple[bool, int], ...]]:
    left, top = [], []
    for blk in range(16):
        x = ((blk >> 2) & 1) * 2 + (blk & 1)
        y = ((blk >> 3) & 1) * 2 + ((blk >> 1) & 1)
        left.append((True, _blk_index(x - 1, y)) if x else (False, _blk_index(3, y)))
        top.append((True, _blk_index(x, y - 1)) if y else (False, _blk_index(x, 3)))
    return tuple(left), tuple(top)


LUMA_LEFT, LUMA_TOP = _neighbour_tables()
CHROMA_LEFT = tuple((True, c - 1) if c & 1 else (False, c + 1) for c in range(4))
CHROMA_TOP = tuple((True, c - 2) if c >> 1 else (False, c + 2) for c in range(4))


class Macroblock:
    """Syntax of one I-slice macroblock (everything needed to re-encode it)."""

    __slots__ = (
        "addr",
        "cac_cbf",
        "cbp_chroma",
        "cbp_luma",
        "cdc_cbf",
        "chroma_ac",
        "chroma_dc",
        "chroma_pred",
        "lcbf",
        "ldc_cbf",
        "luma",
        "luma8x8",
        "luma_dc",
        "mb_type",
        "modes",
        "pcm",
        "qp_delta",
        "t8",
    )

    def __init__(self, addr: int) -> None:
        self.addr = addr
        self.mb_type = 0
        self.t8 = 0
        # Intra NxN modes: -1 = prev_intra_pred_mode_flag 1, else rem_intra_pred_mode.
        self.modes: list[int] | None = None
        self.chroma_pred = 0
        self.cbp_luma = 0
        self.cbp_chroma = 0
        self.qp_delta = 0
        self.luma_dc: list[int] | None = None
        self.luma: list[list[int] | None] | None = None  # 16 blocks (I16 AC or 4x4)
        self.luma8x8: list[list[int] | None] | None = None  # 4 blocks of 64
        self.chroma_dc: list[list[int]] | None = None  # [Cb, Cr] x 4
        self.chroma_ac: list[list[list[int] | None]] | None = None  # [Cb, Cr] x 4 x 15
        self.pcm: bytes | None = None
        self.lcbf = [0] * 16
        self.ldc_cbf = 0
        self.cdc_cbf = [0, 0]
        self.cac_cbf = [[0, 0, 0, 0], [0, 0, 0, 0]]

    @property
    def is_i16(self) -> bool:
        return 1 <= self.mb_type <= 24

    def copy(self) -> Macroblock:
        other = Macroblock(self.addr)
        other.mb_type, other.t8, other.chroma_pred = self.mb_type, self.t8, self.chroma_pred
        other.modes = None if self.modes is None else list(self.modes)
        other.cbp_luma, other.cbp_chroma, other.qp_delta = self.cbp_luma, self.cbp_chroma, self.qp_delta
        other.luma_dc = None if self.luma_dc is None else list(self.luma_dc)
        other.luma = None if self.luma is None else [None if b is None else list(b) for b in self.luma]
        other.luma8x8 = None if self.luma8x8 is None else [None if b is None else list(b) for b in self.luma8x8]
        other.chroma_dc = None if self.chroma_dc is None else [list(b) for b in self.chroma_dc]
        other.chroma_ac = None if self.chroma_ac is None else [
            [None if b is None else list(b) for b in comp] for comp in self.chroma_ac
        ]
        other.pcm = self.pcm
        return other


# --- neighbour coded_block_flag values (9.3.3.1.1.9) -------------------------

def _luma_cbf(mb: Macroblock | None, blk: int) -> int:
    if mb is None or mb.mb_type == I_PCM:
        return 1  # unavailable neighbour of an intra macroblock, or I_PCM
    if not (mb.cbp_luma >> (blk >> 2)) & 1:
        return 0
    if mb.t8:
        return 1  # 8x8 block without coded_block_flag (4:2:0): inferred 1
    return mb.lcbf[blk]


def _luma_dc_cbf(mb: Macroblock | None) -> int:
    if mb is None or mb.mb_type == I_PCM:
        return 1
    return mb.ldc_cbf if mb.is_i16 else 0


def _chroma_dc_cbf(mb: Macroblock | None, comp: int) -> int:
    if mb is None or mb.mb_type == I_PCM:
        return 1
    return mb.cdc_cbf[comp] if mb.cbp_chroma else 0


def _chroma_ac_cbf(mb: Macroblock | None, comp: int, blk: int) -> int:
    if mb is None or mb.mb_type == I_PCM:
        return 1
    return mb.cac_cbf[comp][blk] if mb.cbp_chroma == 2 else 0


# --- residual_block_cabac ----------------------------------------------------

def code_residual_block(engine, coeffs: list[int] | None, cat: int, max_coeff: int,
                        cbf_inc: int | None) -> list[int] | None:
    """Code one residual block; returns its coefficients (``None`` if coded_block_flag = 0)."""
    encoding = engine.encoding
    decision = engine.decision
    if encoding:
        coded = 1 if coeffs is not None and any(coeffs) else 0
        if cbf_inc is None and not coded:
            raise ValueError("an 8x8 luma block with its CBP bit set must have a nonzero coefficient")
    if cbf_inc is not None:
        coded = decision(_CBF_BASE[cat] + cbf_inc, coded if encoding else None)
        if not coded:
            return None
    sig_base, last_base = _SIG_BASE[cat], _LAST_BASE[cat]
    if cat == CAT_LUMA_8X8:
        sig_inc, last_inc = SIG_COEFF_FLAG_OFFSET_8X8, LAST_COEFF_FLAG_OFFSET_8X8
    elif cat == CAT_CHROMA_DC:
        sig_inc = last_inc = (0, 1, 2)
    else:
        sig_inc = last_inc = range(max_coeff)
    if encoding:
        positions = [index for index, value in enumerate(coeffs) if value]
        last = positions[-1]
        for index in range(min(last + 1, max_coeff - 1)):
            significant = 1 if coeffs[index] else 0
            decision(sig_base + sig_inc[index], significant)
            if significant:
                decision(last_base + last_inc[index], 1 if index == last else 0)
        values = coeffs
    else:
        positions = []
        for index in range(max_coeff - 1):
            if decision(sig_base + sig_inc[index]):
                positions.append(index)
                if decision(last_base + last_inc[index]):
                    break
        else:
            positions.append(max_coeff - 1)
        values = [0] * max_coeff
    abs_base = _ABS_BASE[cat]
    gt1_cap = 3 if cat == CAT_CHROMA_DC else 4
    bypass = engine.bypass
    eq1 = gt1 = 0
    for position in reversed(positions):
        first_ctx = abs_base + (0 if gt1 else min(4, 1 + eq1))
        rest_ctx = abs_base + 5 + min(gt1_cap, gt1)
        if encoding:
            value = values[position]
            minus1 = abs(value) - 1
            prefix = min(minus1, 14)
            for bin_index in range(prefix):
                decision(first_ctx if bin_index == 0 else rest_ctx, 1)
            if prefix < 14:
                decision(first_ctx if prefix == 0 else rest_ctx, 0)
            else:
                suffix, k = minus1 - 14, 0
                while suffix >= (1 << k):
                    bypass(1)
                    suffix -= 1 << k
                    k += 1
                bypass(0)
                while k:
                    k -= 1
                    bypass((suffix >> k) & 1)
            bypass(1 if value < 0 else 0)
        else:
            prefix = 0
            while prefix < 14 and decision(first_ctx if prefix == 0 else rest_ctx):
                prefix += 1
            minus1 = prefix
            if prefix == 14:
                k = 0
                while bypass():
                    k += 1
                    if k > _MAX_EG_PREFIX:
                        raise ValueError("coeff_abs_level_minus1 suffix is too long")
                suffix = (1 << k) - 1
                for shift in range(k - 1, -1, -1):
                    suffix += bypass() << shift
                minus1 = 14 + suffix
            magnitude = minus1 + 1
            values[position] = -magnitude if bypass() else magnitude
        if minus1:
            gt1 += 1
        else:
            eq1 += 1
    return values


# --- macroblock_layer ----------------------------------------------------------

def _code_mb_type(engine, mb: Macroblock, inc: int) -> None:
    decision, encoding = engine.decision, engine.encoding
    if encoding:
        mb_type = mb.mb_type
        decision(3 + inc, 0 if mb_type == I_NXN else 1)
        if mb_type == I_NXN:
            return
        engine.terminate(1 if mb_type == I_PCM else 0)
        if mb_type == I_PCM:
            return
        code = mb_type - 1
        chroma = (code % 12) // 4
        decision(6, code // 12)
        decision(7, 1 if chroma else 0)
        if chroma:
            decision(8, 1 if chroma == 2 else 0)
        decision(9, (code & 3) >> 1)
        decision(10, code & 1)
        return
    if not decision(3 + inc):
        mb.mb_type = I_NXN
    elif engine.terminate():
        mb.mb_type = I_PCM
    else:
        luma = decision(6)
        chroma = 1 + decision(8) if decision(7) else 0
        pred = 2 * decision(9)
        pred += decision(10)
        mb.mb_type = 1 + 12 * luma + 4 * chroma + pred


def _code_pcm(engine, mb: Macroblock) -> None:
    if engine.encoding:
        writer = engine.writer
        while not writer.aligned:
            writer.write(0)  # pcm_alignment_zero_bit
        if mb.pcm is None or len(mb.pcm) != PCM_BYTES:
            raise ValueError("I_PCM macroblock needs exactly 384 sample bytes")
        for byte in mb.pcm:
            writer.write_bits(byte, 8)
        engine.start()
        return
    pos = engine.pos
    while pos & 7:
        if (engine.data[pos >> 3] >> (7 - (pos & 7))) & 1:
            raise ValueError("pcm_alignment_zero_bit is not zero")
        pos += 1
    start = pos >> 3
    if start + PCM_BYTES > len(engine.data):
        raise ValueError("truncated I_PCM samples")
    mb.pcm = bytes(engine.data[start:start + PCM_BYTES])
    engine.pos = pos + PCM_BYTES * 8
    engine.start()


def _code_modes(engine, mb: Macroblock) -> None:
    decision, encoding = engine.decision, engine.encoding
    count = 4 if mb.t8 else 16
    if not encoding:
        mb.modes = [0] * count
    modes = mb.modes
    if encoding and (modes is None or len(modes) != count):
        raise ValueError("intra NxN macroblock has the wrong number of prediction modes")
    for index in range(count):
        if encoding:
            mode = modes[index]
            decision(68, 1 if mode < 0 else 0)
            if mode >= 0:
                decision(69, mode & 1)
                decision(69, (mode >> 1) & 1)
                decision(69, (mode >> 2) & 1)
        elif decision(68):
            modes[index] = -1
        else:
            mode = decision(69)
            mode += decision(69) << 1
            mode += decision(69) << 2
            modes[index] = mode


def _code_chroma_pred(engine, mb: Macroblock, left: Macroblock | None, top: Macroblock | None) -> None:
    decision, encoding = engine.decision, engine.encoding
    inc = (left is not None and left.mb_type != I_PCM and left.chroma_pred != 0)
    inc += (top is not None and top.mb_type != I_PCM and top.chroma_pred != 0)
    if encoding:
        mode = mb.chroma_pred
        decision(64 + inc, 1 if mode else 0)
        if mode:
            decision(67, 1 if mode > 1 else 0)
            if mode > 1:
                decision(67, 1 if mode > 2 else 0)
        return
    mode = 0
    if decision(64 + inc):
        mode = 1
        if decision(67):
            mode = 2 + decision(67)
    mb.chroma_pred = mode


def _cbp_term(mb: Macroblock | None, b8: int) -> int:
    if mb is None or mb.mb_type == I_PCM or (mb.cbp_luma >> b8) & 1:
        return 0
    return 1


def _code_cbp(engine, mb: Macroblock, left: Macroblock | None, top: Macroblock | None) -> None:
    decision, encoding = engine.decision, engine.encoding
    target = mb.cbp_luma if encoding else 0
    mb.cbp_luma = 0
    neighbours = (((left, 1), (top, 2)), ((mb, 0), (top, 3)), ((left, 3), (mb, 0)), ((mb, 2), (mb, 1)))
    for b8, ((a_mb, a_b8), (b_mb, b_b8)) in enumerate(neighbours):
        inc = _cbp_term(a_mb, a_b8) + 2 * _cbp_term(b_mb, b_b8)
        bit = decision(73 + inc, (target >> b8) & 1 if encoding else None)
        mb.cbp_luma |= bit << b8
    a_c = 0 if left is None else (2 if left.mb_type == I_PCM else left.cbp_chroma)
    b_c = 0 if top is None else (2 if top.mb_type == I_PCM else top.cbp_chroma)
    inc = (a_c != 0) + 2 * (b_c != 0)
    if encoding:
        chroma = mb.cbp_chroma
        decision(77 + inc, 1 if chroma else 0)
        if chroma:
            decision(81 + (a_c == 2) + 2 * (b_c == 2), 1 if chroma == 2 else 0)
        return
    chroma = 0
    if decision(77 + inc):
        chroma = 1 + decision(81 + (a_c == 2) + 2 * (b_c == 2))
    mb.cbp_chroma = chroma


def _code_qp_delta(engine, mb: Macroblock, previous: Macroblock | None) -> None:
    decision, encoding = engine.decision, engine.encoding
    inc = 1 if previous is not None and previous.qp_delta != 0 else 0
    if encoding:
        delta = mb.qp_delta
        code = 2 * delta - 1 if delta > 0 else -2 * delta
        if code > _MAX_QP_DELTA_CODE:
            raise ValueError("mb_qp_delta out of range")
        for index in range(code + 1):
            decision(60 + inc if index == 0 else (62 if index == 1 else 63), 1 if index < code else 0)
        return
    code = 0
    while decision(60 + inc if code == 0 else (62 if code == 1 else 63)):
        code += 1
        if code > _MAX_QP_DELTA_CODE:
            raise ValueError("mb_qp_delta out of range")
    mb.qp_delta = (code + 1) // 2 if code & 1 else -(code // 2)


def _code_residual(engine, mb: Macroblock, left: Macroblock | None, top: Macroblock | None) -> None:
    encoding = engine.encoding
    if mb.is_i16:
        inc = _luma_dc_cbf(left) + 2 * _luma_dc_cbf(top)
        block = code_residual_block(engine, mb.luma_dc if encoding else None, CAT_LUMA_DC, 16, inc)
        mb.ldc_cbf = 0 if block is None else 1
        if not encoding:
            mb.luma_dc = block
    luma = mb.luma if encoding else [None] * 16
    luma8 = mb.luma8x8 if encoding else ([None] * 4 if mb.t8 else None)
    for b8 in range(4):
        if not (mb.cbp_luma >> b8) & 1:
            continue
        if mb.t8:
            block = code_residual_block(engine, luma8[b8] if encoding else None, CAT_LUMA_8X8, 64, None)
            luma8[b8] = block
            for blk in range(4 * b8, 4 * b8 + 4):
                mb.lcbf[blk] = 1
            continue
        cat, size = (CAT_LUMA_AC, 15) if mb.is_i16 else (CAT_LUMA_4X4, 16)
        for blk in range(4 * b8, 4 * b8 + 4):
            inside, other = LUMA_LEFT[blk]
            inc = _luma_cbf(mb if inside else left, other)
            inside, other = LUMA_TOP[blk]
            inc += 2 * _luma_cbf(mb if inside else top, other)
            block = code_residual_block(engine, luma[blk] if encoding else None, cat, size, inc)
            mb.lcbf[blk] = 0 if block is None else 1
            luma[blk] = block
    if not encoding:
        mb.luma = luma if (mb.cbp_luma and not mb.t8) else None
        mb.luma8x8 = luma8 if (mb.cbp_luma and mb.t8) else None
    if mb.cbp_chroma:
        dc = mb.chroma_dc if encoding else [None, None]
        for comp in range(2):
            inc = _chroma_dc_cbf(left, comp) + 2 * _chroma_dc_cbf(top, comp)
            block = code_residual_block(engine, dc[comp] if encoding else None, CAT_CHROMA_DC, 4, inc)
            mb.cdc_cbf[comp] = 0 if block is None else 1
            dc[comp] = block if block is not None else [0, 0, 0, 0]
        if not encoding:
            mb.chroma_dc = dc
    if mb.cbp_chroma == 2:
        ac = mb.chroma_ac if encoding else [[None] * 4, [None] * 4]
        for comp in range(2):
            for blk in range(4):
                inside, other = CHROMA_LEFT[blk]
                inc = _chroma_ac_cbf(mb if inside else left, comp, other)
                inside, other = CHROMA_TOP[blk]
                inc += 2 * _chroma_ac_cbf(mb if inside else top, comp, other)
                block = code_residual_block(engine, ac[comp][blk] if encoding else None,
                                            CAT_CHROMA_AC, 15, inc)
                mb.cac_cbf[comp][blk] = 0 if block is None else 1
                ac[comp][blk] = block
        if not encoding:
            mb.chroma_ac = ac


def code_macroblock(engine, mb: Macroblock | None, addr: int, left: Macroblock | None,
                    top: Macroblock | None, previous: Macroblock | None,
                    transform_8x8_mode: int) -> Macroblock:
    """Decode (``mb is None``) or encode one I-slice macroblock; returns it."""
    encoding = engine.encoding
    if not encoding:
        mb = Macroblock(addr)
    else:
        mb.lcbf = [0] * 16
        mb.ldc_cbf = 0
        mb.cdc_cbf = [0, 0]
        mb.cac_cbf = [[0, 0, 0, 0], [0, 0, 0, 0]]
    inc = (left is not None and left.mb_type != I_NXN) + (top is not None and top.mb_type != I_NXN)
    _code_mb_type(engine, mb, inc)
    if mb.mb_type == I_PCM:
        _code_pcm(engine, mb)
        mb.t8, mb.chroma_pred, mb.qp_delta = 0, 0, 0
        mb.cbp_luma, mb.cbp_chroma = 15, 2
        return mb
    if mb.mb_type == I_NXN:
        if transform_8x8_mode:
            inc = (left is not None and left.t8 == 1) + (top is not None and top.t8 == 1)
            mb.t8 = engine.decision(399 + inc, mb.t8 if encoding else None)
        elif encoding and mb.t8:
            raise ValueError("transform_size_8x8_flag set while the PPS disables 8x8 transforms")
        _code_modes(engine, mb)
    else:
        mb.t8 = 0
        mb.modes = None
        code = mb.mb_type - 1
        mb.cbp_luma = 15 if code >= 12 else 0
        mb.cbp_chroma = (code % 12) // 4
    _code_chroma_pred(engine, mb, left, top)
    if mb.mb_type == I_NXN:
        _code_cbp(engine, mb, left, top)
    if mb.cbp_luma or mb.cbp_chroma or mb.is_i16:
        _code_qp_delta(engine, mb, previous)
    else:
        mb.qp_delta = 0
    _code_residual(engine, mb, left, top)
    return mb
