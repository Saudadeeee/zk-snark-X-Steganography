"""Summarize which staged commands completed successfully in a session."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from common import require_session


STAGES = [
    "00_prepare.log",
    "01_generate_proof.log",
    "02_pack_payload.log",
    "03_read_video.log",
    "04_candidate_capacity.log",
    "04_first_candidate_location.log",
    "05_embed_video.log",
    "06_read_stego_video.log",
    "07_blind_extract.log",
    "08_unpack_payload.log",
    "09_verify_proof.log",
    "10_wrong_key_rejection.log",
    "11_http_transport.log",
    "12_websocket_e2e.log",
    "13_python_pipeline.log",
]


def stage_passed(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    return (
        "EXIT_CODE: 0" in text
        or "STAGE_RESULT: PASS" in text
        or (path.name == "00_prepare.log" and "input_sha256:" in text)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    session, state = require_session(args.session)
    lines = [
        "STAGED SYSTEM DEMO SUMMARY",
        f"input_video: {state['input_video']}",
        f"input_sha256: {state['input_sha256']}",
        f"session: {session}",
        "",
    ]
    for name in STAGES:
        path = session / name
        lines.append(f"{name}: {'PASS' if stage_passed(path) else 'NOT RUN / FAILED'}")
    lines.append("")
    for filename in ("proof_stego.h264", "stego_video.h264", "extracted_payload.bin",
                     "http_stego_video.h264", "python_pipeline_stego.h264"):
        path = session / filename
        if path.is_file():
            lines.append(f"{filename}: {path.stat().st_size} bytes; sha256={hashlib.sha256(path.read_bytes()).hexdigest()}")
    summary = "\n".join(lines) + "\n"
    target = session / "SUMMARY.txt"
    target.write_text(summary, encoding="utf-8")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
