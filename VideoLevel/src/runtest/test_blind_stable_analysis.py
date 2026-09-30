from __future__ import annotations

from src.core.stego import CAVLCSafetyFilter


def test_stable_only_safety_selects_rederivable_full_safe_carriers(monkeypatch) -> None:
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

    # The stable profile may choose a later candidate when the first
    # structural candidate is not bit-length safe. Every selected carrier
    # must still be in the full safety set and re-derive identically after its
    # own LSB is toggled (the cover/stego symmetry required by blind extraction).
    assert set(stable_positions).issubset(full_positions)
    assert len({position[:2] for position in stable_positions}) == len(
        stable_positions
    )
    for mb, block, coeff_idx in stable_positions:
        coeffs = next(
            values
            for mb_i, block_i, values in coefficients
            if (mb_i, block_i) == (mb, block)
        )
        trailing = CAVLCSafetyFilter()._detect_trailing_ones(coeffs)
        assert coeff_idx != 0
        assert coeff_idx not in trailing
        assert abs(coeffs[coeff_idx]) >= 4

        stego_coefficients = [
            (mb_i, block_i, values[:]) for mb_i, block_i, values in coefficients
        ]
        stego_block = next(
            values
            for mb_i, block_i, values in stego_coefficients
            if (mb_i, block_i) == (mb, block)
        )
        value = stego_block[coeff_idx]
        stego_block[coeff_idx] = (abs(value) ^ 1) * (1 if value > 0 else -1)
        rederived_positions = CAVLCSafetyFilter().get_safe_positions(
            stego_coefficients,
            stable_carriers_only=True,
        )
        assert (mb, block, coeff_idx) in rederived_positions


def test_stable_profile_stops_after_first_rederivable_carrier(monkeypatch) -> None:
    coefficients = [(0, 0, [0, 7, 0, 0, 8, 9] + [0] * 10)]
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

    assert stable_positions == [(0, 0, 1)]
    assert set(stable_positions).issubset(full_positions)
    assert calls["stable"] < calls["full"]
