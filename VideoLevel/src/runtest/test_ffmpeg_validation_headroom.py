"""FFmpeg validation must leave candidates for later patchability filtering."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.embedder import (
    _candidate_validation_target,
    _validate_candidate_positions,
)
from src.runtest._helpers import run_test, section, summarise


def t_validation_target_includes_patchability_headroom() -> None:
    assert _candidate_validation_target(320) == 576
    assert _candidate_validation_target(1) == 257
    assert _candidate_validation_target(0) == 0


def t_validator_keeps_scanning_until_headroom_target() -> None:
    candidates = [(index, 0, 1) for index in range(8)]
    validated, tried = _validate_candidate_positions(
        candidates,
        lambda position: position[0] % 2 == 0,
        target_positions=3,
        max_candidates=len(candidates),
    )

    assert validated == [(0, 0, 1), (2, 0, 1), (4, 0, 1)]
    assert tried == 5


def t_validator_respects_candidate_scan_limit() -> None:
    candidates = [(index, 0, 1) for index in range(8)]
    validated, tried = _validate_candidate_positions(
        candidates,
        lambda _position: True,
        target_positions=6,
        max_candidates=4,
    )

    assert len(validated) == 4
    assert tried == 4


def main() -> None:
    section("FFmpeg validation headroom")
    results = [
        run_test("validation_target_includes_patchability_headroom", t_validation_target_includes_patchability_headroom),
        run_test("validator_keeps_scanning_until_headroom_target", t_validator_keeps_scanning_until_headroom_target),
        run_test("validator_respects_candidate_scan_limit", t_validator_respects_candidate_scan_limit),
    ]
    raise SystemExit(summarise(results, "FFmpeg validation headroom"))


if __name__ == "__main__":
    main()
