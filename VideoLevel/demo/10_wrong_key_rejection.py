"""Show that blind extraction fails under a different key."""

from __future__ import annotations

import argparse
import os

from common import native_tool, require_artifact, require_session, run_logged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    parser.add_argument("--max-bits-per-idr", type=int, default=64)
    args = parser.parse_args()
    session, _ = require_session(args.session)
    stego = require_artifact(session, "stego_video.h264")
    wrong_key_path = session / "wrong_key.bin"
    if not wrong_key_path.exists():
        wrong_key_path.write_bytes(os.urandom(32))
    wrong_key = wrong_key_path.read_bytes()
    if len(wrong_key) != 32:
        raise ValueError("wrong-key test artifact must be exactly 32 bytes")
    original_key = (session / "secret_key.bin").read_bytes()
    if wrong_key == original_key:
        wrong_key = bytes([wrong_key[0] ^ 1]) + wrong_key[1:]
        wrong_key_path.write_bytes(wrong_key)
    run_logged(
        session,
        title="Reject blind extraction with wrong key",
        log_name="10_wrong_key_rejection.log",
        command=[str(native_tool("zkstego_blind_bits")), "extract-stream-auth", str(stego), "-",
                 "4096", str(args.max_bits_per_idr)],
        stdin_data=wrong_key.hex().encode("ascii") + b"\n",
        stdin_description="different demo key=<redacted>",
        expected_exit_code=2,
        timeout=300,
    )
    print("wrong_key_rejected=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
