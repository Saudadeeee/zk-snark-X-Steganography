"""Per-frame decoded quality of a stego H.264 stream against its cover.

Reports whole-video figures and, separately, the frames the embedding changed.

    python -m benchmark.latticezk_quality --cover cover.h264 --stego stego.h264
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_FRAME_LINE = re.compile(r"n:(\d+) mse_avg:([0-9.]+) mse_y:([0-9.]+)")
PEAK = 255.0


def _psnr(mse: float) -> float | None:
    return None if mse <= 0 else round(10 * math.log10(PEAK * PEAK / mse), 3)


def frame_quality(cover: Path, stego: Path, *, ffmpeg: str = "ffmpeg") -> dict[str, Any]:
    """Decode both streams and summarise per-frame luma MSE."""
    return summarize_luma_mse(per_frame_luma_mse(cover, stego, ffmpeg=ffmpeg))


def per_frame_luma_mse(cover: Path, stego: Path, *, ffmpeg: str = "ffmpeg") -> list[float]:
    """Luma MSE of every decoded stego frame against the decoded cover frame."""
    with tempfile.TemporaryDirectory(prefix="latticezk-quality-") as directory:
        stats = Path(directory) / "psnr.log"
        escaped = str(stats).replace("\\", "/").replace(":", "\\:")
        completed = subprocess.run(
            [ffmpeg, "-hide_banner", "-nostdin", "-i", str(stego), "-i", str(cover),
             "-lavfi", f"[0:v][1:v]psnr=stats_file='{escaped}'", "-f", "null", "-"],
            capture_output=True, text=True, timeout=3600, check=False,
        )
        if completed.returncode != 0 or not stats.is_file():
            raise RuntimeError(f"ffmpeg quality comparison failed: {completed.stderr[-400:]}")
        luma_mse = [
            float(match.group(3))
            for match in map(_FRAME_LINE.search, stats.read_text(encoding="utf-8").splitlines())
            if match is not None
        ]
    if not luma_mse:
        raise RuntimeError("no frames were compared")
    return luma_mse


def summarize_luma_mse(luma_mse: list[float]) -> dict[str, Any]:
    changed = [value for value in luma_mse if value > 0]
    return {
        "frames": len(luma_mse),
        "frames_modified": len(changed),
        "frames_modified_fraction": round(len(changed) / len(luma_mse), 4),
        "luma_psnr_all_frames_db": _psnr(sum(luma_mse) / len(luma_mse)),
        "luma_psnr_modified_frames_db": _psnr(sum(changed) / len(changed)) if changed else None,
        "luma_psnr_worst_frame_db": _psnr(max(luma_mse)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cover", type=Path, required=True)
    parser.add_argument("--stego", type=Path, required=True)
    arguments = parser.parse_args()
    report = frame_quality(arguments.cover.resolve(strict=True), arguments.stego.resolve(strict=True))
    sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
