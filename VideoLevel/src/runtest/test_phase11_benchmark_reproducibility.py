"""Phase 11: keep camera benchmark recording safeguards in the standard suite."""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.test_realtime_camera_recorder import RealtimeCameraRecorderTests
from src.runtest._helpers import run_test, section, summarise
from src.runtest.run_all import exit_code_for_phase_statuses, status_for_phase_result


def _run_case(method_name: str) -> None:
    case = RealtimeCameraRecorderTests()
    case.setUp()
    try:
        getattr(case, method_name)()
    finally:
        case.tearDown()


def _run_exit_code_case(statuses: list[str], expected: int) -> None:
    assert exit_code_for_phase_statuses(statuses) == expected


def _run_phase_status_case(
    passed: int, failed: int, skipped: int, exit_code: int, expected: str
) -> None:
    assert status_for_phase_result(passed, failed, skipped, exit_code) == expected


def main() -> int:
    section("Phase 11 - Benchmark Reproducibility")
    methods = (
        "test_capture_command_disables_synthetic_frame_duplication",
        "test_recorder_rejects_non_passthrough_capture_encoder_mode",
        "test_rejects_missing_or_nonpositive_camera_input_buffer_size",
        "test_accepts_bounded_stdin_buffer_with_one_pending_input_chunk",
        "test_rejects_stdin_buffer_above_high_water_plus_one_input_chunk",
        "test_collects_hardware_toolchain_and_native_binary_identity",
        "test_appends_next_run_without_replacing_existing_history",
        "test_persisted_functional_run_marks_below_target_fps_as_realtime_gate_failure",
        "test_persisted_functional_run_passes_fps_gate_at_exact_threshold",
        "test_fps_gate_uses_frame_count_when_reported_rate_rounding_crosses_threshold",
        "test_rejects_capacity_smaller_than_embedded_bits_without_mutating_artifact",
        "test_rejects_full_stream_capacity_above_candidate_bound",
        "test_rejects_failed_camera_run_without_mutating_artifact",
        "test_rejects_quality_record_missing_required_psnr_ssim_and_frame_counts",
        "test_rejects_missing_payload_patch_latency_percentiles",
        "test_rejects_non_finite_fps_and_resource_measurements",
        "test_rejects_fps_inconsistent_with_active_stream_duration",
        "test_rejects_missing_encoded_byte_counts",
        "test_rejects_missing_camera_channel_latency_distribution",
        "test_rejects_missing_native_stdout_wait_percentiles",
        "test_maps_annex_b_nal_completion_latency_across_different_chunks",
        "test_labels_loopback_tcp_channel_latency_explicitly",
        "test_splits_camera_read_send_and_output_receive_latency",
        "test_measures_input_and_output_nal_completion_interarrival",
        "test_rejects_mismatched_input_and_output_nal_sequences",
    )
    exit_code_cases = (
        ("run_all_returns_failure_when_phase_fails_before_tests_start", ["FAIL"], 1),
        ("run_all_returns_incomplete_when_phase_is_incomplete", ["OK", "INCOMPLETE"], 2),
        ("run_all_returns_success_only_when_all_phases_pass", ["OK", "OK"], 0),
        ("run_all_failure_takes_precedence_over_incomplete", ["INCOMPLETE", "FAIL"], 1),
    )
    phase_status_cases = (
        ("run_all_rejects_empty_zero_exit_phase", 0, 0, 0, 0, "FAIL"),
        ("run_all_rejects_failed_test_even_with_zero_exit", 1, 1, 0, 0, "FAIL"),
        ("run_all_marks_skipped_test_incomplete", 2, 0, 1, 0, "INCOMPLETE"),
        ("run_all_accepts_reported_passes", 2, 0, 0, 0, "OK"),
        ("run_all_preserves_incomplete_exit", 0, 0, 0, 2, "INCOMPLETE"),
        ("run_all_preserves_failure_exit", 0, 0, 0, 1, "FAIL"),
    )
    results = [run_test(name.removeprefix("test_"), lambda name=name: _run_case(name)) for name in methods]
    results.extend(
        run_test(name, lambda statuses=statuses, expected=expected: _run_exit_code_case(statuses, expected))
        for name, statuses, expected in exit_code_cases
    )
    results.extend(
        run_test(
            name,
            lambda passed=passed, failed=failed, skipped=skipped, exit_code=exit_code, expected=expected:
                _run_phase_status_case(passed, failed, skipped, exit_code, expected),
        )
        for name, passed, failed, skipped, exit_code, expected in phase_status_cases
    )
    return summarise(results, "Phase 11")


if __name__ == "__main__":
    raise SystemExit(main())
