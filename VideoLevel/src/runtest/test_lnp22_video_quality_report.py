"""Tests for per-frame visual-quality measurements of LNP22 video segments."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import numpy as np
import pytest

from benchmark import _common

ROOT = Path(__file__).resolve().parents[2]
PROBE_DIR = ROOT / "benchmark" / "lnp22_context_probe"
if str(PROBE_DIR) not in sys.path:
    sys.path.insert(0, str(PROBE_DIR))

import quality_report


def _write_segment(directory: Path, prefix: str, index: int, data: bytes) -> Path:
    path = directory / f"{prefix}_{index:05d}.h264"
    path.write_bytes(data)
    return path


@pytest.fixture(autouse=True)
def probe_cif_segments(monkeypatch):
    monkeypatch.setattr(
        quality_report,
        "_probe_h264_video",
        lambda _path, **_kwargs: {
            "width": 352,
            "height": 288,
            "decoded_frames": 2,
        },
    )


def test_report_preserves_partial_coverage_and_global_frame_indices(
    tmp_path, monkeypatch
):
    _write_segment(tmp_path, "segment", 0, b"source-0")
    _write_segment(tmp_path, "segment", 1, b"source-1")
    stego = _write_segment(tmp_path, "stego", 0, b"stego-0")
    metric_calls = []

    def fake_quality(source_path, stego_path, max_frames, use_cache):
        metric_calls.append((source_path.name, stego_path.name, max_frames, use_cache))
        return {
            "n": 2,
            "psnr_per_frame": [40.0, float("inf")],
            "ssim_per_frame": [0.99, 1.0],
            "psnr_full_video": 43.01029995663981,
        }

    monkeypatch.setattr(quality_report, "compute_quality_streaming", fake_quality)

    report = quality_report.build_quality_report(tmp_path, frames_per_segment=2)

    assert report["complete"] is False
    assert report["source_segment_count"] == 2
    assert report["measured_segment_count"] == 1
    assert report["measured_frame_count"] == 2
    assert report["per_frame"][0]["frame_index"] == 0
    assert report["per_frame"][1]["frame_index"] == 1
    assert report["per_frame"][1]["psnr_y_db"] is None
    assert report["per_frame"][1]["identical_luma"] is True
    assert report["segments"][0]["input_width"] == 352
    assert report["segments"][0]["input_height"] == 288
    assert "rescale" in report["metric_scope"]
    assert report["segments"][0]["stego_sha256"] == hashlib.sha256(
        stego.read_bytes()
    ).hexdigest()
    assert metric_calls == [("segment_00000.h264", "stego_00000.h264", 3, False)]


def test_report_rejects_noncontiguous_source_segments(tmp_path):
    _write_segment(tmp_path, "segment", 1, b"source-1")
    _write_segment(tmp_path, "stego", 1, b"stego-1")

    with pytest.raises(ValueError, match="contiguous from zero"):
        quality_report.build_quality_report(tmp_path, frames_per_segment=2)


@pytest.mark.parametrize("value", [True, 2.5, "2"])
def test_report_rejects_non_integer_frames_per_segment(tmp_path, value):
    with pytest.raises(ValueError, match="positive integer"):
        quality_report.build_quality_report(tmp_path, frames_per_segment=value)


def test_report_rejects_frame_count_mismatch_before_nonfinal_segment(
    tmp_path, monkeypatch
):
    _write_segment(tmp_path, "segment", 0, b"source-0")
    _write_segment(tmp_path, "segment", 1, b"source-1")
    _write_segment(tmp_path, "stego", 0, b"stego-0")
    monkeypatch.setattr(
        quality_report,
        "_probe_h264_video",
        lambda _path, **_kwargs: {
            "width": 352,
            "height": 288,
            "decoded_frames": 1,
        },
    )
    monkeypatch.setattr(
        quality_report,
        "compute_quality_streaming",
        lambda *_args, **_kwargs: {
            "n": 1,
            "psnr_per_frame": [30.0],
            "ssim_per_frame": [0.9],
            "psnr_full_video": 30.0,
        },
    )

    with pytest.raises(ValueError, match="non-final segment"):
        quality_report.build_quality_report(tmp_path, frames_per_segment=2)


def test_report_rejects_truncated_final_stego_segment(tmp_path, monkeypatch):
    _write_segment(tmp_path, "segment", 0, b"source")
    _write_segment(tmp_path, "stego", 0, b"stego")
    monkeypatch.setattr(
        quality_report,
        "_probe_h264_video",
        lambda path, **_kwargs: {
            "width": 352,
            "height": 288,
            "decoded_frames": 100 if path.name.startswith("segment_") else 99,
        },
    )

    with pytest.raises(ValueError, match="decoded frame count mismatch"):
        quality_report.build_quality_report(tmp_path, frames_per_segment=100)


def test_report_rejects_metrics_truncated_after_probe(tmp_path, monkeypatch):
    _write_segment(tmp_path, "segment", 0, b"source")
    _write_segment(tmp_path, "stego", 0, b"stego")
    monkeypatch.setattr(
        quality_report,
        "compute_quality_streaming",
        lambda *_args, **_kwargs: {
            "n": 1,
            "psnr_per_frame": [30.0],
            "ssim_per_frame": [0.9],
            "psnr_full_video": 30.0,
        },
    )

    with pytest.raises(ValueError, match="invalid frame metrics"):
        quality_report.build_quality_report(tmp_path, frames_per_segment=100)


def test_report_rejects_different_source_and_stego_dimensions(tmp_path, monkeypatch):
    _write_segment(tmp_path, "segment", 0, b"source")
    _write_segment(tmp_path, "stego", 0, b"stego")
    monkeypatch.setattr(
        quality_report,
        "_probe_h264_video",
        lambda path, **_kwargs: {
            "width": 352 if path.name.startswith("segment_") else 640,
            "height": 288,
            "decoded_frames": 2,
        },
    )

    with pytest.raises(ValueError, match="dimensions differ"):
        quality_report.build_quality_report(tmp_path, frames_per_segment=100)


def test_report_writer_refuses_to_overwrite_existing_artifact(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_segment(run_dir, "segment", 0, b"source")
    _write_segment(run_dir, "stego", 0, b"stego")
    output = tmp_path / "quality.json"
    output.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        quality_report.write_quality_report(run_dir, output, frames_per_segment=2)

    assert output.read_text(encoding="utf-8") == "keep"


def test_report_writer_restores_path_when_measurement_fails(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    output = tmp_path / "quality.json"
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.write_bytes(b"placeholder")
    monkeypatch.setenv("PATH", "original-path")
    monkeypatch.setattr(
        quality_report, "_resolve_executable", lambda _command, _default: fake_ffmpeg
    )
    monkeypatch.setattr(
        quality_report.subprocess,
        "run",
        lambda *_args, **_kwargs: type("Result", (), {"stdout": "ffmpeg version test"})(),
    )

    def fail_measurement(*_args, **_kwargs):
        raise RuntimeError("intentional measurement failure")

    monkeypatch.setattr(quality_report, "build_quality_report", fail_measurement)

    with pytest.raises(RuntimeError, match="intentional measurement failure"):
        quality_report.write_quality_report(run_dir, output, frames_per_segment=2)

    assert os.environ["PATH"] == "original-path"


def test_cli_reports_decode_failure_without_traceback(tmp_path, monkeypatch, capsys):
    error = _common.QualityDecodeError("ffmpeg could not decode input")
    monkeypatch.setattr(
        quality_report,
        "write_quality_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    exit_code = quality_report.main(
        [
            "--run-dir",
            str(tmp_path),
            "--output",
            str(tmp_path / "quality.json"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "quality report failed: ffmpeg could not decode input" in captured.err
    assert "Traceback" not in captured.err


def test_ffmpeg_command_name_is_resolved_through_path(tmp_path, monkeypatch):
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"test executable placeholder")
    monkeypatch.setattr(quality_report.shutil, "which", lambda _name: str(ffmpeg))

    assert quality_report._resolve_ffmpeg("ffmpeg") == ffmpeg.resolve()


def test_quality_streaming_passes_ffmpeg_and_cache_policy_to_both_decoders(monkeypatch):
    calls = []
    ffmpeg = Path("D:/tools/ffmpeg.exe")

    def fake_decode(path, *, max_frames, ffmpeg_command=None, use_cache=None):
        calls.append((path, max_frames, ffmpeg_command, use_cache))
        return np.zeros((1, 288, 352), dtype=np.uint8)

    monkeypatch.setattr(_common, "decode_luma_frames", fake_decode)

    measured = _common.compute_quality_streaming(
        "source.h264",
        "stego.h264",
        max_frames=7,
        ffmpeg_command=ffmpeg,
        use_cache=False,
    )

    assert measured["n"] == 1
    assert calls == [
        ("source.h264", 7, ffmpeg, False),
        ("stego.h264", 7, ffmpeg, False),
    ]
