"""Tests for bounded-memory raw CAVLC capacity measurements."""

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from benchmark.streaming_capacity_scan import (
    _scan_segments,
    frame_cut_points,
    main,
    summarize_raw_capacity,
    validate_segment_partition,
)
from src.runtest._helpers import run_test, section, summarise


def t_frame_cut_points_exclude_zero_and_terminal_boundary():
    assert frame_cut_points(300, 100) == [100, 200]
    assert frame_cut_points(250, 100) == [100, 200]


def t_rejects_invalid_frame_partitions():
    invalid = (
        (0, 100, [100]),
        (300, 0, [100, 100, 100]),
        (300, 100, []),
        (300, 100, [100, 99, 101]),
        (300, 100, [100, 100]),
    )
    for total_frames, frames_per_segment, observed in invalid:
        try:
            validate_segment_partition(total_frames, frames_per_segment, observed)
        except ValueError:
            continue
        raise AssertionError(f"invalid partition was accepted: {observed}")


def t_accepts_complete_full_and_partial_final_segment():
    assert validate_segment_partition(300, 100, [100, 100, 100]) == 300
    assert validate_segment_partition(250, 100, [100, 100, 50]) == 250


def t_short_video_is_analyzed_as_one_segment_without_ffmpeg_split():
    with tempfile.TemporaryDirectory() as temp_dir:
        video = Path(temp_dir) / "short.h264"
        video.write_bytes(b"short-video")
        fake_analysis = ([], {}, {}, {}, {}, [(0, 0, 1), (1, 0, 1)])
        with patch("benchmark._common.load_or_build_benchmark_analysis", return_value=fake_analysis), patch(
            "benchmark.streaming_capacity_scan._run"
        ) as run_command:
            frame_counts, raw_bits = _scan_segments(video, 100, 50)
        assert frame_counts == [50]
        assert raw_bits == [2]
        run_command.assert_not_called()


def t_raw_capacity_report_is_explicitly_not_quality_validated():
    report = summarize_raw_capacity(
        asset="clip.h264",
        frame_count=250,
        frames_per_segment=100,
        segment_frame_counts=[100, 100, 50],
        raw_safe_bits_by_segment=[1000, 2000, 500],
        proof_bytes=400,
        framing_bytes=8,
    )
    assert report["raw_safe_carrier_bits"] == 3500
    assert report["raw_capacity_assessment"]["required_bits"] == 3264
    assert report["raw_capacity_assessment"]["fits"] is True
    assert report["patchability_validated"] is False
    assert report["quality_validated"] is False
    assert report["raw_fit_is_sufficient_for_embedding"] is False


def t_report_rejects_mismatched_segment_arrays():
    try:
        summarize_raw_capacity(
            asset="clip.h264",
            frame_count=100,
            frames_per_segment=100,
            segment_frame_counts=[100],
            raw_safe_bits_by_segment=[],
            proof_bytes=1,
        )
    except ValueError:
        return
    raise AssertionError("mismatched measurements were accepted")


def t_cli_writes_report_for_a_valid_measured_partition():
    with tempfile.TemporaryDirectory() as temp_dir:
        video = Path(temp_dir) / "clip.h264"
        proof = Path(temp_dir) / "proof.bin"
        report_path = Path(temp_dir) / "report.json"
        video.write_bytes(b"test-video")
        proof.write_bytes(b"proof")

        with patch("benchmark.streaming_capacity_scan._probe_frame_count", return_value=2), patch(
            "benchmark.streaming_capacity_scan._scan_segments", return_value=([2], [10])
        ), patch("benchmark.streaming_capacity_scan._ffmpeg_version", return_value="ffmpeg test"):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = main([
                    "--video", str(video),
                    "--proof-artifact", str(proof),
                    "--frames-per-segment", "2",
                    "--output", str(report_path),
                ])

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert result == 0
        assert report["raw_safe_carrier_bits"] == 10
        assert report["quality_validated"] is False
        emitted = json.loads(stdout.getvalue())
        assert emitted["asset"] == "clip.h264"
        assert emitted["proof_artifact"] == "proof.bin"


def main_test():
    section("Phase 13 - Streaming Raw Capacity Scan")
    results = [
        run_test("frame_cut_points_exclude_zero_and_terminal_boundary", t_frame_cut_points_exclude_zero_and_terminal_boundary),
        run_test("rejects_invalid_frame_partitions", t_rejects_invalid_frame_partitions),
        run_test("accepts_complete_full_and_partial_final_segment", t_accepts_complete_full_and_partial_final_segment),
        run_test("short_video_is_analyzed_as_one_segment_without_ffmpeg_split", t_short_video_is_analyzed_as_one_segment_without_ffmpeg_split),
        run_test("raw_capacity_report_is_explicitly_not_quality_validated", t_raw_capacity_report_is_explicitly_not_quality_validated),
        run_test("report_rejects_mismatched_segment_arrays", t_report_rejects_mismatched_segment_arrays),
        run_test("cli_writes_report_for_a_valid_measured_partition", t_cli_writes_report_for_a_valid_measured_partition),
    ]
    raise SystemExit(summarise(results, "Phase 13"))


if __name__ == "__main__":
    main_test()
