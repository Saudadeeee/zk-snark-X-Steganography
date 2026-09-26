"""Run the established WebSocket and real loopback-Uvicorn native E2E checks."""

from __future__ import annotations

import argparse
import os
import sys

from common import ROOT, native_tool, require_session, run_logged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    session, _ = require_session(args.session)
    environment = os.environ.copy()
    environment["ZK_STEGO_NATIVE_CLI"] = str(native_tool("zkstego_blind_bits"))
    test_file = ROOT / "src" / "runtest" / "test_native_http_channel.py"
    run_logged(
        session,
        title="Native WebSocket and loopback HTTP/WebSocket end-to-end tests",
        log_name="12_websocket_e2e.log",
        command=[sys.executable, str(test_file)],
        stdin_description="none; uses isolated E2E fixtures",
        timeout=1200,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
