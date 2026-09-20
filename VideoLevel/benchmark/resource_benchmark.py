"""Run the validated benchmark sections while recording wall time, CPU and RSS.

This is intentionally a process-level measurement: native ``node``, ffmpeg and
Python descendants are included, so the reported peak is meaningful for the
actual end-to-end pipeline rather than only Python allocations.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil


ROOT = Path(__file__).resolve().parent.parent
RESULT = ROOT / "benchmark" / "results" / "resource_benchmark.json"


def _tree_usage(process: psutil.Process) -> tuple[int, float]:
    rss, cpu = 0, 0.0
    try:
        processes = [process, *process.children(recursive=True)]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        # The child can terminate after the caller's poll() but before psutil
        # enumerates its descendants.  A missing final sample is preferable to
        # turning an otherwise completed benchmark into a monitor failure.
        return rss, cpu
    for item in processes:
        try:
            memory = item.memory_info()
            times = item.cpu_times()
            rss += memory.rss
            cpu += times.user + times.system
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return rss, cpu


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure complete validated benchmark resource use")
    parser.add_argument("--sections", nargs="+", type=int, default=[1, 2, 3, 4, 5, 6])
    parser.add_argument("--timeout", type=int, default=180, help="per-section timeout passed to runner")
    parser.add_argument("--fast", action="store_true", help="pass --fast to existing benchmark runner")
    args = parser.parse_args()

    command = [sys.executable, "-m", "benchmark.safe_benchmark_runner", "--sections", *map(str, args.sections), "--timeout", str(args.timeout)]
    if args.fast:
        command.append("--fast")
    started = time.perf_counter()
    child = subprocess.Popen(command, cwd=ROOT)
    monitored = psutil.Process(child.pid)
    peak_rss, max_cpu = 0, 0.0
    while child.poll() is None:
        rss, cpu = _tree_usage(monitored)
        peak_rss, max_cpu = max(peak_rss, rss), max(max_cpu, cpu)
        time.sleep(0.1)
    rss, cpu = _tree_usage(monitored)
    peak_rss, max_cpu = max(peak_rss, rss), max(max_cpu, cpu)
    elapsed = time.perf_counter() - started
    report = {
        "measured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "command": command,
        "exit_code": child.returncode,
        "wall_time_s": round(elapsed, 3),
        "process_tree_peak_rss_mib": round(peak_rss / (1024 * 1024), 3),
        "process_tree_cpu_s": round(max_cpu, 3),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "logical_cpus": os.cpu_count(),
    }
    RESULT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return child.returncode


if __name__ == "__main__":
    raise SystemExit(main())
