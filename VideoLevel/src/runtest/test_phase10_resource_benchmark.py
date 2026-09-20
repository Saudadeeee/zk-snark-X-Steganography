"""Contracts for process-tree resource measurement."""

import os
import sys

import psutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from benchmark.resource_benchmark import _tree_usage
from src.runtest._helpers import run_test, section, summarise


class _ExitedProcess:
    def children(self, *, recursive: bool):
        assert recursive
        raise psutil.NoSuchProcess(12345)


def t_tree_usage_tolerates_process_exit_race():
    assert _tree_usage(_ExitedProcess()) == (0, 0.0)


def main():
    section("Phase 10 - Resource Benchmark Contract")
    results = [run_test("tree_usage_tolerates_process_exit_race", t_tree_usage_tolerates_process_exit_race)]
    sys.exit(summarise(results, "Phase 10"))


if __name__ == "__main__":
    main()
