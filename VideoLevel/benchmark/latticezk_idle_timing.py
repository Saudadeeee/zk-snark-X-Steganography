"""Embed/verify timings of selected sweep cases, re-run one at a time on an idle host.

The sweep may run several cases concurrently, which inflates its timings.  This
script repeats chosen cases sequentially with the configuration recorded in
their sweep reports (video, carrier, chunk size, mode) and writes
``timing_<case>.json`` with the timings, the host and the worker count.

    python -m benchmark.latticezk_idle_timing --cases city4cif_q22_reg container_cif_q22_reg
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmark" / "results" / "q2"
WORK = ROOT / "tmp" / "idle_timing"


def _video(report: dict[str, Any]) -> Path:
    """Sweep reports record the cover's file name; covers live in data/encoded."""
    recorded = Path(report["input_video"])
    for candidate in (recorded, ROOT / recorded, ROOT / "data" / "encoded" / recorded.name):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"cover {recorded} not found")


def _command(report: dict[str, Any], output: Path, stego: Path) -> list[str]:
    command = [sys.executable, "-B", "-m", "benchmark.latticezk_video_e2e",
               "--video", str(_video(report)),
               "--output", str(stego), "--report", str(output),
               "--chunk-bytes", str(report["chunk_bytes"]), "--carrier", report["carrier"],
               "--frames-per-segment", str(report["frames_per_segment"]),
               "--skip-security-checks"]
    if report["mode"].startswith("registered"):
        command.append("--registered")
    return command


def run_case(name: str, results: Path, work: Path) -> dict[str, Any]:
    source = results / f"e2e_{name}.json"
    if not source.exists():
        return {"case": name, "error": "no sweep report"}
    report = json.loads(source.read_text(encoding="utf-8"))
    raw = work / f"timing_{name}.raw.json"
    stego = work / f"{name}.h264"
    log = work / f"{name}.log"
    with log.open("w", encoding="utf-8") as handle:
        code = subprocess.run(_command(report, raw, stego), cwd=ROOT, stdout=handle,
                              stderr=subprocess.STDOUT, check=False).returncode
    stego.unlink(missing_ok=True)
    if code != 0 or not raw.exists():
        return {"case": name, "error": f"e2e exit {code}", "log": str(log)}
    timed = json.loads(raw.read_text(encoding="utf-8"))
    return {
        "case": name,
        "carrier": report["carrier"],
        "carrier_contract": timed.get("carrier_contract"),
        "parameter_set": timed.get("parameter_set"),
        "envelope_bytes": timed.get("envelope_bytes"),
        "carriers_used": timed.get("carriers_used"),
        "segments_used": timed.get("segments_used"),
        "verified": timed.get("blind_video_only_verification"),
        "timings_s": timed.get("timings_s"),
        "sweep_timings_s": report.get("timings_s"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", nargs="+", required=True)
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--work", type=Path, default=WORK)
    arguments = parser.parse_args()
    arguments.work.mkdir(parents=True, exist_ok=True)
    host = {"platform": platform.platform(), "processor": platform.processor(), "cpus": os.cpu_count(),
            "analysis_workers": os.environ.get("ZKSTEGO_ANALYSIS_WORKERS", "default min(8, cpus)"),
            "note": "cases run one at a time with no other benchmark on the host"}
    for name in arguments.cases:
        row = {"host": host, **run_case(name, arguments.results, arguments.work)}
        (arguments.results / f"timing_{name}.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
        sys.stdout.write(json.dumps({key: row.get(key) for key in ("case", "verified", "timings_s", "error")}) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
