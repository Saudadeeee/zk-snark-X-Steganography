import math
import sys

from benchmark.native_pipeline_matrix import (
    _run_measured,
    build_metric_filtergraph,
    compute_luma_ssim,
    frame_transport_payload,
    host_metadata,
    label_ffmpeg_ssim,
    _markdown_report,
    parse_encoder_result,
    parse_metric_log,
    serialize_quality_rows,
)
from src.blind_sync import unpack_blind_payload


def test_parse_encoder_capacity_failure():
    parsed = parse_encoder_result(
        2,
        "",
        "payload capacity insufficient: embedded 10420 of 270424 bits\n",
    )

    assert parsed["status"] == "capacity_failure"
    assert parsed["embedded_bits"] == 10420
    assert parsed["requested_bits"] == 270424


def test_parse_encoder_success():
    parsed = parse_encoder_result(
        0,
        "PASS frames=300 dimensions=352x288 embedded_bits=120\n",
        "",
    )

    assert parsed["status"] == "success"
    assert parsed["embedded_bits"] == 120


def test_parse_per_frame_psnr_and_ssim_logs():
    psnr = "n:1 mse_avg:10.0 psnr_avg:38.13\nn:2 mse_avg:12.0 psnr_avg:37.34\n"
    ssim = "n:1 Y:0.99 U:0.98 V:0.98 All:0.987\nn:2 Y:0.98 U:0.97 V:0.97 All:0.977\n"

    rows = parse_metric_log(psnr, ssim)

    assert rows == [
        {"frame": 1, "psnr_db": 38.13, "ssim": 0.987},
        {"frame": 2, "psnr_db": 37.34, "ssim": 0.977},
    ]


def test_filtergraph_uses_relative_metric_logs_for_windows_compatibility():
    graph = build_metric_filtergraph("psnr_per_frame.log", "ssim_per_frame.log")

    assert "split=2[refp][refs]" in graph
    assert "split=2[distp][dists]" in graph
    assert "[refp][distp]psnr=" in graph
    assert "[refs][dists]ssim=" in graph
    assert "stats_file=psnr_per_frame.log" in graph
    assert "stats_file=ssim_per_frame.log" in graph
    assert "D:" not in graph


def test_transport_payload_is_the_real_blind_sync_envelope():
    raw, framed = frame_transport_payload(bytes.fromhex("a5"))

    assert raw == bytes.fromhex("a5")
    assert len(framed) == len(raw) + 14
    assert unpack_blind_payload(framed) == raw


def test_host_metadata_records_hardware_context():
    host = host_metadata()

    assert host["physical_cores"] > 0
    assert host["logical_processors"] >= host["physical_cores"]
    assert host["ram_total_bytes"] > 0
    assert host["cpu_identifier"]


def test_measured_process_drains_large_stdout_and_stderr():
    result = _run_measured([
        sys.executable,
        "-c",
        "import sys; sys.stdout.write('o'*200000); sys.stderr.write('e'*200000)",
    ])

    assert result["returncode"] == 0
    assert len(result["stdout"]) == 200000
    assert len(result["stderr"]) == 200000


def test_measured_process_reports_timeout():
    result = _run_measured([sys.executable, "-c", "import time; time.sleep(5)"], timeout_seconds=0.05)

    assert result["timed_out"] is True
    assert result["returncode"] is not None


def test_quality_json_represents_infinite_psnr_without_invalid_json():
    rows = serialize_quality_rows([{"frame": 1, "psnr_db": math.inf, "ssim": 1.0}])

    assert rows == [{"frame": 1, "psnr_db": None, "psnr_status": "positive_infinity", "ssim": 1.0}]


def test_precise_luma_ssim_distinguishes_near_identical_frames():
    reference = bytes([100] * (32 * 32))
    changed = bytearray(reference)
    changed[16 * 32 + 16] = 101

    score = compute_luma_ssim(reference, bytes(changed), width=32, height=32)

    assert 0.0 < score < 1.0


def test_ffmpeg_ssim_value_is_preserved_before_optional_luma_metric():
    rows = label_ffmpeg_ssim([{"frame": 1, "psnr_db": 40.0, "ssim": 1.0}])

    assert rows[0]["ssim_ffmpeg_all"] == 1.0


def test_report_exposes_extractor_cpu_and_peak_rss():
    report = {
        "generated_utc": "2026-09-30T00:00:00+00:00",
        "host": {},
        "cases": [{
            "name": "fixture",
            "input_video": {"width": 352, "height": 288, "frames": 1, "duration_seconds": 0.04},
            "encode": {"wall_seconds": 0.1, "process_tree_cpu_seconds": 0.09, "process_tree_peak_rss_mb": 6.0, "status": "success", "embedded_bits": 120},
            "blind_extract": {"passed": True, "wall_seconds": 0.2, "process_tree_cpu_seconds": 0.18, "process_tree_peak_rss_mb": 40.0},
            "quality": {"mean_frame_psnr_db": 40.0, "mean_frame_ssim_ffmpeg_all_rounded": 0.98},
        }],
    }

    markdown = _markdown_report(report)

    assert "Extract CPU (s)" in markdown
    assert "Extract peak RSS (MiB)" in markdown
    assert "0.180" in markdown
    assert "40.000" in markdown
