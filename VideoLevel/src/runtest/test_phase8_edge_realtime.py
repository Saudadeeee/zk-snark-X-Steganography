"""Contracts for the bounded-latency edge camera runtime."""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.edge.realtime import (
    AnnexBSegmenter,
    BoundedSegmentQueue,
    EdgeRealtimeBudget,
    ProofEpochCoordinator,
)
from benchmark.edge_realtime import assess_realtime, percentile
from src.runtest._helpers import run_test, section, summarise


def _nal(nal_type: int, payload: bytes) -> bytes:
    return b"\x00\x00\x00\x01" + bytes([0x60 | nal_type]) + payload


def _native_relay() -> Path:
    root = Path(__file__).resolve().parents[2]
    relay = root / "native" / "edge-build" / "Release" / "zkstego_annexb_relay.exe"
    if relay.is_file():
        return relay
    cmake = "cmake"
    subprocess.run([cmake, "-S", "native", "-B", "native/edge-build"], cwd=root, check=True)
    subprocess.run([cmake, "--build", "native/edge-build", "--config", "Release"], cwd=root, check=True)
    assert relay.is_file(), "CMake build did not produce native relay"
    return relay


def t_budget_requires_frame_pacing_and_bounded_latency():
    budget = EdgeRealtimeBudget(fps=30.0, max_segment_latency_s=1.0, max_queue_segments=2)
    assert round(budget.frame_interval_ms, 3) == 33.333
    assert budget.accepts(p95_latency_s=0.8, dropped_segments=0)
    assert not budget.accepts(p95_latency_s=1.01, dropped_segments=0)
    assert not budget.accepts(p95_latency_s=0.2, dropped_segments=1)


def t_bounded_queue_drops_oldest_segment_not_camera_thread():
    queue = BoundedSegmentQueue(max_segments=2)
    queue.put(b"first")
    queue.put(b"second")
    queue.put(b"third")
    assert queue.dropped_segments == 1
    assert queue.get(timeout_s=0.01) == b"second"
    assert queue.get(timeout_s=0.01) == b"third"


def t_proof_epoch_is_generated_once_for_concurrent_segments():
    calls = 0
    lock = threading.Lock()

    def generate(epoch: int) -> bytes:
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(0.01)
        return f"proof-{epoch}".encode()

    coordinator = ProofEpochCoordinator(generate)
    results: list[bytes] = []
    workers = [threading.Thread(target=lambda: results.append(coordinator.get(7))) for _ in range(6)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert calls == 1
    assert results == [b"proof-7"] * 6


def t_annexb_segmenter_emits_complete_idr_segment():
    stream = _nal(7, b"sps") + _nal(8, b"pps") + _nal(5, b"idr-a") + _nal(1, b"p") + _nal(5, b"idr-b")
    segmenter = AnnexBSegmenter()
    produced = []
    for offset in range(0, len(stream), 5):
        produced.extend(segmenter.feed(stream[offset:offset + 5]))
    assert len(produced) == 1
    assert b"idr-a" in produced[0]
    assert b"idr-b" not in produced[0]
    assert produced[0].startswith(_nal(7, b"sps"))


def t_edge_benchmark_rejects_drops_or_over_budget_p95():
    assert percentile([0.01, 0.02, 0.03, 0.04], 95) == 0.04
    assert assess_realtime(p95_latency_s=0.5, dropped_segments=0, max_latency_s=1.0) == "pass"
    assert assess_realtime(p95_latency_s=1.1, dropped_segments=0, max_latency_s=1.0) == "fail_latency"
    assert assess_realtime(p95_latency_s=0.1, dropped_segments=1, max_latency_s=1.0) == "fail_drops"


def t_native_relay_keeps_binary_annexb_bytes_on_windows():
    relay = _native_relay()
    source = _nal(7, b"sps\x1a") + _nal(8, b"pps") + _nal(5, b"idr")
    result = subprocess.run(
        [str(relay), "--sei-payload-hex", "CAFE"], input=source,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert len(result.stdout) > len(source)
    assert b"sps\x1a" in result.stdout


def main():
    section("Phase 8 - Edge Realtime Runtime")
    results = [
        run_test("budget_requires_frame_pacing_and_bounded_latency", t_budget_requires_frame_pacing_and_bounded_latency),
        run_test("bounded_queue_drops_oldest_segment_not_camera_thread", t_bounded_queue_drops_oldest_segment_not_camera_thread),
        run_test("proof_epoch_is_generated_once_for_concurrent_segments", t_proof_epoch_is_generated_once_for_concurrent_segments),
        run_test("annexb_segmenter_emits_complete_idr_segment", t_annexb_segmenter_emits_complete_idr_segment),
        run_test("edge_benchmark_rejects_drops_or_over_budget_p95", t_edge_benchmark_rejects_drops_or_over_budget_p95),
        run_test("native_relay_keeps_binary_annexb_bytes_on_windows", t_native_relay_keeps_binary_annexb_bytes_on_windows),
    ]
    sys.exit(summarise(results, "Phase 8"))


if __name__ == "__main__":
    main()
