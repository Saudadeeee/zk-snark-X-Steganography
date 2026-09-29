"""Reconstruction must not accept a payload after any changed block was skipped."""

from __future__ import annotations

from src.embedder import _assess_reconstruction_application


def test_skipped_modified_block_forces_reembedding_even_with_enough_positions() -> None:
    used = [(0, 0, 1), (1, 0, 1), (2, 0, 1), (3, 0, 1)]
    modified = {(0, 0), (1, 0)}
    applied = {(0, 0)}

    accepted, missing = _assess_reconstruction_application(
        used,
        modified_blocks=modified,
        applied_blocks=applied,
        required_positions=3,
    )

    assert accepted is None
    assert missing == {(1, 0)}


def test_complete_reconstruction_keeps_payload_order_and_required_prefix() -> None:
    used = [(3, 0, 1), (2, 0, 1), (1, 0, 1), (0, 0, 1)]

    accepted, missing = _assess_reconstruction_application(
        used,
        modified_blocks={(1, 0)},
        applied_blocks={(1, 0)},
        required_positions=3,
    )

    assert accepted == used[:3]
    assert missing == set()
