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
    next_patchability_target,
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
            frame_counts, raw_bits, patchable_bits = _scan_segments(video, 100, 50)
        assert frame_counts == [50]
        assert raw_bits == [2]
        assert patchable_bits is None
        run_command.assert_not_called()


def t_short_video_can_scan_only_blind_stable_carriers():
    with tempfile.TemporaryDirectory() as temp_dir:
        video = Path(temp_dir) / "short.h264"
        video.write_bytes(b"short-video")
        fake_analysis = ([], {}, {}, {}, {}, [(0, 0, 1)])
        with patch(
            "benchmark._common.load_or_build_benchmark_analysis",
            return_value=fake_analysis,
        ) as analyze:
            frame_counts, raw_bits, patchable_bits = _scan_segments(
                video,
                100,
                10,
                stable_blind_only=True,
            )

        assert frame_counts == [10]
        assert raw_bits == [1]
        assert patchable_bits is None
        analyze.assert_called_once_with(
            video.resolve(),
            force=True,
            interleave_positions=False,
            stable_blind_only=True,
        )


def t_analysis_requests_stable_carriers_without_interleaving():
    from benchmark._common import load_or_build_benchmark_analysis

    coefficients = [(0, 0, [0, 4] + [0] * 14)]
    with tempfile.TemporaryDirectory() as temp_dir:
        video = Path(temp_dir) / "clip.h264"
        video.write_bytes(b"video")
        with patch("benchmark._common.load_or_extract_idr_blocks", return_value=(
            coefficients, {}, {}, {}, {}
        )), patch("src.core.stego.CAVLCSafetyFilter.get_safe_positions", return_value=[]) as filter_call:
            load_or_build_benchmark_analysis(
                video,
                force=True,
                interleave_positions=False,
                stable_blind_only=True,
            )

    filter_call.assert_called_once_with(
        coefficients,
        nC_map={},
        nal_length_map={},
        t1_override_map={},
        stable_carriers_only=True,
        interleave_positions=False,
    )


def t_patchability_target_balances_remaining_bits_over_chunks():
    assert next_patchability_target(1053680, 0, 145984, 30) == 35123
    assert next_patchability_target(1053680, 35123, 145984, 29) == 35123
    assert next_patchability_target(1053680, 1053680, 145984, 0) == 0


def t_patchability_target_is_bounded_by_raw_chunk_capacity():
    assert next_patchability_target(1000, 0, 100, 3) == 100
    assert next_patchability_target(1000, 100, 800, 2) == 450
    assert next_patchability_target(1000, 400, 800, 2) == 300


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
    assert report["patchability_validation_scope"] == "not_measured"
    assert report["quality_validated"] is False
    assert report["raw_fit_is_sufficient_for_embedding"] is False


def t_patchability_report_confirms_exact_payload_only_when_enough_positions_passes():
    common = {
        "asset": "clip.h264",
        "frame_count": 250,
        "frames_per_segment": 100,
        "segment_frame_counts": [100, 100, 50],
        "raw_safe_bits_by_segment": [10000, 10000, 10000],
        "proof_bytes": 400,
        "framing_bytes": 8,
    }
    confirmed = summarize_raw_capacity(
        **common,
        patchable_safe_bits_by_segment=[1200, 1200, 864],
    )
    assert confirmed["patchability_confirmed_bits"] == 3264
    assert confirmed["patchability_validated"] is True
    assert confirmed["patchability_target_bits"] == 3264
    assert confirmed["patchability_target_met"] is True
    assert confirmed["patchability_validation_scope"] == "requested_target_only"
    assert confirmed["patchability_capacity_upper_bound_bits"] == 30000
    assert confirmed["patchability_total_capacity_measured"] is False
    assert "patchability_capacity_assessment" not in confirmed
    assert confirmed["patchability_result"] == "proof_payload_positions_confirmed"
    assert confirmed["quality_validated"] is False

    inconclusive = summarize_raw_capacity(
        **common,
        patchable_safe_bits_by_segment=[1000, 500, 500],
    )
    assert inconclusive["patchability_validated"] is False
    assert inconclusive["patchability_target_bits"] == 3264
    assert inconclusive["patchability_target_met"] is False
    assert inconclusive["patchability_capacity_upper_bound_bits"] == 30000
    assert inconclusive["patchability_total_capacity_measured"] is False
    assert inconclusive["patchability_result"] == "inconclusive_candidate_shortfall"
    assert inconclusive["insufficient_patchable_candidates_proven"] is False


