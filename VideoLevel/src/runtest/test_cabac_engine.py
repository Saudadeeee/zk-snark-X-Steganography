"""CABAC engine, residual coder and macroblock layer: encoder/decoder symmetry (no video needed)."""

from __future__ import annotations

import hashlib
import random

import pytest

from src.bitstream.cabac.engine import BitWriter, CabacDecoder, CabacEncoder
from src.bitstream.cabac.headers import escape, is_canonically_escaped, unescape
from src.bitstream.cabac.syntax import (
    CAT_CHROMA_AC, CAT_CHROMA_DC, CAT_LUMA_4X4, CAT_LUMA_8X8, CAT_LUMA_AC, CAT_LUMA_DC, I_NXN, I_PCM,
    Macroblock, code_macroblock, code_residual_block,
)
from src.transport.cabac_sync import CabacMagnitudeContract

QP = 27


def _encoded(ops) -> tuple[bytes, int]:
    writer = BitWriter()
    encoder = CabacEncoder(writer, QP)
    for kind, ctx, value in ops:
        if kind == "d":
            encoder.decision(ctx, value)
        elif kind == "b":
            encoder.bypass(value)
        else:
            encoder.terminate(value)
    end = writer.bit_length
    while not writer.aligned:
        writer.write(0)
    return writer.to_bytes(), end


@pytest.mark.parametrize("seed", range(6))
def test_random_bins_round_trip_and_end_position(seed) -> None:
    rng = random.Random(seed)
    ops = []
    for _ in range(20_000):
        roll = rng.random()
        if roll < 0.8:
            ctx = rng.randrange(1024)
            ops.append(("d", ctx, 1 if rng.random() < (0.9 if ctx & 1 else 0.2) else 0))
        elif roll < 0.98:
            ops.append(("b", 0, rng.randrange(2)))
        else:
            ops.append(("t", 0, 0))
    ops.append(("t", 0, 1))
    data, end = _encoded(ops)
    decoder = CabacDecoder(data, 0, QP)
    for kind, ctx, value in ops:
        if kind == "d":
            assert decoder.decision(ctx) == value
        elif kind == "b":
            assert decoder.bypass() == value
        else:
            assert decoder.terminate() == value
    # After the final terminate bin the decoder sits exactly after rbsp_stop_one_bit.
    assert decoder.pos == end
    assert (data[(end - 1) >> 3] >> (7 - ((end - 1) & 7))) & 1 == 1


def _random_block(rng: random.Random, size: int, allow_empty: bool = True) -> list[int]:
    block = [0] * size
    count = rng.randrange(0 if allow_empty else 1, size + 1)
    for index in rng.sample(range(size), count):
        magnitude = rng.choice([1, 1, 1, 2, 3, 5, 14, 15, 16, 40, 300, 5000])
        block[index] = magnitude if rng.random() < 0.5 else -magnitude
    return block


@pytest.mark.parametrize(("cat", "size"), [
    (CAT_LUMA_DC, 16), (CAT_LUMA_AC, 15), (CAT_LUMA_4X4, 16), (CAT_CHROMA_DC, 4),
    (CAT_CHROMA_AC, 15), (CAT_LUMA_8X8, 64),
])
def test_residual_blocks_round_trip(cat, size) -> None:
    rng = random.Random(cat)
    blocks = [_random_block(rng, size, allow_empty=cat != CAT_LUMA_8X8) for _ in range(300)]
    incs = [None if cat == CAT_LUMA_8X8 else rng.randrange(4) for _ in blocks]
    writer = BitWriter()
    encoder = CabacEncoder(writer, QP)
    for block, inc in zip(blocks, incs):
        code_residual_block(encoder, block, cat, size, inc)
    encoder.terminate(1)
    while not writer.aligned:
        writer.write(0)
    decoder = CabacDecoder(writer.to_bytes(), 0, QP)
    for block, inc in zip(blocks, incs):
        decoded = code_residual_block(decoder, None, cat, size, inc)
        assert (decoded or [0] * size) == block
    assert decoder.terminate() == 1


def test_an_empty_8x8_block_with_its_cbp_bit_set_is_refused() -> None:
    encoder = CabacEncoder(BitWriter(), QP)
    with pytest.raises(ValueError, match="nonzero coefficient"):
        code_residual_block(encoder, [0] * 64, CAT_LUMA_8X8, 64, None)


def _random_macroblock(rng: random.Random, addr: int, transform_8x8_mode: int) -> Macroblock:
    mb = Macroblock(addr)
    roll = rng.random()
    if roll < 0.05:
        mb.mb_type = I_PCM
        mb.pcm = bytes(rng.randrange(256) for _ in range(384))
        return mb
    mb.mb_type = I_NXN if roll < 0.55 else rng.randrange(1, 25)
    mb.chroma_pred = rng.randrange(4)
    if mb.mb_type == I_NXN:
        mb.t8 = rng.randrange(2) if transform_8x8_mode else 0
        mb.modes = [rng.choice([-1, rng.randrange(8)]) for _ in range(4 if mb.t8 else 16)]
        mb.cbp_luma = rng.randrange(16)
        mb.cbp_chroma = rng.randrange(3)
    else:
        code = mb.mb_type - 1
        mb.cbp_luma = 15 if code >= 12 else 0
        mb.cbp_chroma = (code % 12) // 4
    if mb.cbp_luma or mb.cbp_chroma or mb.is_i16:
        mb.qp_delta = rng.randrange(-26, 26)
    if mb.is_i16:
        mb.luma_dc = _random_block(rng, 16)
    if mb.cbp_luma:
        if mb.t8:
            mb.luma8x8 = [_random_block(rng, 64, False) if (mb.cbp_luma >> b) & 1 else None for b in range(4)]
        else:
            size = 15 if mb.is_i16 else 16
            mb.luma = [_random_block(rng, size) if (mb.cbp_luma >> (blk >> 2)) & 1 else None
                       for blk in range(16)]
    if mb.cbp_chroma:
        mb.chroma_dc = [_random_block(rng, 4), _random_block(rng, 4)]
    if mb.cbp_chroma == 2:
        mb.chroma_ac = [[_random_block(rng, 15) for _ in range(4)] for _ in range(2)]
    return mb


