"""Contracts for the realtime CAVLC segment controller (src/realtime_cavlc.py)."""

import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.realtime_cavlc import CAVLCRealtimeBudget, RealtimeCAVLCScheduler  # noqa: E402
from src.runtest._helpers import run_test, section, summarise  # noqa: E402


def t_scheduler_keeps_only_fresh_segments_under_pressure():
    scheduler = RealtimeCAVLCScheduler(CAVLCRealtimeBudget(fps=30.0, max_queue_segments=2), lambda _epoch: b"proof", lambda segment, _proof: segment)
    scheduler.submit(b"old", epoch=1)
    scheduler.submit(b"current", epoch=1)
    scheduler.submit(b"fresh", epoch=1)
    assert scheduler.dropped_segments == 1
    assert scheduler.process_next().output == b"current"
    assert scheduler.process_next().output == b"fresh"


def t_scheduler_bounds_queue_by_bytes_and_rejects_oversized_segment():
    scheduler = RealtimeCAVLCScheduler(
        CAVLCRealtimeBudget(fps=30.0, max_queue_segments=4, max_queued_bytes=5, max_segment_bytes=4),
        lambda _epoch: b"proof",
        lambda segment, _proof: segment,
    )
    scheduler.submit(b"1234", epoch=1)
    scheduler.submit(b"ab", epoch=1)
    assert scheduler.dropped_segments == 1
    assert scheduler.queued_bytes == 2
    try:
        scheduler.submit(b"12345", epoch=1)
    except ValueError as exc:
        assert "maximum" in str(exc)
    else:
        raise AssertionError("oversized segment must be rejected")
    try:
        scheduler.submit(bytearray(b"mut"), epoch=1)
    except TypeError as exc:
        assert "immutable bytes" in str(exc)
    else:
        raise AssertionError("mutable segment input must not bypass the byte bound")
    assert scheduler.queued_bytes == 2
    assert scheduler.process_next().output == b"ab"
    assert scheduler.queued_bytes == 0


def t_scheduler_rejects_epoch_regression():
    scheduler = RealtimeCAVLCScheduler(CAVLCRealtimeBudget(), lambda _epoch: b"p", lambda data, _p: data)
    scheduler.submit(b"new", epoch=3)
    try:
        scheduler.submit(b"old", epoch=2)
    except ValueError as exc:
        assert "monotonic" in str(exc)
    else:
        raise AssertionError("scheduler must reject an epoch regression")


