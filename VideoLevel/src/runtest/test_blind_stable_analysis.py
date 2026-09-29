from __future__ import annotations

from src.blind_sync import _stable_candidate_index
from src.core.stego import CAVLCSafetyFilter


def test_stable_only_safety_matches_full_safe_positions_for_blind_candidates(
    monkeypatch,
) -> None:
    coefficients = [
        (0, 0, [0, 4, 5, 6, 7, -8, 2] + [0] * 9),
        (0, 1, [0, 3, -4, 2, 1] + [0] * 11),
        (0, 2, [0, 3, -2, 1] + [0] * 12),
    ]
    original_verify = CAVLCSafetyFilter._verify_block_bit_length_invariance
    calls = {"full": 0, "stable": 0}
    active_profile = "full"

    def count_verify(self, *args, **kwargs):
        calls[active_profile] += 1
        return original_verify(self, *args, **kwargs)

    monkeypatch.setattr(
        CAVLCSafetyFilter,
        "_verify_block_bit_length_invariance",
        count_verify,
    )

    full_positions = CAVLCSafetyFilter().get_safe_positions(coefficients)
    active_profile = "stable"
    stable_positions = CAVLCSafetyFilter().get_safe_positions(
        coefficients,
        stable_carriers_only=True,
    )

    expected = []
    for mb, block, coeffs in coefficients:
        candidate = _stable_candidate_index(
            coeffs,
            CAVLCSafetyFilter()._detect_trailing_ones(coeffs),
        )
        if candidate is not None:
            expected.extend(
                position
                for position in full_positions
                if position[:2] == (mb, block) and position[2] == candidate
            )

    assert stable_positions == expected
    assert calls["stable"] < calls["full"]
