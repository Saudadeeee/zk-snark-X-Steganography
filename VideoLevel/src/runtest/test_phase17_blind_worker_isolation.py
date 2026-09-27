"""The heavy blind comparison must release each video's parser heap."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from types import SimpleNamespace

from benchmark.blind_core_trial import (
    BLIND_SYNC_KEY,
    _position_match_stats,
    _select_operating_asset,
    _worker_process_id,
    run_isolated,
)
from benchmark.locked_operating_contract import LOCKED_CHAOS_KEY
from src.runtest._helpers import run_test, section, summarise


def t_worker_runs_in_separate_process() -> None:
    worker_pid = run_isolated(_worker_process_id)
    assert isinstance(worker_pid, int)
    assert worker_pid != os.getpid()


def t_asset_selection_uses_locked_sidecar_contract() -> None:
    expected = SimpleNamespace(
        sequence_name="deadline_q22_g1_600f",
        video_path="cover.h264",
        stego_path="stego.h264",
        bits_required=1232,
    )
    with patch(
        "benchmark.blind_core_trial.load_best_locked_operating_contract",
        return_value=expected,
    ) as load_contract:
        asset = _select_operating_asset(required_bits=1232)

    load_contract.assert_called_once()
    assert asset == ("deadline_q22_g1_600f", "cover.h264", "stego.h264", 1232)


def t_position_comparison_measures_set_and_order() -> None:
    derived = [(1, 0, 2), (2, 0, 1), (3, 0, 4)]
    embedded = [(1, 0, 2), (2, 0, 3), (4, 0, 4)]

    stats = _position_match_stats(derived, embedded)

    assert stats == {
        "set_overlap": 1,
        "set_overlap_ratio": 1 / 3,
        "prefix_match": 1,
        "prefix_match_ratio": 1 / 3,
    }


def t_blind_sync_key_matches_embedder_chaos_key() -> None:
    assert BLIND_SYNC_KEY == LOCKED_CHAOS_KEY


def main() -> None:
    section("Phase 17 - Isolated blind-analysis worker")
    results = [
        run_test("worker_runs_in_separate_process", t_worker_runs_in_separate_process),
        run_test("asset_selection_uses_locked_sidecar_contract", t_asset_selection_uses_locked_sidecar_contract),
        run_test("position_comparison_measures_set_and_order", t_position_comparison_measures_set_and_order),
        run_test("blind_sync_key_matches_embedder_chaos_key", t_blind_sync_key_matches_embedder_chaos_key),
    ]
    raise SystemExit(summarise(results, "Phase 17"))


if __name__ == "__main__":
    main()
