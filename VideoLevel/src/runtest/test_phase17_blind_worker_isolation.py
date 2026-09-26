"""The heavy blind comparison must release each video's parser heap."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.blind_core_trial import _worker_process_id, run_isolated
from src.runtest._helpers import run_test, section, summarise


def t_worker_runs_in_separate_process() -> None:
    worker_pid = run_isolated(_worker_process_id)
    assert isinstance(worker_pid, int)
    assert worker_pid != os.getpid()


def main() -> None:
    section("Phase 17 - Isolated blind-analysis worker")
    results = [run_test("worker_runs_in_separate_process", t_worker_runs_in_separate_process)]
    raise SystemExit(summarise(results, "Phase 17"))


if __name__ == "__main__":
    main()
