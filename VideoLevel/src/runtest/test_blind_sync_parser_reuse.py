"""Regression tests preventing redundant H.264 parser allocations."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from src.blind_sync import (
    BlindOperatingContract,
    extract_blind_video_payload,
    pack_blind_payload,
)
from src.core.analysis_cache import _build_reconstruction_context
from src.video_canonicalization import canonical_video_sha256


def test_reconstruction_context_keeps_the_parser_that_was_already_built(tmp_path):
    video = tmp_path / "cover.h264"
    video.write_bytes(b"test")
    parser = Mock(nal_units=[])

    context = _build_reconstruction_context(video, parser=parser)

    assert context["parser"] is parser


def test_blind_extractor_reuses_decoded_analysis_for_header_and_payload():
    payload = b"video-only-test"
    envelope = pack_blind_payload(payload)
    analysis = ([], {}, {}, {}, {}, [])
    contract = BlindOperatingContract(
        stable_carriers_only=True,
        require_bitstream_patchable=True,
        max_modifications_per_block=1,
    )

    def derive_positions(_video, _key, required_bits, _contract, **_kwargs):
        return [(0, 0, index) for index in range(required_bits)], Mock()

    with (
        patch("src.blind_sync.load_or_build_video_analysis", return_value=analysis),
        patch(
            "src.blind_sync.derive_blind_positions_operating_contract",
            side_effect=derive_positions,
        ),
        patch(
            "src.core.pipeline._extract_bits_from_decoded_analysis",
            side_effect=[envelope[:14], envelope],
        ) as extract_bits,
        patch("src.core.pipeline.H264BitstreamParser") as parser_factory,
    ):
        result = extract_blind_video_payload("stego.h264", b"sync key", contract)

    assert result.payload == payload
    parser_factory.assert_not_called()
    assert extract_bits.call_args_list == [
        call(
            stego_video_path="stego.h264",
            embed_safe_positions=[(0, 0, index) for index in range(14 * 8)],
            frame_verified_data={},
            nC_map={},
            payload_bits=14 * 8,
            max_modifications_per_block=1,
        ),
        call(
            stego_video_path="stego.h264",
            embed_safe_positions=[(0, 0, index) for index in range(len(envelope) * 8)],
            frame_verified_data={},
            nC_map={},
            payload_bits=len(envelope) * 8,
            max_modifications_per_block=1,
        ),
    ]


def test_canonical_video_hash_accepts_preparsed_parser_and_frame_data(tmp_path):
    video = tmp_path / "stego.h264"
    video.write_bytes(b"preparsed fixture")
    nal = SimpleNamespace(
        nal_unit_type=5,
        forbidden_zero_bit=0,
        nal_ref_idc=3,
        start_code_size=4,
        rbsp_byte=bytes.fromhex("b696"),
    )
    parser = SimpleNamespace(nal_units=[nal])
    frame_data = {
        0: (
            {(0, 0): {"start_bit": 8, "end_bit": 11}},
            {(0, 0): [3] + [0] * 15},
            bytes.fromhex("b696"),
        )
    }

    with (
        patch("src.bitstream.h264.H264BitstreamParser") as parser_factory,
        patch("src.core.pipeline.extract_all_idr_blocks") as extract_blocks,
    ):
        digest = canonical_video_sha256(
            video,
            [(0, 0, 0)],
            parser=parser,
            frame_verified_data=frame_data,
        )

    assert len(digest) == 64
    parser_factory.assert_not_called()
    extract_blocks.assert_not_called()


def test_canonical_video_hash_rejects_incomplete_preparsed_context(tmp_path):
    video = tmp_path / "stego.h264"
    video.write_bytes(b"preparsed fixture")

    try:
        canonical_video_sha256(video, [(0, 0, 0)], parser=SimpleNamespace(nal_units=[]))
    except ValueError as error:
        assert "provided together" in str(error)
    else:
        raise AssertionError("incomplete parser context should be rejected")
