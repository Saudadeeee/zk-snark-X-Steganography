"""Unit tests for normalization of embedded H.264 coefficient carriers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtest._helpers import run_test, section, summarise
from src.video_canonicalization import (
    canonical_h264_digest,
    canonical_video_sha256,
    canonicalize_carrier_coefficients,
)


def _pack_bits(bits: str) -> bytes:
    packed = bytearray((len(bits) + 7) // 8)
    for index, bit in enumerate(bits):
        if bit == "1":
            packed[index // 8] |= 1 << (7 - index % 8)
    return bytes(packed)


def t_sign_carriers_normalize_to_positive_trailing_one() -> None:
    coefficients = [(3, 7, [0, -1, 2] + [0] * 13)]

    normalized = canonicalize_carrier_coefficients(coefficients, [(3, 7, -2)])

    assert normalized == [(3, 7, [0, 1, 2] + [0] * 13)]
    assert coefficients[0][2][1] == -1, "input coefficient data must remain unchanged"


def t_lsb_carriers_normalize_magnitude_and_handle_unit_value() -> None:
    coefficients = [(1, 4, [3, -5, 1] + [0] * 13)]

    normalized = canonicalize_carrier_coefficients(
        coefficients, [(1, 4, 0), (1, 4, 1), (1, 4, 2)]
    )

    assert normalized == [(1, 4, [2, -4, 2] + [0] * 13)]


def t_native_odd_anchor_pairs_are_invariant_and_threshold_checked() -> None:
    carrier = [(1, 4, 0), (1, 4, 1)]
    odd_levels = [(1, 4, [5, -7] + [0] * 14)]
    even_levels = [(1, 4, [6, -8] + [0] * 14)]
    assert canonicalize_carrier_coefficients(
        odd_levels, carrier, magnitude_pair="native_odd_anchor_v1"
    ) == []
    assert canonicalize_carrier_coefficients(
        even_levels, carrier, magnitude_pair="native_odd_anchor_v1"
    ) == [(1, 4, [5, -7] + [0] * 14)]
    try:
        canonicalize_carrier_coefficients(
            [(1, 4, [4] + [0] * 15)], [(1, 4, 0)],
            magnitude_pair="native_odd_anchor_v1",
        )
    except ValueError as error:
        assert "below magnitude five" in str(error)
    else:
        raise AssertionError("native carrier below threshold must be rejected")


def t_empty_carrier_set_returns_no_modifications() -> None:
    assert canonicalize_carrier_coefficients([(1, 0, [1] + [0] * 15)], []) == []


def t_missing_block_is_rejected() -> None:
    try:
        canonicalize_carrier_coefficients([(1, 0, [1] + [0] * 15)], [(2, 0, 0)])
    except ValueError as error:
        assert "unknown coefficient block" in str(error)
    else:
        raise AssertionError("unknown carrier block must be rejected")


def t_invalid_carrier_index_or_non_trailing_sign_is_rejected() -> None:
    coefficients = [(1, 0, [2, 0] + [0] * 14)]

    for position in ((1, 0, 16), (1, 0, -1)):
        try:
            canonicalize_carrier_coefficients(coefficients, [position])
        except ValueError:
            continue
        raise AssertionError(f"invalid carrier must be rejected: {position}")


def t_duplicate_carrier_is_rejected() -> None:
    coefficients = [(1, 0, [3] + [0] * 15)]
    try:
        canonicalize_carrier_coefficients(coefficients, [(1, 0, 0), (1, 0, 0)])
    except ValueError as error:
        assert "duplicate carrier" in str(error)
    else:
        raise AssertionError("duplicate carrier must be rejected")


def t_overlapping_global_idr_ranges_are_rejected() -> None:
    frames = {
        0: ({}, {(5, 0): [5] + [0] * 15}, b"\x80"),
        5: ({}, {(5, 0): [5] + [0] * 15}, b"\x80"),
    }
    try:
        canonical_h264_digest([], frames, [(5, 0, 0)])
    except ValueError as error:
        assert "overlaps another frame" in str(error)
    else:
        raise AssertionError("ambiguous global IDR frame ranges must be rejected")


def t_empty_carrier_list_hashes_original_without_parsing() -> None:
    import hashlib
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as temp_dir:
        source = Path(temp_dir) / "video.h264"
        source.write_bytes(b"unchanged H.264 bytes")
        with patch("src.bitstream.h264.H264BitstreamParser") as parser:
            assert canonical_video_sha256(source, []) == hashlib.sha256(source.read_bytes()).hexdigest()
            parser.assert_not_called()


def t_canonical_digest_masks_variable_length_carrier_codewords() -> None:
    from types import SimpleNamespace

    def parsed_nal(level: int, carrier_code: str):
        prefix = "10110110"
        suffix = "10010110"
        bits = prefix + carrier_code + suffix
        rbsp = _pack_bits(bits)
        nal = SimpleNamespace(
            nal_unit_type=5,
            forbidden_zero_bit=0,
            nal_ref_idc=3,
            start_code_size=4,
            rbsp_byte=rbsp,
        )
        offsets = {(0, 0): {"start_bit": len(prefix), "end_bit": len(prefix) + len(carrier_code)}}
        blocks = {(0, 0): [level] + [0] * 15}
        return nal, {0: (offsets, blocks, rbsp)}

    cover_nal, cover_frames = parsed_nal(3, "101")
    stego_nal, stego_frames = parsed_nal(2, "11001")
    positions = [(0, 0, 0)]

    assert canonical_h264_digest([cover_nal], cover_frames, positions) == canonical_h264_digest(
        [stego_nal], stego_frames, positions
    )


def t_canonical_digest_still_binds_noncarrier_bits() -> None:
    from types import SimpleNamespace

    def parsed_nal(prefix: str):
        carrier = "101"
        suffix = "10010110"
        bits = prefix + carrier + suffix
        rbsp = _pack_bits(bits)
        nal = SimpleNamespace(
            nal_unit_type=5,
            forbidden_zero_bit=0,
            nal_ref_idc=3,
            start_code_size=4,
            rbsp_byte=rbsp,
        )
        offsets = {(0, 0): {"start_bit": len(prefix), "end_bit": len(prefix) + len(carrier)}}
        blocks = {(0, 0): [3] + [0] * 15}
        return nal, {0: (offsets, blocks, rbsp)}

    first_nal, first_frames = parsed_nal("10110110")
    altered_nal, altered_frames = parsed_nal("10110111")
    positions = [(0, 0, 0)]

    assert canonical_h264_digest([first_nal], first_frames, positions) != canonical_h264_digest(
        [altered_nal], altered_frames, positions
    )


def t_video_hash_uses_parsed_nal_and_carrier_ranges() -> None:
    import tempfile
    from types import SimpleNamespace
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as temp_dir:
        source = Path(temp_dir) / "cover.h264"
        source.write_bytes(b"test H.264 stream")
        nal = SimpleNamespace(nal_unit_type=5)
        frames = {0: ({}, {}, b"rbsp")}
        positions = [(0, 0, 0)]
        with (
            patch("src.bitstream.h264.H264BitstreamParser") as parser_type,
            patch("src.core.pipeline.extract_all_idr_blocks", return_value=([], frames, {}, {}, {})),
            patch("src.video_canonicalization.canonical_h264_digest", return_value="ab" * 32) as digest,
        ):
            parser = parser_type.return_value
            parser.nal_units = [nal]
            assert canonical_video_sha256(source, positions) == "ab" * 32
            digest.assert_called_once_with([nal], frames, positions)


def main() -> None:
    section("Video carrier canonicalization")
    results = [
        run_test("sign_carriers_normalize_to_positive_trailing_one", t_sign_carriers_normalize_to_positive_trailing_one),
        run_test("lsb_carriers_normalize_magnitude_and_handle_unit_value", t_lsb_carriers_normalize_magnitude_and_handle_unit_value),
        run_test("native_odd_anchor_pairs_are_invariant_and_threshold_checked", t_native_odd_anchor_pairs_are_invariant_and_threshold_checked),
        run_test("empty_carrier_set_returns_no_modifications", t_empty_carrier_set_returns_no_modifications),
        run_test("missing_block_is_rejected", t_missing_block_is_rejected),
        run_test("invalid_carrier_index_or_non_trailing_sign_is_rejected", t_invalid_carrier_index_or_non_trailing_sign_is_rejected),
        run_test("duplicate_carrier_is_rejected", t_duplicate_carrier_is_rejected),
        run_test("overlapping_global_idr_ranges_are_rejected", t_overlapping_global_idr_ranges_are_rejected),
        run_test("empty_carrier_list_hashes_original_without_parsing", t_empty_carrier_list_hashes_original_without_parsing),
        run_test("canonical_digest_masks_variable_length_carrier_codewords", t_canonical_digest_masks_variable_length_carrier_codewords),
        run_test("canonical_digest_still_binds_noncarrier_bits", t_canonical_digest_still_binds_noncarrier_bits),
        run_test("video_hash_uses_parsed_nal_and_carrier_ranges", t_video_hash_uses_parsed_nal_and_carrier_ranges),
    ]
    raise SystemExit(summarise(results, "Video carrier canonicalization"))


if __name__ == "__main__":
    main()
