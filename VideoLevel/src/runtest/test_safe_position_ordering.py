from collections import Counter

from src.core.stego import CAVLCSafetyFilter


def test_unordered_safe_positions_preserve_exact_capacity() -> None:
    coefficients = [
        (395, 0, [0, 4] + [0] * 14),
        (0, 0, [0, 6] + [0] * 14),
        (22, 0, [0, 8] + [0] * 14),
    ]
    safety_filter = CAVLCSafetyFilter(enable_bit_length_check=False)

    ordered = safety_filter.get_safe_positions(coefficients)
    unsorted = safety_filter.get_safe_positions(
        coefficients,
        interleave_positions=False,
    )

    assert Counter(unsorted) == Counter(ordered)
    assert ordered != unsorted
    assert unsorted == [(395, 0, 1), (0, 0, 1), (22, 0, 1)]
