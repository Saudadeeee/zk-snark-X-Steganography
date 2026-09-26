"""Embed packed proof bytes into the source H.264 using native CAVLC code."""

from __future__ import annotations

import argparse

from common import native_tool, read_key, require_artifact, require_session, run_logged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    parser.add_argument("--max-bits-per-idr", type=int, default=64)
    args = parser.parse_args()
    if args.max_bits_per_idr < 1:
        parser.error("--max-bits-per-idr must be positive")
    session, state = require_session(args.session)
    payload = require_artifact(session, "packed_payload.bin").read_bytes()
    require_artifact(session, "candidate_capacity.json")
    output = session / "stego_video.h264"
    stdin_data = read_key(session).hex().encode("ascii") + b"\n" + payload.hex().encode("ascii") + b"\n"
    run_logged(
        session,
        title="Embed proof-bearing bytes into selected CAVLC sign positions",
        log_name="05_embed_video.log",
        command=[str(native_tool("zkstego_blind_bits")), "embed-stream-auth-stdin",
                 state["input_video"], str(output), str(args.max_bits_per_idr)],
        stdin_data=stdin_data,
        stdin_description=f"ephemeral key=<redacted>; payload={len(payload)} bytes",
        timeout=300,
    )
    print(f"stego_video: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
