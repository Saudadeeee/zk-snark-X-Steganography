from pathlib import Path
from types import SimpleNamespace

import pytest

from src.bitstream.bitstream_ops import BitstreamReconstructor
from src.bitstream.h264 import H264BitstreamParser, TraceableCAVLCParser
from src.core import pipeline as video_pipeline


def test_deadline_chroma_dc_fixture_parses_without_recovery():
    """Regression: chroma-DC total_zeros must preserve the next MB boundary."""
    video = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "encoded"
        / "deadline_cif_q22_g1_600f.h264"
    )
    assert video.is_file(), f"required H.264 regression fixture is missing: {video}"

    parser = H264BitstreamParser(str(video))
    parser.parse()
    reconstructor = BitstreamReconstructor()
    sps = pps = None
    idr = None
    for nal in parser.nal_units:
        nal_type = int(nal.nal_unit_type)
        if nal_type == 7:
            sps = reconstructor._parse_sps_from_nal(nal)
        elif nal_type == 8:
            pps = reconstructor._parse_pps_from_nal(nal)
        elif nal_type == 5:
            idr = nal
            break

    assert sps is not None and pps is not None and idr is not None
    result = TraceableCAVLCParser().extract_with_offsets(idr, sps, pps)

    assert result["parse_trusted"] is True
    assert result["parse_integrity_issues"] == []
    assert result["num_mbs"] == 396
    assert result["offsets"]


def test_supported_all_intra_cavlc_fixture_parses_without_recovery():
    """Keep a real, independently decodable success fixture for the trust gate."""
    video = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "encoded"
        / "foreman_cif_q22_g1.h264"
    )
    assert video.is_file(), f"required H.264 success fixture is missing: {video}"

    parser = H264BitstreamParser(str(video))
    parser.parse()
    reconstructor = BitstreamReconstructor()
    sps = pps = idr = None
    for nal in parser.nal_units:
        nal_type = int(nal.nal_unit_type)
        if nal_type == 7:
            sps = reconstructor._parse_sps_from_nal(nal)
        elif nal_type == 8:
            pps = reconstructor._parse_pps_from_nal(nal)
        elif nal_type == 5:
            idr = nal
            break

    assert sps is not None and pps is not None and idr is not None
    result = TraceableCAVLCParser().extract_with_offsets(idr, sps, pps)

    assert result["parse_trusted"] is True
    assert result["parse_integrity_issues"] == []
    assert result["num_mbs"] == 396
    assert result["offsets"]


def test_i16x16_luma_dc_context_uses_neighboring_luma_4x4_blocks():
    """A valid GOP8 fixture previously desynced at MB 53 on the DC nC context."""
    video = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "encoded"
        / "foreman_cif_g8_300f_b800k.h264"
    )
    assert video.is_file(), f"required H.264 regression fixture is missing: {video}"

    parser = H264BitstreamParser(str(video))
    parser.parse()
    reconstructor = BitstreamReconstructor()
    sps = pps = idr = None
    for nal in parser.nal_units:
        nal_type = int(nal.nal_unit_type)
        if nal_type == 7:
            sps = reconstructor._parse_sps_from_nal(nal)
        elif nal_type == 8:
            pps = reconstructor._parse_pps_from_nal(nal)
        elif nal_type == 5:
            idr = nal
            break

    assert sps is not None and pps is not None and idr is not None
    result = TraceableCAVLCParser().extract_with_offsets(idr, sps, pps)

    assert result["parse_trusted"] is True
    assert result["parse_integrity_issues"] == []
    assert result["num_mbs"] == 396


def test_pipeline_refuses_offsets_after_heuristic_parser_recovery(monkeypatch):
    class FakeParser:
        def __init__(self):
            self.nal_units = [
                SimpleNamespace(nal_unit_type=7),
                SimpleNamespace(nal_unit_type=8),
                SimpleNamespace(nal_unit_type=5, rbsp_byte=b"\x00"),
            ]

    class FakeReconstructor:
        def _parse_sps_from_nal(self, _nal):
            return SimpleNamespace(
                pic_width_in_mbs_minus1=0,
                pic_height_in_map_units_minus1=0,
            )

        def _parse_pps_from_nal(self, _nal):
            return object()

    class RecoveredParser:
        def extract_with_offsets(self, *_args, **_kwargs):
            return {
                "blocks": {(0, 0): [1] + [0] * 15},
                "offsets": {(0, 0): {"start_bit": 0, "end_bit": 1, "bit_length": 1}},
                "mb_metadata": {},
                "parse_trusted": False,
                "parse_integrity_issues": ["heuristic_resync:mb=0:bit=12"],
            }

    monkeypatch.setattr(video_pipeline, "TraceableCAVLCParser", RecoveredParser)
    with pytest.raises(RuntimeError, match="untrusted CAVLC parse"):
        video_pipeline.extract_all_idr_blocks(
            "unused.h264", FakeReconstructor(), parser=FakeParser()
        )
