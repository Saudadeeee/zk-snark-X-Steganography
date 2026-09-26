"""Measure CAVLC sign candidates and show a real candidate bit address."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import native_tool, require_artifact, require_session, run_logged


METRICS_PREFIX = "ZKSTEG_CAPACITY_METRICS "


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    parser.add_argument("--max-bits-per-idr", type=int, default=64)
    args = parser.parse_args()
    if args.max_bits_per_idr < 1:
        parser.error("--max-bits-per-idr must be positive")
    session, state = require_session(args.session)
    packed = require_artifact(session, "packed_payload.bin").read_bytes()
    required_bits = (len(packed) + 19) * 8
    cli = native_tool("zkstego_blind_bits")

    result = run_logged(
        session,
        title="Scan IDR stream and measure bounded CAVLC candidate capacity",
        log_name="04_candidate_capacity.log",
        command=[str(cli), "measure-live-capacity-stdin", str(args.max_bits_per_idr)],
        stdin_data=Path(state["input_video"]).read_bytes(),
        stdin_description="raw Annex-B H.264 bytes",
        timeout=300,
    )
    lines = [line for line in result.stdout.decode("ascii").splitlines()
             if line.startswith(METRICS_PREFIX)]
    if len(lines) != 1:
        raise RuntimeError(f"capacity scanner did not emit exactly one metrics record; see {session / '04_candidate_capacity.log'}")
    metrics = json.loads(lines[0][len(METRICS_PREFIX):])
    (session / "candidate_capacity.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    if metrics["candidate_capacity_bits"] < required_bits:
        raise RuntimeError(
            f"insufficient native capacity: {metrics['candidate_capacity_bits']} bits, need {required_bits}; "
            "see candidate_capacity.json and provide a longer/higher-capacity supported video"
        )

    probe = session / "candidate_probe.h264"
    run_logged(
        session,
        title="Locate and patch one disposable candidate sign for inspection",
        log_name="04_first_candidate_location.log",
        command=[str(native_tool("zkstego_idr_inspect")), state["input_video"],
                 "--flip-first-sign", str(probe)],
        timeout=180,
    )
    report = (
        f"required_bits_including_native_framing: {required_bits}\n"
        f"raw_candidate_signs: {metrics['raw_candidate_signs']}\n"
        f"bounded_candidate_capacity_bits: {metrics['candidate_capacity_bits']}\n"
        f"capacity_sufficient: true\n"
        "The embedding step deterministically selects the required candidates from this scan.\n"
        "The probe output is a separate one-bit diagnostic, not the stego output.\n"
    )
    (session / "04_positions_summary.txt").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
