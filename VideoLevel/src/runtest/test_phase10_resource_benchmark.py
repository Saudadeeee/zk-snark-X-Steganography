"""Contracts for process-tree resource measurement."""

import os
import sys

import psutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from benchmark.resource_benchmark import _tree_usage
from benchmark.sec1_quality import _require_full_payload
from src.runtest._helpers import run_test, section, summarise


class _ExitedProcess:
    def children(self, *, recursive: bool):
        assert recursive
        raise psutil.NoSuchProcess(12345)


def t_tree_usage_tolerates_process_exit_race():
    assert _tree_usage(_ExitedProcess()) == (0, 0.0)


def t_quality_benchmark_rejects_zero_payload_result():
    try:
        _require_full_payload({"akiyo": {"embedded_bits": 0, "required_bits": 1176}})
    except RuntimeError as exc:
        assert "akiyo" in str(exc)
        return
    raise AssertionError("quality benchmark must reject a result without its full payload")


def main():
    section("Phase 10 - Resource Benchmark Contract")
    results = [
        run_test("tree_usage_tolerates_process_exit_race", t_tree_usage_tolerates_process_exit_race),
        run_test("quality_benchmark_rejects_zero_payload_result", t_quality_benchmark_rejects_zero_payload_result),
    ]
    sys.exit(summarise(results, "Phase 10"))


if __name__ == "__main__":
    main()
