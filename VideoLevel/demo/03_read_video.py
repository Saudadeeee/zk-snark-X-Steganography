"""Inspect Annex-B NAL units and decode supported IDR slices/macroblocks."""

from __future__ import annotations

import argparse

from common import native_tool, require_session, run_logged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    session, state = require_session(args.session)
    run_logged(
        session,
        title="Read Annex-B video and inspect IDR slices",
        log_name="03_read_video.log",
        command=[str(native_tool("zkstego_idr_inspect")), state["input_video"], "--slice"],
        timeout=180,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
