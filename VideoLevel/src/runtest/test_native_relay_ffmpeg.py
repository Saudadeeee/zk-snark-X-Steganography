"""Native relay integration: FFmpeg encode -> C relay/SEI -> FFmpeg decode."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _relay_path() -> Path:
    names = ["zkstego_annexb_relay.exe", "zkstego_annexb_relay"]
    candidates = []
    for name in names:
        candidates.extend([
            ROOT / "native" / "build" / "Release" / name,
            ROOT / "native" / "build" / name,
        ])
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("native relay binary not found; build native/ first")


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"{completed.stderr.decode('utf-8', 'replace')}"
        )
    return completed


def main() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required for native relay integration")
    relay = _relay_path()
    with tempfile.TemporaryDirectory(prefix="zkstego-native-") as temp_dir:
        source = Path(temp_dir) / "source.h264"
        stego = Path(temp_dir) / "sei.h264"
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=2",
            "-frames:v", "2", "-pix_fmt", "yuv420p",
            "-c:v", "libx264", "-profile:v", "baseline", "-coder", "0",
            "-x264-params", "aud=1:keyint=1:min-keyint=1:scenecut=0",
            "-f", "h264", "-y", str(source),
        ])
        relay_result = _run(
            [str(relay), "--sei-payload-hex", "0000010203", "--chunk-bytes", "5"],
            input=source.read_bytes(),
        )
        stego.write_bytes(relay_result.stdout)
        if stego.read_bytes() == source.read_bytes():
            raise AssertionError("relay did not add its in-band SEI carrier")
        _run(["ffmpeg", "-hide_banner", "-v", "error", "-i", str(stego), "-f", "null", "-"])
    print("native relay FFmpeg integration: passed")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"native relay FFmpeg integration: failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
