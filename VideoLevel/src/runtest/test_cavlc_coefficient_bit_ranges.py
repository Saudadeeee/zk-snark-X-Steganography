"""CAVLC coefficient-to-bit mappings needed for canonical carrier hashing."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bitstream.bitstream_io import BitstreamReader, BitstreamWriter
from src.bitstream.cavlc import CAVLCDecoder, CAVLCEncoder
from src.runtest._helpers import run_test, section, summarise


def t_tracing_maps_trailing_signs_and_regular_levels_to_encoded_bits() -> None:
    source = [2, 0, -3, 0, 1, -1, 1] + [0] * 9
    writer = BitstreamWriter()
    CAVLCEncoder(writer).encode_block_cavlc(source, nC=0)

    reader = BitstreamReader(writer.get_bytes())
    decoded = CAVLCDecoder(reader, track_coefficient_bit_ranges=True).decode_block_cavlc(nC=0)

    assert decoded.levels == source
    assert decoded.coefficient_bit_ranges is not None
    assert len(decoded.coefficient_bit_ranges) == len(source)
    for coefficient_index, value in enumerate(source):
        bit_range = decoded.coefficient_bit_ranges[coefficient_index]
        if value == 0:
            assert bit_range is None
            continue
        assert bit_range is not None
        start, end = bit_range
        assert 0 <= start < end <= reader.position

    # The final three non-zero coefficients in scan order are trailing ones;
    # each is represented by an explicit one-bit sign flag in CAVLC.
    assert [decoded.coefficient_bit_ranges[index][1] - decoded.coefficient_bit_ranges[index][0] for index in (4, 5, 6)] == [1, 1, 1]


def t_default_decode_does_not_retain_coefficient_bit_ranges() -> None:
    writer = BitstreamWriter()
    CAVLCEncoder(writer).encode_block_cavlc([1] + [0] * 15, nC=0)
    decoded = CAVLCDecoder(BitstreamReader(writer.get_bytes())).decode_block_cavlc(nC=0)

    assert decoded.coefficient_bit_ranges is None


def t_traced_empty_block_has_no_coefficient_bit_ranges() -> None:
    writer = BitstreamWriter()
    CAVLCEncoder(writer).encode_block_cavlc([0] * 16, nC=0)
    decoded = CAVLCDecoder(
        BitstreamReader(writer.get_bytes()), track_coefficient_bit_ranges=True
    ).decode_block_cavlc(nC=0)

    assert decoded.levels == [0] * 16
    assert decoded.coefficient_bit_ranges == [None] * 16


def main() -> None:
    section("CAVLC coefficient bit ranges")
    results = [
        run_test(
            "tracing_maps_trailing_signs_and_regular_levels_to_encoded_bits",
            t_tracing_maps_trailing_signs_and_regular_levels_to_encoded_bits,
        ),
        run_test(
            "default_decode_does_not_retain_coefficient_bit_ranges",
            t_default_decode_does_not_retain_coefficient_bit_ranges,
        ),
        run_test(
            "traced_empty_block_has_no_coefficient_bit_ranges",
            t_traced_empty_block_has_no_coefficient_bit_ranges,
        ),
    ]
    raise SystemExit(summarise(results, "CAVLC coefficient bit ranges"))


if __name__ == "__main__":
    main()
