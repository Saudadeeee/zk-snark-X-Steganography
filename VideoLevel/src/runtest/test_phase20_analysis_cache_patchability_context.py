"""Regression tests for using exact NAL-derived patchability context."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from src.bitstream.bitstream_io import BitstreamWriter
from src.bitstream.cavlc import CAVLCEncoder
from src.core import analysis_cache
from src.core.stego import CAVLCSafetyFilter


def test_verified_context_only_exposes_sign_bits_from_a_canonical_t1_block() -> None:
    coefficients = [0, -2, -1, -1] + [0] * 12
    invalid_writer = BitstreamWriter()
    with pytest.raises(ValueError, match="must match the coefficient block"):
        CAVLCEncoder(invalid_writer).encode_block_cavlc(
            coefficients,
            nC=2,
            max_num_coeff=16,
            override_trailing_ones=1,
        )

    writer = BitstreamWriter()
    CAVLCEncoder(writer).encode_block_cavlc(
        coefficients,
        nC=2,
        max_num_coeff=16,
        override_trailing_ones=2,
    )
    bit_length = writer.get_bit_position()
    rbsp = writer.get_bytes(align=False) + bytes(8)
    offset = {
        "start_bit": 0,
        "end_bit": bit_length,
        "bit_length": bit_length,
        "nC": 2,
        "max_num_coeff": 16,
    }
    frame_verified_data = {
        0: ({(0, 11): offset}, {(0, 11): coefficients}, rbsp)
    }
    without_context = CAVLCSafetyFilter().get_safe_positions(
        [(0, 11, coefficients)], nC_map={(0, 11): 2}
    )
    with_context = CAVLCSafetyFilter().get_safe_positions(
        [(0, 11, coefficients)],
        nC_map={(0, 11): 2},
        t1_override_map={},
        nal_length_map={(0, 11): bit_length},
        frame_verified_data=frame_verified_data,
    )

    # Negative carrier indexes encode sign bits. These are offered only after
    # the exact NAL block has been decoded and validated; -3 is coeff[2].
    assert without_context == []
    assert set(with_context) == {(0, 11, -3), (0, 11, -4)}


def test_analysis_cache_passes_verified_frames_into_safety_filter(tmp_path) -> None:
    video = tmp_path / "cover.h264"
    video.write_bytes(b"fixture")
    verified_frames = {0: ({(0, 0): {"nC": 2}}, {(0, 0): [1]}, b"rbsp")}
    extracted = ([(0, 0, [1])], verified_frames, {(0, 0): 2}, {(0, 0): 17}, {})
    parser = Mock(nal_units=[])
    safety_filter = Mock()
    safety_filter.get_safe_positions.return_value = [(0, 0, 1)]

    with (
        patch.object(analysis_cache, "H264BitstreamParser", return_value=parser),
        patch.object(analysis_cache, "BitstreamReconstructor"),
        patch.object(analysis_cache, "extract_all_idr_blocks", return_value=extracted),
        patch.object(analysis_cache, "CAVLCSafetyFilter", return_value=safety_filter),
    ):
        result = analysis_cache.load_or_build_video_analysis(
            video,
            use_cache=False,
        )

    assert result[1] is verified_frames
    safety_filter.get_safe_positions.assert_called_once()
    _, kwargs = safety_filter.get_safe_positions.call_args
    assert kwargs["frame_verified_data"] is verified_frames


def test_analysis_cache_requests_stable_only_safety_profile(tmp_path) -> None:
    video = tmp_path / "stable-cover.h264"
    video.write_bytes(b"fixture")
    verified_frames = {0: ({(0, 0): {"nC": 2}}, {(0, 0): [1]}, b"rbsp")}
    extracted = ([(0, 0, [1])], verified_frames, {(0, 0): 2}, {(0, 0): 17}, {})
    parser = Mock(nal_units=[])
    safety_filter = Mock()
    safety_filter.get_safe_positions.return_value = [(0, 0, 1)]

    with (
        patch.object(analysis_cache, "H264BitstreamParser", return_value=parser),
        patch.object(analysis_cache, "BitstreamReconstructor"),
        patch.object(analysis_cache, "extract_all_idr_blocks", return_value=extracted),
        patch.object(analysis_cache, "CAVLCSafetyFilter", return_value=safety_filter),
    ):
        analysis_cache.load_or_build_video_analysis(
            video,
            use_cache=False,
            stable_blind_only=True,
        )

    _, kwargs = safety_filter.get_safe_positions.call_args
    assert kwargs["stable_carriers_only"] is True
