"""Portable FFmpeg fixture for codec validation and decode smoke tests."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtest._helpers import run_test, section, summarise
from src.stream_profile import analyze_stream_profile


def _encode(output: Path, *, profile: str, coder: int) -> None:
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=32x32:rate=1",
            "-frames:v", "1", "-pix_fmt", "yuv420p", "-c:v", "libx264",
            "-profile:v", profile, "-coder", str(coder), "-g", "1", "-f", "h264", str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def t_ffmpeg_fixture_validates_codec_and_decodes() -> None:
    assert shutil.which("ffmpeg"), "ffmpeg is required for this integration test"
    with tempfile.TemporaryDirectory(prefix="zkstego-fixture-") as directory:
        root = Path(directory)
        baseline = root / "baseline_cavlc.h264"
        main = root / "main_cabac.h264"
        _encode(baseline, profile="baseline", coder=0)
        _encode(main, profile="main", coder=1)

        accepted = analyze_stream_profile(str(baseline))
        rejected = analyze_stream_profile(str(main))
        assert accepted.supported and accepted.profile == "baseline" and accepted.entropy_mode == "cavlc"
        assert not rejected.supported and rejected.profile == "main" and rejected.entropy_mode == "cabac"

        decode = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(baseline), "-f", "null", "-"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert decode.returncode == 0, decode.stderr


def main() -> None:
    section("FFmpeg fixture - codec gate and decode smoke test")
    results = [run_test("ffmpeg_fixture_validates_codec_and_decodes", t_ffmpeg_fixture_validates_codec_and_decodes)]
    raise SystemExit(summarise(results, "FFmpeg fixture"))


if __name__ == "__main__":
    main()
