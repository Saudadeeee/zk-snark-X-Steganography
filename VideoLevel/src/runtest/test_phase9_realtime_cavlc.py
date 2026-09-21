"""Contracts for the realtime CAVLC segment controller."""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.realtime_cavlc import CAVLCRealtimeBudget, RealtimeCAVLCScheduler
from src.bitstream.cavlc import get_run_before_table
from src.runtest._helpers import run_test, section, summarise


def t_scheduler_keeps_only_fresh_segments_under_pressure():
    scheduler = RealtimeCAVLCScheduler(CAVLCRealtimeBudget(fps=30.0, max_queue_segments=2), lambda _epoch: b"proof", lambda segment, _proof: segment)
    scheduler.submit(b"old", epoch=1)
    scheduler.submit(b"current", epoch=1)
    scheduler.submit(b"fresh", epoch=1)
    assert scheduler.dropped_segments == 1
    assert scheduler.process_next().output == b"current"
    assert scheduler.process_next().output == b"fresh"


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


def t_cavlc_run_before_tables_match_h264_reference_vlcs():
    assert get_run_before_table(4) == {
        "11": 0, "10": 1, "01": 2, "001": 3, "000": 4,
    }
    assert get_run_before_table(5) == {
        "11": 0, "10": 1, "011": 2, "010": 3, "001": 4, "000": 5,
    }
    assert get_run_before_table(6) == {
        "11": 0, "000": 1, "001": 2, "011": 3, "010": 4, "101": 5, "100": 6,
    }
    assert get_run_before_table(7)["00000000001"] == 14


def main():
    section("Phase 9 - Realtime CAVLC Controller")
    results = [
        run_test("scheduler_keeps_only_fresh_segments_under_pressure", t_scheduler_keeps_only_fresh_segments_under_pressure),
        run_test("scheduler_reuses_one_proof_per_epoch_and_reports_budget", t_scheduler_reuses_one_proof_per_epoch_and_reports_budget),
        run_test("cavlc_run_before_tables_match_h264_reference_vlcs", t_cavlc_run_before_tables_match_h264_reference_vlcs),
    ]
    sys.exit(summarise(results, "Phase 9"))


if __name__ == "__main__":
    main()
