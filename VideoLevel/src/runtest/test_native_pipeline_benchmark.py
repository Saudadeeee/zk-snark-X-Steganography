from benchmark.native_pipeline_matrix import (
    build_metric_filtergraph,
    parse_encoder_result,
    parse_metric_log,
)


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

    assert "stats_file=psnr_per_frame.log" in graph
    assert "stats_file=ssim_per_frame.log" in graph
    assert "D:" not in graph
