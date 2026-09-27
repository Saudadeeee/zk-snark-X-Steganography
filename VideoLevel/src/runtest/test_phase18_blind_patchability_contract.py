"""Blind position contracts can reproduce embedder patchability filtering."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.blind_sync import BlindOperatingContract, derive_blind_positions_operating_contract
from src.runtest._helpers import run_test, section, summarise


def t_patchable_contract_uses_embedder_headroom_and_modification_limit() -> None:
    safe_positions = [(idx, 0, 1) for idx in range(8)]
    analysis = ([], {0: ({}, {}, b"rbsp")}, {}, {}, {}, safe_positions)
    contract = BlindOperatingContract(
        version="patchable-test-v1",
        dedup_per_block=False,
        require_bitstream_patchable=True,
        patchability_headroom=4,
    )

    def retain_requested(positions, frame_data, *, required_bits, max_modifications_per_block):
        assert frame_data == analysis[1]
        assert max_modifications_per_block == 1
        return positions[:required_bits]

    with patch("src.blind_sync.load_or_build_video_analysis", return_value=analysis), patch(
        "src.embedder._prune_patchable_positions", side_effect=retain_requested
    ) as prune:
        positions, _metadata = derive_blind_positions_operating_contract(
            "unused.h264",
            b"same-chaos-key",
            required_bits=2,
            contract=contract,
        )

    prune.assert_called_once()
    assert prune.call_args.kwargs["required_bits"] == 6
    assert len(positions) == 2


def main() -> None:
    section("Phase 18 - Blind patchability contract")
    results = [
        run_test(
            "patchable_contract_uses_embedder_headroom_and_modification_limit",
            t_patchable_contract_uses_embedder_headroom_and_modification_limit,
        ),
    ]
    raise SystemExit(summarise(results, "Phase 18"))


if __name__ == "__main__":
    main()
