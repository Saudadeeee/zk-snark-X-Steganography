"""
prepare_fixtures.py — regenerate the H.264 test fixtures under data/encoded/.

data/encoded/*.h264 is git-ignored, so a fresh clone has no test videos.
This script re-encodes them from the tracked raw source data/raw/foreman_cif.y4m
with libx264 Baseline/CAVLC settings matching each fixture's name.

Run:
    py -3.12 src/runtest/prepare_fixtures.py            # create missing fixtures
    py -3.12 src/runtest/prepare_fixtures.py --force    # re-encode all fixtures

The tracked raw source has 50 frames; "300f" fixtures loop it to 300 frames.

foreman_cif_q18_g1_300f.h264 is pinned by the native CTest (3,551,610 bytes);
with ffmpeg 8.0.1 / libx264 these settings reproduce it bit-exactly
(SHA-256 867cc0c6...35df57). Other encoder versions may differ.

Not generated here:
  - coastguard/deadline fixtures need raw .y4m files that are not tracked;
    tests that use them fall back to the foreman fixtures.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW_SOURCE = ROOT / "data" / "raw" / "foreman_cif.y4m"
ENCODED_DIR = ROOT / "data" / "encoded"

_BASELINE_CAVLC = ["-c:v", "libx264", "-profile:v", "baseline", "-coder", "0",
                   "-bf", "0", "-pix_fmt", "yuv420p"]

# name -> (frame count or None for the whole source, rate control / GOP arguments)
FIXTURES: dict[str, tuple[int | None, list[str]]] = {
    "foreman_cif_q22_g1.h264": (None, ["-g", "1", "-qp", "22"]),
    "foreman_cif_q18_g1_300f.h264": (300, ["-g", "1", "-keyint_min", "1", "-qp", "18"]),
    "foreman_cif_g8_300f_b800k.h264": (300, ["-g", "8", "-b:v", "800k"]),
}


def encode_fixture(name: str, frames: int | None, rate_args: list[str], ffmpeg: str) -> None:
    output = ENCODED_DIR / name
    input_args = ["-i", str(RAW_SOURCE)]
    frame_args: list[str] = []
    if frames is not None:
        input_args = ["-stream_loop", "-1", *input_args]
        frame_args = ["-frames:v", str(frames)]
    command = [ffmpeg, "-v", "error", "-y", *input_args,
               *_BASELINE_CAVLC, *rate_args, *frame_args, "-f", "h264", str(output)]
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=False)
    if result.returncode != 0:
        output.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg failed for {name}:\n{result.stderr.strip()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate data/encoded test fixtures")
    parser.add_argument("--force", action="store_true", help="re-encode existing fixtures")
    args = parser.parse_args()

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        print("ERROR: ffmpeg not found on PATH", file=sys.stderr)
        return 1
    if not RAW_SOURCE.is_file():
        print(f"ERROR: raw source not found: {RAW_SOURCE}", file=sys.stderr)
        return 1

    ENCODED_DIR.mkdir(parents=True, exist_ok=True)
    for name, (frames, rate_args) in FIXTURES.items():
        target = ENCODED_DIR / name
        if target.is_file() and not args.force:
            print(f"[keep]   {name}")
            continue
        encode_fixture(name, frames, rate_args, ffmpeg)
        print(f"[encode] {name} ({target.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