def t_realtime_budget_rejects_non_finite_values():
    for kwargs in ({"fps": float("nan")}, {"fps": float("inf")}, {"max_p95_latency_s": float("nan")}):
        try:
            CAVLCRealtimeBudget(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid realtime budget accepted: {kwargs}")


def t_scheduler_reuses_one_proof_when_consumers_race():
    calls = 0
    calls_lock = threading.Lock()

    def proof(_epoch):
        nonlocal calls
        with calls_lock:
            calls += 1
        return b"proof"

    scheduler = RealtimeCAVLCScheduler(CAVLCRealtimeBudget(), proof, lambda data, _proof: data)
    scheduler.submit(b"one", epoch=4)
    scheduler.submit(b"two", epoch=4)
    results = []
    workers = [threading.Thread(target=lambda: results.append(scheduler.process_next())) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=2)
        assert not worker.is_alive()
    assert calls == 1
    assert len(results) == 2 and all(result is not None for result in results)
    assert scheduler.queued_bytes == 0


def t_scheduler_bounds_epoch_cache_and_latency_sample_history():
    proof_calls = []
    scheduler = RealtimeCAVLCScheduler(
        CAVLCRealtimeBudget(max_cached_epochs=2, max_latency_samples=2),
        lambda epoch: proof_calls.append(epoch) or b"proof",
        lambda data, _proof: data,
    )
    for epoch in (1, 1, 2, 3, 3):
        scheduler.submit(b"x", epoch=epoch)
        assert scheduler.process_next() is not None
    report = scheduler.report()
    assert proof_calls == [1, 2, 3]
    assert report.processed_segments == 5
    assert len(scheduler._latencies) == 2


def t_scheduler_reuses_one_proof_per_epoch_and_reports_budget():
    calls = 0

    def proof(epoch: int) -> bytes:
        nonlocal calls
        calls += 1
        return f"proof-{epoch}".encode()

    scheduler = RealtimeCAVLCScheduler(CAVLCRealtimeBudget(fps=30.0), proof, lambda segment, _proof: segment)
    scheduler.submit(b"a", epoch=7)
    scheduler.submit(b"b", epoch=7)
    scheduler.process_next()
    scheduler.process_next()
    assert calls == 1
    assert scheduler.report().accepted


def t_scheduler_counts_failed_segments_and_rejects_report():
    def patch(segment, _proof):
        if segment == b"bad":
            raise RuntimeError("patch failed")
        return segment

    def proof(epoch):
        if epoch == 9:
            raise RuntimeError("prover failed")
        return b"proof"

    scheduler = RealtimeCAVLCScheduler(CAVLCRealtimeBudget(fps=1.0, max_queue_segments=4), proof, patch)
    scheduler.submit(b"ok", epoch=1)
    scheduler.submit(b"bad", epoch=1)
    first = scheduler.process_next()
    assert first.output == b"ok" and first.proof_s > 0.0
    assert first.end_to_end_latency_s >= first.latency_s
    assert scheduler.report().accepted and scheduler.report().failed_segments == 0
    try:
        scheduler.process_next()
    except RuntimeError as exc:
        assert "patch failed" in str(exc)
    else:
        raise AssertionError("patch failure must propagate")
    scheduler.submit(b"later", epoch=9)
    try:
        scheduler.process_next()
    except RuntimeError as exc:
        assert "prover failed" in str(exc)
    else:
        raise AssertionError("proof failure must propagate")
    report = scheduler.report()
    assert report.failed_segments == 2, report
    assert report.processed_segments == 1 and report.dropped_segments == 0
    assert not report.accepted
    assert scheduler.queued_bytes == 0


def t_scheduler_reports_end_to_end_and_proof_latency():
    import time as _time

    def slow_proof(_epoch):
        _time.sleep(0.02)
        return b"proof"

    scheduler = RealtimeCAVLCScheduler(CAVLCRealtimeBudget(fps=1.0), slow_proof, lambda data, _p: data)
    scheduler.submit(b"a", epoch=1)
    _time.sleep(0.03)
    first = scheduler.process_next()
    scheduler.submit(b"b", epoch=1)
    second = scheduler.process_next()
    assert first.proof_s >= 0.015 and second.proof_s == 0.0
    assert first.end_to_end_latency_s >= 0.045, first
    report = scheduler.report()
    assert report.end_to_end_p95_latency_s >= first.end_to_end_latency_s
    assert report.proof_p95_s >= 0.015
    assert report.p95_latency_s < report.end_to_end_p95_latency_s


def main():
    section("Realtime scheduler")
    results = [
        run_test("scheduler_keeps_only_fresh_segments_under_pressure", t_scheduler_keeps_only_fresh_segments_under_pressure),
        run_test("scheduler_bounds_queue_by_bytes_and_rejects_oversized_segment", t_scheduler_bounds_queue_by_bytes_and_rejects_oversized_segment),
        run_test("scheduler_rejects_epoch_regression", t_scheduler_rejects_epoch_regression),
        run_test("realtime_budget_rejects_non_finite_values", t_realtime_budget_rejects_non_finite_values),
        run_test("scheduler_reuses_one_proof_when_consumers_race", t_scheduler_reuses_one_proof_when_consumers_race),
        run_test("scheduler_bounds_epoch_cache_and_latency_sample_history", t_scheduler_bounds_epoch_cache_and_latency_sample_history),
        run_test("scheduler_reuses_one_proof_per_epoch_and_reports_budget", t_scheduler_reuses_one_proof_per_epoch_and_reports_budget),
        run_test("scheduler_counts_failed_segments_and_rejects_report", t_scheduler_counts_failed_segments_and_rejects_report),
        run_test("scheduler_reports_end_to_end_and_proof_latency", t_scheduler_reports_end_to_end_and_proof_latency),
    ]
    sys.exit(summarise(results, "Realtime scheduler"))


if __name__ == "__main__":
    main()
