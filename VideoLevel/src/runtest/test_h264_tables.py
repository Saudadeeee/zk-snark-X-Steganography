"""Regression tests for the H.264 CAVLC VLC tables in src/h264_tables.py.

Checks prefix-freeness, the Kraft sums required by ITU-T H.264 Tables
9-5/9-7/9-9/9-10, symbol coverage and spec spot values. Parser coverage lives
in test_demo_h264_explain.py (demo segmenter vs native tool + FFmpeg).
"""

import os
import sys
from fractions import Fraction

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.h264_tables import (  # noqa: E402
    COEFF_TOKEN_CHROMA_DC,
    COEFF_TOKEN_NC_0_1,
    COEFF_TOKEN_NC_2_3,
    COEFF_TOKEN_NC_4_7,
    RUN_BEFORE_TABLES,
    TOTAL_ZEROS_2x2,
    TOTAL_ZEROS_TABLES,
)
from src.runtest._helpers import run_test, section, summarise  # noqa: E402

# Missing codewords per ITU-T H.264 Tables 9-5/9-7/9-10 (all-zero codes are
# forbidden so a start code cannot be emulated): Kraft sum = 1 - 2^-len.
_INCOMPLETE_TABLES = {
    "coeff_token nC 0-1": 15,
    "coeff_token nC 2-3": 13,
    "coeff_token nC 4-7": 10,
    "total_zeros 4x4 TC=1": 9,
    "run_before zerosLeft>6": 11,
}


def _all_tables():
    tables = {
        "coeff_token nC 0-1": COEFF_TOKEN_NC_0_1,
        "coeff_token nC 2-3": COEFF_TOKEN_NC_2_3,
        "coeff_token nC 4-7": COEFF_TOKEN_NC_4_7,
        "coeff_token chroma DC": COEFF_TOKEN_CHROMA_DC,
    }
    tables.update({f"total_zeros 4x4 TC={tc}": t for tc, t in TOTAL_ZEROS_TABLES.items()})
    tables.update({f"total_zeros 2x2 TC={tc}": t for tc, t in TOTAL_ZEROS_2x2.items()})
    tables.update({
        (f"run_before zerosLeft={zl}" if zl < 7 else "run_before zerosLeft>6"): t
        for zl, t in RUN_BEFORE_TABLES.items()
    })
    return tables


def _code_for(table: dict, symbol) -> str:
    matches = [code for code, value in table.items() if value == symbol]
    assert len(matches) == 1, f"symbol {symbol!r} has {len(matches)} codewords"
    return matches[0]


def t_vlc_tables_are_prefix_free_with_spec_kraft_sums():
    for name, table in _all_tables().items():
        codes = list(table)
        for a in codes:
            for b in codes:
                assert a == b or not b.startswith(a), f"{name}: '{a}' is a prefix of '{b}'"
        assert all(set(code) <= {"0", "1"} for code in codes), f"{name}: non-binary codeword"
        assert len(set(table.values())) == len(table), f"{name}: duplicate symbols"
        kraft = sum(Fraction(1, 2 ** len(code)) for code in codes)
        missing = _INCOMPLETE_TABLES.get(name)
        expected = 1 - Fraction(1, 2 ** missing) if missing else Fraction(1)
        assert kraft == expected, f"{name}: Kraft sum {kraft} != {expected}"


def t_coeff_token_tables_cover_every_symbol():
    expected = {(tc, t1) for tc in range(17) for t1 in range(min(tc, 3) + 1)}
    for name, table in (("nC0-1", COEFF_TOKEN_NC_0_1), ("nC2-3", COEFF_TOKEN_NC_2_3),
                        ("nC4-7", COEFF_TOKEN_NC_4_7)):
        assert set(table.values()) == expected, f"{name}: symbol set mismatch"
    assert set(COEFF_TOKEN_CHROMA_DC.values()) == {
        (tc, t1) for tc in range(5) for t1 in range(min(tc, 3) + 1)
    }


def t_total_zeros_and_run_before_cover_every_symbol():
    assert sorted(TOTAL_ZEROS_TABLES) == list(range(1, 16))
    for tc, table in TOTAL_ZEROS_TABLES.items():
        assert set(table.values()) == set(range(16 - tc + 1)), f"total_zeros TC={tc}"
    assert sorted(TOTAL_ZEROS_2x2) == [1, 2, 3]
    for tc, table in TOTAL_ZEROS_2x2.items():
        assert set(table.values()) == set(range(4 - tc + 1)), f"total_zeros 2x2 TC={tc}"
    assert sorted(RUN_BEFORE_TABLES) == list(range(1, 8))
    for zl, table in RUN_BEFORE_TABLES.items():
        top = zl if zl < 7 else 14
        assert set(table.values()) == set(range(top + 1)), f"run_before zerosLeft={zl}"


def t_spec_spot_values():
    assert _code_for(COEFF_TOKEN_NC_0_1, (2, 2)) == "001"
    assert _code_for(COEFF_TOKEN_NC_0_1, (13, 1)) == "000000000000001"
    assert _code_for(COEFF_TOKEN_NC_0_1, (16, 0)) == "0000000000000100"
    assert _code_for(COEFF_TOKEN_NC_4_7, (1, 0)) == "001111"
    assert _code_for(COEFF_TOKEN_NC_4_7, (0, 0)) == "1111"
    assert _code_for(COEFF_TOKEN_CHROMA_DC, (0, 0)) == "01"
    assert _code_for(COEFF_TOKEN_CHROMA_DC, (1, 1)) == "1"
    assert TOTAL_ZEROS_2x2[1] == {"1": 0, "01": 1, "001": 2, "000": 3}
    assert TOTAL_ZEROS_2x2[2] == {"1": 0, "01": 1, "00": 2}
    assert _code_for(RUN_BEFORE_TABLES[7], 14) == "00000000001"


def main():
    section("H.264 CAVLC VLC tables")
    results = [
        run_test("vlc_tables_are_prefix_free_with_spec_kraft_sums", t_vlc_tables_are_prefix_free_with_spec_kraft_sums),
        run_test("coeff_token_tables_cover_every_symbol", t_coeff_token_tables_cover_every_symbol),
        run_test("total_zeros_and_run_before_cover_every_symbol", t_total_zeros_and_run_before_cover_every_symbol),
        run_test("spec_spot_values", t_spec_spot_values),
    ]
    sys.exit(summarise(results, "H.264 tables"))


if __name__ == "__main__":
    main()