def t_report_rejects_patchable_counts_above_raw_candidates():
    try:
        summarize_raw_capacity(
            asset="clip.h264",
            frame_count=100,
            frames_per_segment=100,
            segment_frame_counts=[100],
            raw_safe_bits_by_segment=[10],
            proof_bytes=1,
            patchable_safe_bits_by_segment=[11],
        )
    except ValueError:
        return
    raise AssertionError("patchable positions above raw candidates were accepted")


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
            "benchmark.streaming_capacity_scan._scan_segments", return_value=([2], [10], None)
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
        assert report["carrier_profile"] == "all_safe_candidates"
        assert report["quality_validated"] is False
        emitted = json.loads(stdout.getvalue())
        assert emitted["asset"] == "clip.h264"
        assert emitted["proof_artifact"] == "proof.bin"


def t_cli_selects_blind_stable_profile():
    with tempfile.TemporaryDirectory() as temp_dir:
        video = Path(temp_dir) / "clip.h264"
        proof = Path(temp_dir) / "proof.bin"
        report_path = Path(temp_dir) / "report.json"
        video.write_bytes(b"test-video")
        proof.write_bytes(b"proof")

        with patch("benchmark.streaming_capacity_scan._probe_frame_count", return_value=2), patch(
            "benchmark.streaming_capacity_scan._scan_segments", return_value=([2], [3], None)
        ) as scan_segments, patch(
            "benchmark.streaming_capacity_scan._ffmpeg_version", return_value="ffmpeg test"
        ):
            result = main([
                "--video", str(video),
                "--proof-artifact", str(proof),
                "--frames-per-segment", "2",
                "--stable-blind-carriers",
                "--output", str(report_path),
            ])

        assert result == 0
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["carrier_profile"] == "blind_stable_candidates"
        assert report["blind_extraction_validated"] is False
        assert scan_segments.call_args.kwargs["stable_blind_only"] is True


def t_cli_accepts_explicit_payload_size_without_proof_file():
    with tempfile.TemporaryDirectory() as temp_dir:
        video = Path(temp_dir) / "clip.h264"
        report_path = Path(temp_dir) / "report.json"
        video.write_bytes(b"test-video")

        with patch("benchmark.streaming_capacity_scan._probe_frame_count", return_value=2), patch(
            "benchmark.streaming_capacity_scan._scan_segments", return_value=([2], [100], None)
        ), patch("benchmark.streaming_capacity_scan._ffmpeg_version", return_value="ffmpeg test"):
            result = main([
                "--video", str(video),
                "--target-payload-bytes", "1916177",
                "--frames-per-segment", "2",
                "--stable-blind-carriers",
                "--output", str(report_path),
            ])

        assert result == 0
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["target_payload_bytes"] == 1_916_177
        assert report["payload_size_source"] == "explicit_target_bytes"
        assert report["proof_artifact"] is None
        assert report["proof_bytes"] is None
        assert report["raw_capacity_assessment"]["target_payload_bytes"] == 1_916_177
        assert report["raw_capacity_assessment"]["required_bits"] == 15_329_544


def main_test():
    section("Phase 13 - Streaming Raw Capacity Scan")
    results = [
        run_test("frame_cut_points_exclude_zero_and_terminal_boundary", t_frame_cut_points_exclude_zero_and_terminal_boundary),
        run_test("rejects_invalid_frame_partitions", t_rejects_invalid_frame_partitions),
        run_test("accepts_complete_full_and_partial_final_segment", t_accepts_complete_full_and_partial_final_segment),
        run_test("short_video_is_analyzed_as_one_segment_without_ffmpeg_split", t_short_video_is_analyzed_as_one_segment_without_ffmpeg_split),
        run_test("short_video_can_scan_only_blind_stable_carriers", t_short_video_can_scan_only_blind_stable_carriers),
        run_test("analysis_requests_stable_carriers_without_interleaving", t_analysis_requests_stable_carriers_without_interleaving),
        run_test("patchability_target_balances_remaining_bits_over_chunks", t_patchability_target_balances_remaining_bits_over_chunks),
        run_test("patchability_target_is_bounded_by_raw_chunk_capacity", t_patchability_target_is_bounded_by_raw_chunk_capacity),
        run_test("raw_capacity_report_is_explicitly_not_quality_validated", t_raw_capacity_report_is_explicitly_not_quality_validated),
        run_test("patchability_report_confirms_exact_payload_only_when_enough_positions_passes", t_patchability_report_confirms_exact_payload_only_when_enough_positions_passes),
        run_test("report_rejects_patchable_counts_above_raw_candidates", t_report_rejects_patchable_counts_above_raw_candidates),
        run_test("report_rejects_mismatched_segment_arrays", t_report_rejects_mismatched_segment_arrays),
        run_test("cli_writes_report_for_a_valid_measured_partition", t_cli_writes_report_for_a_valid_measured_partition),
        run_test("cli_selects_blind_stable_profile", t_cli_selects_blind_stable_profile),
        run_test("cli_accepts_explicit_payload_size_without_proof_file", t_cli_accepts_explicit_payload_size_without_proof_file),
    ]
    raise SystemExit(summarise(results, "Phase 13"))


if __name__ == "__main__":
    main_test()
