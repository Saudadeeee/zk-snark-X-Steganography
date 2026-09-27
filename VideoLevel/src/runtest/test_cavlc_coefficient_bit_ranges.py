"""CAVLC coefficient-to-bit mappings needed for canonical carrier hashing."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bitstream.bitstream_io import BitstreamReader, BitstreamWriter
from src.bitstream.cavlc import CAVLCDecoder, CAVLCEncoder
from src.runtest._helpers import get_video, run_test, section, summarise


def t_tracing_maps_trailing_signs_and_regular_levels_to_encoded_bits() -> None:
    # Keep one regular level followed by two trailing-one coefficients. This
    # pattern is round-trip stable in the repository's current encoder/decoder.
    source = [2, -1, 1] + [0] * 13
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

    # The final two non-zero coefficients in scan order are trailing ones;
    # each is represented by an explicit one-bit sign flag in CAVLC.
    assert [
        decoded.coefficient_bit_ranges[index][1] - decoded.coefficient_bit_ranges[index][0]
        for index in (1, 2)
    ] == [1, 1]
    assert decoded.coefficient_bit_ranges[0][1] - decoded.coefficient_bit_ranges[0][0] > 1


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


def t_traceable_h264_parser_retains_absolute_ranges_only_when_requested() -> None:
    from src.bitstream.bitstream_ops import BitstreamReconstructor
    from src.bitstream.h264 import H264BitstreamParser, TraceableCAVLCParser

    parser = H264BitstreamParser(get_video("foreman_cif_q22_g1.h264"))
    parser.parse()
    reconstructor = BitstreamReconstructor()
    sps = pps = None
    for nal in parser.nal_units:
        nal_type = int(nal.nal_unit_type)
        if nal_type == 7:
            sps = reconstructor._parse_sps_from_nal(nal)
        elif nal_type == 8:
            pps = reconstructor._parse_pps_from_nal(nal)
    assert sps is not None and pps is not None
    idr = next(nal for nal in parser.nal_units if int(nal.nal_unit_type) == 5)

    traced = TraceableCAVLCParser(track_coefficient_bit_ranges=True)
    result = traced.extract_with_offsets(idr, sps, pps)
    offsets = result["offsets"]
    blocks = result["blocks"]
    observed_ranges = 0
    for (mb_idx, block_idx), block_offsets in offsets.items():
        if block_idx >= 16 or block_offsets.get("bit_length", 0) <= 0:
            continue
        ranges = block_offsets.get("coefficient_bit_ranges")
        if ranges is None:
            continue
        assert len(ranges) == len(blocks[(mb_idx, block_idx)])
        block_start = block_offsets["start_bit"]
        block_end = block_offsets["end_bit"]
        assert all(
            bit_range is None or block_start <= bit_range[0] < bit_range[1] <= block_end
            for bit_range in ranges
        )
        observed_ranges += 1
    assert observed_ranges > 0, "traceable parser did not retain any luma coefficient bit ranges"


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
        run_test(
            "traceable_h264_parser_retains_absolute_ranges_only_when_requested",
            t_traceable_h264_parser_retains_absolute_ranges_only_when_requested,
        ),
    ]
    raise SystemExit(summarise(results, "CAVLC coefficient bit ranges"))


if __name__ == "__main__":
    main()
