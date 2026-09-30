from benchmark.native_pipeline_matrix import (
    escape_filter_path,
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


def test_escape_windows_drive_colon_for_ffmpeg_filtergraph():
    assert escape_filter_path(r"D:\bench\frame metrics.log") == r"D\:/bench/frame metrics.log"
