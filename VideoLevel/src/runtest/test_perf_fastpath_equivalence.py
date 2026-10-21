"""Fast paths in the CAVLC decoder and canonical digest equal the generic code.

Each fast path is selected only for the library's own concrete types
(``BitstreamReader``, ``BitArray``, ``(int, int, list)`` entries). A subclass
or a plain sequence forces the original generic code, so the two can be
compared on identical inputs, including truncated and corrupt bitstreams.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import pytest

from src.bitstream.bitstream_io import BitstreamReader, BitstreamWriter
from src.bitstream.bitstream_ops import BitArray
from src.bitstream.cavlc import CAVLCDecoder, CAVLCEncoder
from src.transport.video_canonicalization import (
    _update_raw_bit_segment,
    canonical_h264_digest,
    canonicalize_carrier_coefficients,
)

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "data" / "external" / "trust_corpus" / "mdn_friday_cif_q22_g1_30f.h264"
)


class GenericReader(BitstreamReader):
    """Same reader, but its type disables the direct-bit fast paths."""


def _decode_outcome(reader_type, data: bytes, start: int, nC: int, max_num_coeff: int):
    reader = reader_type(data)
    reader.pos = start
    try:
        block = CAVLCDecoder(reader).decode_block_cavlc(nC, max_num_coeff=max_num_coeff)
        outcome = ("ok", block.levels, block.total_coeffs, block.trailing_ones, block.total_zeros)
    except Exception as error:  # noqa: BLE001 - the error itself is compared
        outcome = ("error", type(error).__name__, str(error))
    return outcome, reader.pos


def _random_blocks(rng: random.Random, count: int) -> list[list[int]]:
    blocks = []
    for _ in range(count):
        levels = [0] * 16
        for index in rng.sample(range(16), rng.randint(1, 16)):
            magnitude = rng.choice([1, 1, 1, 2, 3, 5, 9, 17, 40, 300, 2500])
            levels[index] = magnitude if rng.random() < 0.5 else -magnitude
        blocks.append(levels)
    return blocks


@pytest.mark.parametrize("nC", [-1, 0, 2, 4, 8])
def test_direct_decoder_matches_generic_reader_on_valid_and_corrupt_data(nC):
    rng = random.Random(1000 + nC)
    max_num_coeff = 4 if nC == -1 else 16
    streams = []
    for levels in _random_blocks(rng, 150):
        if nC == -1:
            levels = levels[:4]
            if not any(levels):
                levels[0] = 1
        writer = BitstreamWriter()
        try:
            CAVLCEncoder(writer).encode_block_cavlc(levels, nC=nC, max_num_coeff=max_num_coeff)
        except Exception:  # noqa: BLE001 - only encodable blocks are useful here
            continue
        encoded = writer.get_bytes(align=True)
        streams.append(encoded + bytes(4))
        streams.append(encoded[: max(1, len(encoded) // 2)])  # truncated
        corrupt = bytearray(encoded)
        corrupt[rng.randrange(len(corrupt))] ^= 1 << rng.randrange(8)
        streams.append(bytes(corrupt))
    streams.extend(bytes(rng.randrange(256) for _ in range(12)) for _ in range(200))
    streams.extend([b"\x00" * 6, b"\x00\x00\x00\x01", b"\xff"])
    assert len(streams) > 300
    for data in streams:
        for start in (0, 3):
            if start >= len(data) * 8:
                continue
            assert _decode_outcome(BitstreamReader, data, start, nC, max_num_coeff) == (
                _decode_outcome(GenericReader, data, start, nC, max_num_coeff)
            )


def test_direct_decoder_matches_generic_reader_on_real_slices():
    if not FIXTURE.is_file():
        pytest.skip("the checked-in H.264 fixture is unavailable")
    from src.bitstream.h264 import NALParser

    nal_units = NALParser(FIXTURE.read_bytes()).parse()
    idr = [nal.rbsp_byte for nal in nal_units if int(nal.nal_unit_type) == 5][:2]
    rng = random.Random(7)
    for rbsp in idr:
        for start in rng.sample(range(len(rbsp) * 8 - 64), 400):
            for nC in (0, 3, 5, 9):
                assert _decode_outcome(BitstreamReader, rbsp, start, nC, 16) == (
                    _decode_outcome(GenericReader, rbsp, start, nC, 16)
                )


class ListBits:
    """Bit source without ``.bits``: exercises the original list-slice path."""

    def __init__(self, data: bytes):
        self._bits = BitArray(data)[0:len(data) * 8]

    def __getitem__(self, key):
        return self._bits[key]


def test_raw_bit_segment_fast_path_matches_list_path():
    rng = random.Random(3)
    data = bytes(rng.randrange(256) for _ in range(257))
    fast_source, list_source = BitArray(data), ListBits(data)
    total = len(data) * 8
    for _ in range(500):
        start = rng.randrange(total + 1)
        end = rng.randrange(start, total + 1)
        fast, generic = hashlib.sha256(), hashlib.sha256()
        _update_raw_bit_segment(fast, fast_source, start, end)
        _update_raw_bit_segment(generic, list_source, start, end)
        assert fast.digest() == generic.digest()


def test_canonicalize_fast_path_matches_generic_entries():
    rng = random.Random(5)
    coefficients = [
        (mb, block, levels)
        for mb in range(30)
        for block, levels in enumerate(_random_blocks(rng, 16))
    ]
    positions = []
    for mb, block, levels in rng.sample(coefficients, 120):
        index = next(i for i, value in enumerate(levels) if value)
        positions.append((mb, block, ~index if abs(levels[index]) == 1 else index))
    generic_entries = [[mb, block, tuple(levels)] for mb, block, levels in coefficients]
    fast = canonicalize_carrier_coefficients(coefficients, positions)
    generic = canonicalize_carrier_coefficients(generic_entries, positions)
    assert fast == generic
    with pytest.raises(ValueError, match="duplicate coefficient block"):
        canonicalize_carrier_coefficients(coefficients + coefficients[:1], positions)
    for bad in ((True, 0, [1]), (0, 0.0, [1]), (0, 0, 7), (0, 0)):
        with pytest.raises(ValueError):
            canonicalize_carrier_coefficients([bad], [])


def test_canonical_digest_is_unchanged_for_real_analysis():
    if not FIXTURE.is_file():
        pytest.skip("the checked-in H.264 fixture is unavailable")
    from src.bitstream.bitstream_ops import BitstreamReconstructor
    from src.bitstream.h264 import H264BitstreamParser
    from src.core.pipeline import extract_all_idr_blocks

    parser = H264BitstreamParser(str(FIXTURE))
    parser.parse()
    nal_units = [nal for nal in parser.nal_units if int(nal.nal_unit_type) != 5]
    idr_nals = [nal for nal in parser.nal_units if int(nal.nal_unit_type) == 5][:3]
    parser.nal_units = nal_units + idr_nals
    coefficients, frame_data, *_ = extract_all_idr_blocks(
        str(FIXTURE), BitstreamReconstructor(), parser=parser
    )
    rng = random.Random(11)
    positions = []
    for mb, block, levels in rng.sample(coefficients, 300):
        index = next(i for i, value in enumerate(levels) if value)
        positions.append((mb, block, ~index if abs(levels[index]) == 1 else index))
    # Frame data rebuilt with generic (list-entry / tuple-level) structures
    # takes every original slow path in canonicalization.
    generic_frames = {
        offset: (offsets, {key: tuple(levels) for key, levels in blocks.items()}, rbsp)
        for offset, (offsets, blocks, rbsp) in frame_data.items()
    }
    fast = canonical_h264_digest(parser.nal_units, frame_data, positions)
    generic = canonical_h264_digest(parser.nal_units, generic_frames, positions)
    assert fast == generic
