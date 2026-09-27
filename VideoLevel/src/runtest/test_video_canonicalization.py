"""Unit tests for normalization of embedded H.264 coefficient carriers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtest._helpers import run_test, section, summarise
from src.video_canonicalization import canonicalize_carrier_coefficients


def t_sign_carriers_normalize_to_positive_trailing_one() -> None:
    coefficients = [(3, 7, [0, -1, 2] + [0] * 13)]

    normalized = canonicalize_carrier_coefficients(coefficients, [(3, 7, -2)])

    assert normalized == [(3, 7, [0, 1, 2] + [0] * 13)]
    assert coefficients[0][2][1] == -1, "input coefficient data must remain unchanged"


def t_lsb_carriers_normalize_magnitude_and_handle_unit_value() -> None:
    coefficients = [(1, 4, [3, -5, 1] + [0] * 13)]

    normalized = canonicalize_carrier_coefficients(
        coefficients, [(1, 4, 0), (1, 4, 1), (1, 4, 2)]
    )

    assert normalized == [(1, 4, [2, -4, 0] + [0] * 13)]


def t_empty_carrier_set_returns_no_modifications() -> None:
    assert canonicalize_carrier_coefficients([(1, 0, [1] + [0] * 15)], []) == []


def t_missing_block_is_rejected() -> None:
    try:
        canonicalize_carrier_coefficients([(1, 0, [1] + [0] * 15)], [(2, 0, 0)])
    except ValueError as error:
        assert "unknown coefficient block" in str(error)
    else:
        raise AssertionError("unknown carrier block must be rejected")


def t_invalid_carrier_index_or_non_trailing_sign_is_rejected() -> None:
    coefficients = [(1, 0, [2, 0] + [0] * 14)]

    for position in ((1, 0, 16), (1, 0, -1)):
        try:
            canonicalize_carrier_coefficients(coefficients, [position])
        except ValueError:
            continue
        raise AssertionError(f"invalid carrier must be rejected: {position}")


def t_duplicate_carrier_is_rejected() -> None:
    coefficients = [(1, 0, [3] + [0] * 15)]
    try:
        canonicalize_carrier_coefficients(coefficients, [(1, 0, 0), (1, 0, 0)])
    except ValueError as error:
        assert "duplicate carrier" in str(error)
    else:
        raise AssertionError("duplicate carrier must be rejected")


def main() -> None:
    section("Video carrier canonicalization")
    results = [
        run_test("sign_carriers_normalize_to_positive_trailing_one", t_sign_carriers_normalize_to_positive_trailing_one),
        run_test("lsb_carriers_normalize_magnitude_and_handle_unit_value", t_lsb_carriers_normalize_magnitude_and_handle_unit_value),
        run_test("empty_carrier_set_returns_no_modifications", t_empty_carrier_set_returns_no_modifications),
        run_test("missing_block_is_rejected", t_missing_block_is_rejected),
        run_test("invalid_carrier_index_or_non_trailing_sign_is_rejected", t_invalid_carrier_index_or_non_trailing_sign_is_rejected),
        run_test("duplicate_carrier_is_rejected", t_duplicate_carrier_is_rejected),
    ]
    raise SystemExit(summarise(results, "Video carrier canonicalization"))


if __name__ == "__main__":
    main()
