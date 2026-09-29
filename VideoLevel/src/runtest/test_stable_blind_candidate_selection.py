"""Unit tests for deterministic fallback selection of blind CAVLC carriers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.stego import select_rederivable_stable_candidate


def test_falls_back_to_first_safe_candidate_when_earlier_failures_stay_unsafe():
    candidates = [2, 5, 9]
    safe_in_current_block = {2: False, 5: True, 9: True}
    becomes_safe_after_toggle = {(5, 2): False}

    selected = select_rederivable_stable_candidate(
        candidates,
        safe_in_current_block,
        lambda selected, earlier: becomes_safe_after_toggle.get(
            (selected, earlier), False
        ),
    )

    assert selected == 5


def test_rejects_fallback_if_an_earlier_candidate_becomes_safe_after_toggle():
    candidates = [2, 5]
    safe_in_current_block = {2: False, 5: True}

    selected = select_rederivable_stable_candidate(
        candidates,
        safe_in_current_block,
        lambda selected, earlier: selected == 5 and earlier == 2,
    )

    assert selected is None


def test_keeps_first_safe_candidate_without_fallback_checks():
    candidates = [2, 5]
    safe_in_current_block = {2: True, 5: True}

    selected = select_rederivable_stable_candidate(
        candidates,
        safe_in_current_block,
        lambda _selected, _earlier: True,
    )

    assert selected == 2


def test_returns_none_when_no_candidate_is_safe():
    candidates = [2, 5]
    safe_in_current_block = {2: False, 5: False}

    selected = select_rederivable_stable_candidate(
        candidates,
        safe_in_current_block,
        lambda _selected, _earlier: False,
    )

    assert selected is None
