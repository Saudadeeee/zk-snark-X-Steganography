"""CABAC test clips, encoded on demand with libx264 from the local raw sources.

``data/raw`` and ``data/encoded`` are gitignored; a test asks for a clip by
name and is skipped when ffmpeg or the raw source is missing.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENCODED = ROOT / "data" / "encoded"
RAW = ROOT / "data" / "raw"

_X264_G1 = ["-c:v", "libx264", "-coder", "1", "-g", "1", "-bf", "0", "-preset", "medium"]
CLIPS: dict[str, tuple[str, list[str]]] = {
    "foreman_cif_cabac_main_g1_30f.h264": (
        "foreman_cif_300f.y4m", ["-frames:v", "30", *_X264_G1, "-profile:v", "main", "-qp", "22"]),
    "foreman_cif_cabac_high_g1_30f.h264": (
        "foreman_cif_300f.y4m",
        ["-frames:v", "30", *_X264_G1, "-profile:v", "high", "-qp", "22", "-x264-params", "8x8dct=1"]),
    "foreman_cif_cabac_high_g8_48f.h264": (
        "foreman_cif_300f.y4m",
        ["-frames:v", "48", "-c:v", "libx264", "-coder", "1", "-profile:v", "high", "-g", "8",
         "-keyint_min", "8", "-sc_threshold", "0", "-qp", "22", "-preset", "medium"]),
    "foreman_cif_cabac_high_g1_300f.h264": (
        "foreman_cif_300f.y4m", [*_X264_G1, "-profile:v", "high", "-qp", "22"]),
    "container_cif_cabac_high_slices4_12f.h264": (
        "container_cif.y4m",
        ["-frames:v", "12", *_X264_G1, "-profile:v", "high", "-qp", "26", "-x264-params", "slices=4"]),
    "akiyo_cif_cabac_main_crf18_aq_12f.h264": (
        "akiyo_cif.y4m",
        ["-frames:v", "12", *_X264_G1, "-profile:v", "main", "-crf", "18", "-x264-params", "aq-mode=2"]),
    "football_cif_cabac_high_qp4_6f.h264": (
        "football_cif.y4m", ["-frames:v", "6", *_X264_G1, "-profile:v", "high", "-qp", "4"]),
}


def cabac_clip(name: str) -> Path:
    """Path of a CABAC clip, encoding it first if needed (skips the test if impossible)."""
    path = ENCODED / name
    if path.is_file():
        return path
    source, options = CLIPS[name]
    raw = RAW / source
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg and ffprobe are required")
    if not raw.is_file():
        pytest.skip(f"local raw source not present: data/raw/{source}")
    ENCODED.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".partial.h264")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw), *options, str(partial)],
        check=True, capture_output=True,
    )
    partial.replace(path)
    return path


def strict_decode_errors(path: Path) -> str:
    """FFmpeg stderr of a strict decode (empty when the stream decodes cleanly)."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-err_detect", "explode",
         "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True, check=False,
    )
    return result.stderr.strip() + ("" if result.returncode == 0 else f" (exit {result.returncode})")


def psnr_y(reference: Path, distorted: Path) -> tuple[float, float]:
    """``(average, minimum)`` per-frame luma PSNR of ``distorted`` against ``reference``."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(reference), "-i", str(distorted),
         "-lavfi", "psnr=stats_file=-", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    values = []
    for line in result.stdout.splitlines():
        for field in line.split():
            if field.startswith("psnr_y:"):
                text = field.split(":", 1)[1]
                values.append(float("inf") if text == "inf" else float(text))
    if not values:
        raise RuntimeError("ffmpeg psnr filter produced no per-frame values")
    finite = [value for value in values if value != float("inf")] or [float("inf")]
    return sum(finite) / len(finite), min(values)
