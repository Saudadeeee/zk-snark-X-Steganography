"""Blind-extract authenticated bytes from stego H.264 without the cover file."""

from __future__ import annotations

import argparse

from common import native_tool, read_key, require_artifact, require_session, run_logged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    parser.add_argument("--max-bits-per-idr", type=int, default=64)
    parser.add_argument("--maximum-payload-bytes", type=int, default=4096)
    args = parser.parse_args()
    session, _ = require_session(args.session)
    stego = require_artifact(session, "stego_video.h264")
    keyline = read_key(session).hex().encode("ascii") + b"\n"
    result = run_logged(
        session,
        title="Blind extraction from stego video (original cover is not provided)",
        log_name="07_blind_extract.log",
        command=[str(native_tool("zkstego_blind_bits")), "extract-stream-auth", str(stego), "-",
                 str(args.maximum_payload_bytes), str(args.max_bits_per_idr)],
        stdin_data=keyline,
        stdin_description="ephemeral key=<redacted>; no original video supplied",
        timeout=300,
    )
    recovered = bytes.fromhex(result.stdout.decode("ascii").strip())
    (session / "extracted_payload.bin").write_bytes(recovered)
    print(f"extracted_bytes={len(recovered)}")
    print(f"output: {session / 'extracted_payload.bin'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
