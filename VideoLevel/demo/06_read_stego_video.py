"""Read back and strictly decode the generated H.264 stego video."""

from __future__ import annotations

import argparse
import hashlib
import shutil

from common import native_tool, require_artifact, require_session, run_logged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    session, _ = require_session(args.session)
    stego = require_artifact(session, "stego_video.h264")
    run_logged(
        session,
        title="Read back NAL/IDR layout from stego output",
        log_name="06_read_stego_video.log",
        command=[str(native_tool("zkstego_idr_inspect")), str(stego), "--slice"],
        timeout=180,
    )
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        run_logged(
            session,
            title="Strict FFmpeg decode of stego output",
            log_name="06_ffmpeg_decode.log",
            command=[ffmpeg, "-v", "error", "-xerror", "-i", str(stego), "-f", "null", "-"],
            timeout=300,
        )
    else:
        (session / "06_ffmpeg_decode.log").write_text(
            "SKIPPED: ffmpeg not found on PATH\n", encoding="utf-8",
        )
        print("FFmpeg strict decode: SKIP (ffmpeg missing)")
    print(f"stego_bytes={stego.stat().st_size}")
    print(f"stego_sha256={hashlib.sha256(stego.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
