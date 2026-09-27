"""FFmpeg validation must leave candidates for later patchability filtering."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.embedder import (
    _candidate_validation_target,
    _prepare_validated_patchable_positions,
    _validate_candidate_positions,
)
from unittest.mock import patch
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


def t_batch_validator_is_used_when_available() -> None:
    class BatchValidator:
        def __init__(self) -> None:
            self.request = None

        def __call__(self, _position):
            raise AssertionError("batch-capable validator must not run per position")

        def validate_batch(self, positions, *, target_positions, max_candidates):
            self.request = (target_positions, max_candidates)
            return positions[:target_positions], target_positions

    positions = [(index, 0, 1) for index in range(6)]
    validator = BatchValidator()
    validated, tried = _validate_candidate_positions(
        positions,
        validator,
        target_positions=4,
        max_candidates=5,
    )

    assert validated == positions[:4]
    assert tried == 4
    assert validator.request == (4, 5)


def t_patchability_filter_runs_before_batch_ffmpeg_validation() -> None:
    positions = [(index, 0, 1) for index in range(8)]
    patchable = positions[2:]

    class BatchValidator:
        def __init__(self) -> None:
            self.seen = None

        def validate_batch(self, candidates, *, target_positions, max_candidates):
            self.seen = (candidates, target_positions, max_candidates)
            return candidates, len(candidates)

    validator = BatchValidator()
    with patch("src.embedder._prune_patchable_positions", return_value=patchable) as prune:
        with patch("src.embedder._limit_positions_per_block", return_value=patchable) as limit:
            filtered, validated, tried = _prepare_validated_patchable_positions(
                positions,
                {"frame": "offsets"},
                validator,
                required_bits=2,
                max_modifications_per_block=1,
                max_candidates=10,
            )

    target = _candidate_validation_target(2)
    prune.assert_called_once_with(
        positions,
        {"frame": "offsets"},
        required_bits=target,
        max_modifications_per_block=1,
    )
    limit.assert_called_once_with(patchable, max_modifications_per_block=1)
    assert filtered == patchable
    assert validated == patchable
    assert tried == len(patchable)
    assert validator.seen == (patchable, target, 10)


def main() -> None:
    section("FFmpeg validation headroom")
    results = [
        run_test("validation_target_includes_patchability_headroom", t_validation_target_includes_patchability_headroom),
        run_test("validator_keeps_scanning_until_headroom_target", t_validator_keeps_scanning_until_headroom_target),
        run_test("validator_respects_candidate_scan_limit", t_validator_respects_candidate_scan_limit),
        run_test("batch_validator_is_used_when_available", t_batch_validator_is_used_when_available),
        run_test("patchability_filter_runs_before_batch_ffmpeg_validation", t_patchability_filter_runs_before_batch_ffmpeg_validation),
    ]
    raise SystemExit(summarise(results, "FFmpeg validation headroom"))


if __name__ == "__main__":
    main()
