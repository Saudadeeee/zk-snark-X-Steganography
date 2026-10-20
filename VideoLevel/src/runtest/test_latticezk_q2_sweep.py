"""Automatic chunk sizing of the evaluation sweep from measured capacity."""

from __future__ import annotations

import json

from benchmark import latticezk_q2_sweep as sweep


def _capacity(tmp_path, name: str, min_chunk: int, segments: int, total: int | None = None) -> None:
    (tmp_path / f"capacity_{name}.json").write_text(json.dumps([{
        "min_chunk_bytes_supported": min_chunk, "segments_scanned": segments,
        "segments_total": total or segments,
    }]), encoding="utf-8")


def test_chunk_stays_below_measured_capacity_and_fits(tmp_path) -> None:
    _capacity(tmp_path, "case", 5_946, 3)
    chunk = sweep._auto_chunk({"name": "case", "registered": True}, tmp_path / "v.h264",
                              tmp_path, tmp_path / "log")
    assert chunk == int(5_946 * sweep.CHUNK_MARGIN)
    assert -(-7_589 // chunk) <= 3


def test_envelope_that_does_not_fit_is_reported(tmp_path) -> None:
    _capacity(tmp_path, "small", 1_101, 3)
    assert sweep._auto_chunk({"name": "small", "registered": True}, tmp_path / "v.h264",
                             tmp_path, tmp_path / "log") is None
    _capacity(tmp_path, "inband", 3_888, 3)
    assert sweep._auto_chunk({"name": "inband", "registered": False}, tmp_path / "v.h264",
                             tmp_path, tmp_path / "log") is None


def test_chunk_never_exceeds_the_chunk_format_limit(tmp_path) -> None:
    from src.blind_payload_chunks import MAX_CHUNK_BYTES

    _capacity(tmp_path, "huge", 68_680, 1)
    chunk = sweep._auto_chunk({"name": "huge", "registered": True}, tmp_path / "v.h264",
                              tmp_path, tmp_path / "log")
    assert chunk == MAX_CHUNK_BYTES


def test_density_spreads_the_envelope_over_more_segments(tmp_path) -> None:
    _capacity(tmp_path, "base", 13_000, 3, total=6)
    full = sweep._auto_chunk({"name": "base"}, tmp_path / "v.h264", tmp_path, tmp_path / "log")
    quarter = sweep._auto_chunk({"name": "q", "capacity_from": "base", "density": 0.25},
                                tmp_path / "v.h264", tmp_path, tmp_path / "log")
    assert quarter == int(13_000 * sweep.CHUNK_MARGIN * 0.25)
    assert -(-7_589 // full) == 1 and -(-7_589 // quarter) == 3
    # 10% needs more segments than the clip has.
    assert sweep._auto_chunk({"name": "t", "capacity_from": "base", "density": 0.05},
                             tmp_path / "v.h264", tmp_path, tmp_path / "log") is None


def test_capacity_from_another_clip_or_carrier_is_refused(tmp_path) -> None:
    (tmp_path / "capacity_base.json").write_text(json.dumps([{
        "video": "other.h264", "carrier": "magnitude",
        "min_chunk_bytes_supported": 13_000, "segments_scanned": 3, "segments_total": 6,
    }]), encoding="utf-8")
    assert sweep._auto_chunk({"name": "x", "capacity_from": "base"}, tmp_path / "v.h264",
                             tmp_path, tmp_path / "log") is None
    (tmp_path / "capacity_base.json").write_text(json.dumps([{
        "video": "v.h264", "carrier": "magnitude",
        "min_chunk_bytes_supported": 13_000, "segments_scanned": 3, "segments_total": 6,
    }]), encoding="utf-8")
    assert sweep._auto_chunk({"name": "x", "capacity_from": "base", "carrier": "t1"},
                             tmp_path / "v.h264", tmp_path, tmp_path / "log") is None
    assert sweep._auto_chunk({"name": "x", "capacity_from": "base"}, tmp_path / "v.h264",
                             tmp_path, tmp_path / "log") is not None
