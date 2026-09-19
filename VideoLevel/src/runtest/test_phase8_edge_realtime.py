"""Contracts for the bounded-latency edge camera runtime."""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.edge.realtime import (
    AnnexBSegmenter,
    BoundedSegmentQueue,
    EdgeRealtimeBudget,
    ProofEpochCoordinator,
)
from src.runtest._helpers import run_test, section, summarise


def _nal(nal_type: int, payload: bytes) -> bytes:
    return b"\x00\x00\x00\x01" + bytes([0x60 | nal_type]) + payload


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


def main():
    section("Phase 8 - Edge Realtime Runtime")
    results = [
        run_test("budget_requires_frame_pacing_and_bounded_latency", t_budget_requires_frame_pacing_and_bounded_latency),
        run_test("bounded_queue_drops_oldest_segment_not_camera_thread", t_bounded_queue_drops_oldest_segment_not_camera_thread),
        run_test("proof_epoch_is_generated_once_for_concurrent_segments", t_proof_epoch_is_generated_once_for_concurrent_segments),
        run_test("annexb_segmenter_emits_complete_idr_segment", t_annexb_segmenter_emits_complete_idr_segment),
    ]
    sys.exit(summarise(results, "Phase 8"))


if __name__ == "__main__":
    main()
