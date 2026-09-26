"""Create an isolated, ephemeral session shared by the numbered stages."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT, RUNS_DIR


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare one demo session and choose its input video/message.")
    parser.add_argument("--input", type=Path,
                        default=ROOT / "data" / "encoded" / "foreman_cif_q18_g1_300f.h264")
    parser.add_argument("--message", default="ZK demo payload")
    args = parser.parse_args()
    source = args.input.expanduser().resolve(strict=True)
    if not source.is_file():
        parser.error(f"input must be a regular file: {source}")
    message = args.message.encode("utf-8")
    if not message:
        parser.error("message must not be empty")

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    session = RUNS_DIR / f"session_{stamp}"
    suffix = 1
    while session.exists():
        session = RUNS_DIR / f"session_{stamp}_{suffix}"
        suffix += 1
    session.mkdir()

    source_bytes = source.read_bytes()
    key = os.urandom(32)
    (session / "message.bin").write_bytes(message)
    # This is a throwaway demo key, not a production credential. Do not print
    # or include its bytes in any log; the session folder is git-ignored.
    key_path = session / "secret_key.bin"
    descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as key_file:
        key_file.write(key)
    state = {
        "input_video": str(source),
        "input_bytes": len(source_bytes),
        "input_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "message_bytes": len(message),
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    (session / "session.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    (session / "00_prepare.log").write_text(
        "STEP: Select and fingerprint input video; create ephemeral demo key\n"
        f"input_video: {source}\ninput_bytes: {len(source_bytes)}\n"
        f"input_sha256: {state['input_sha256']}\nmessage_bytes: {len(message)}\n"
        "secret_key: generated (32 bytes), kept out of logs\n"
        "STAGE_RESULT: PASS\n",
        encoding="utf-8",
    )
    # Keep stdout to exactly one path so callers may assign it in PowerShell.
    print(session.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
