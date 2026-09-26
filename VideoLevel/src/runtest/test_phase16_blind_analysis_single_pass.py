"""Blind-position derivation should analyze each input video only once."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.blind_sync import BlindOperatingContract, derive_blind_positions_operating_contract
from src.runtest._helpers import run_test, section, summarise


def t_operating_contract_reuses_single_analysis_result() -> None:
    coefficients = [(0, 0, [0, 4, 2] + [0] * 13)]
    frame_verified_data = {0: ({}, {}, b"rbsp")}
    nal_length_map = {(0, 0): 12}
    safe_positions = [(0, 0, 1)]
    analysis = (
        coefficients,
        frame_verified_data,
        {},
        nal_length_map,
        {},
        safe_positions,
    )
    contract = BlindOperatingContract(
        version="test-v1",
        dedup_per_block=False,
    )

    with patch("src.blind_sync.load_or_build_video_analysis", return_value=analysis) as load:
        positions, metadata = derive_blind_positions_operating_contract(
            "unused.h264",
            b"sync-key",
            required_bits=1,
            contract=contract,
        )

    assert load.call_count == 1
    assert positions == safe_positions
    assert metadata.idr_count == 1


def main() -> None:
    section("Phase 16 - Single-pass blind analysis")
    results = [
        run_test("operating_contract_reuses_single_analysis_result", t_operating_contract_reuses_single_analysis_result),
    ]
    raise SystemExit(summarise(results, "Phase 16"))


if __name__ == "__main__":
    main()