def _canonical_fields(mb: Macroblock) -> tuple:
    def nonempty(block):
        return None if block is None or not any(block) else tuple(block)

    luma = None if mb.luma is None else tuple(nonempty(b) for b in mb.luma)
    luma8 = None if mb.luma8x8 is None else tuple(nonempty(b) for b in mb.luma8x8)
    cdc = None if mb.chroma_dc is None else tuple(tuple(b) for b in mb.chroma_dc)
    cac = None if mb.chroma_ac is None else tuple(tuple(nonempty(b) for b in comp) for comp in mb.chroma_ac)
    ldc = nonempty(mb.luma_dc)
    if mb.mb_type == I_PCM:
        return (mb.mb_type, mb.pcm)
    return (mb.mb_type, mb.t8, None if mb.modes is None else tuple(mb.modes), mb.chroma_pred,
            mb.cbp_luma, mb.cbp_chroma, mb.qp_delta, ldc, luma, luma8, cdc, cac)


def _walk(engine, mbs, width: int, count: int, transform_8x8_mode: int) -> list[Macroblock]:
    by_addr: dict[int, Macroblock] = {}
    out = []
    previous = None
    for addr in range(count):
        left = by_addr.get(addr - 1) if addr % width else None
        top = by_addr.get(addr - width)
        mb = code_macroblock(engine, None if mbs is None else mbs[addr], addr, left, top, previous,
                             transform_8x8_mode)
        by_addr[addr] = previous = mb
        out.append(mb)
        last = addr == count - 1
        if mbs is None:
            assert engine.terminate() == (1 if last else 0)
        else:
            engine.terminate(1 if last else 0)
    return out


@pytest.mark.parametrize("seed", range(12))
def test_random_macroblock_pictures_round_trip(seed) -> None:
    """Every I-slice syntax element, context selection and I_PCM re-initialisation is symmetric."""
    rng = random.Random(100 + seed)
    width, count, transform_8x8_mode = 11, 99, seed % 2
    mbs = [_random_macroblock(rng, addr, transform_8x8_mode) for addr in range(count)]
    writer = BitWriter()
    _walk(CabacEncoder(writer, 20 + seed), mbs, width, count, transform_8x8_mode)
    while not writer.aligned:
        writer.write(0)
    decoded = _walk(CabacDecoder(writer.to_bytes(), 0, 20 + seed), None, width, count, transform_8x8_mode)
    assert [_canonical_fields(mb) for mb in decoded] == [_canonical_fields(mb) for mb in mbs]
    assert any(mb.mb_type == I_PCM for mb in mbs)


def test_emulation_prevention_is_minimal_and_handles_cabac_zero_words() -> None:
    # Slice data, its stop-bit byte, then two cabac_zero_words.
    rbsp = b"\x12\x00\x00\x01\x80\x00\x00\x00\x00"
    escaped = escape(rbsp)
    assert escaped == b"\x12\x00\x00\x03\x01\x80\x00\x00\x03\x00\x00\x03"
    assert unescape(escaped) == rbsp
    assert is_canonically_escaped(escaped)
    assert not is_canonically_escaped(escaped[:-1])  # missing final 0x03
    assert not is_canonically_escaped(b"\x12\x00\x00\x03\x04")  # superfluous escape
    assert escape(b"\xab\x00\x00") == b"\xab\x00\x00\x03"


def test_normative_tables_are_pinned() -> None:
    """Values transcribed by research/cabac/gen_cabac_tables.py from FFmpeg n7.1."""
    from src.bitstream.cabac import tables

    blob = repr((tables.INIT_I, tables.RANGE_TAB_LPS, tables.TRANS_IDX_LPS, tables.TRANS_IDX_MPS,
                 tables.SIG_COEFF_FLAG_OFFSET_8X8, tables.LAST_COEFF_FLAG_OFFSET_8X8)).encode()
    assert hashlib.sha256(blob).hexdigest() == (
        "828b267489425562575296fb2f3159094382cf80ffcace9b7a9182a90658d695"
    )
    # Spot checks against ITU-T H.264 Tables 9-44, 9-45, 9-17, 9-21 and 9-34.
    assert tables.RANGE_TAB_LPS[0] == (128, 176, 208, 240) and tables.RANGE_TAB_LPS[63] == (2, 2, 2, 2)
    assert tables.TRANS_IDX_LPS[:6] == (0, 0, 1, 2, 2, 4) and tables.TRANS_IDX_LPS[63] == 63
    assert tables.TRANS_IDX_MPS[61:] == (62, 62, 63)
    assert tables.INIT_I[60:64] == ((0, 41), (0, 63), (0, 63), (0, 63))
    assert tables.INIT_I[399:402] == ((31, 21), (31, 31), (25, 50))


@pytest.mark.parametrize("magnitude", [1, 3, 5, 0, True])
def test_contract_requires_an_even_threshold(magnitude) -> None:
    with pytest.raises(ValueError):
        CabacMagnitudeContract(min_magnitude=magnitude)
