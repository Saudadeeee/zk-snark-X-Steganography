"""Fail-closed RBSP surgery needed to finalize a CAVLC proof after encoding."""

from __future__ import annotations

import pytest

from src.bitstream.rbsp_patch import replace_codewords


def _rbsp(syntax_bits: str) -> bytes:
    bits = syntax_bits + "1"
    bits += "0" * ((-len(bits)) % 8)
    return bytes(int(bits[index:index + 8], 2) for index in range(0, len(bits), 8))


def test_variable_length_codewords_preserve_every_other_syntax_bit() -> None:
    original = _rbsp("1011010011")
    rewritten = replace_codewords(
        original,
        [(2, 5, [0, 0]), (8, 10, [1, 0, 1, 1])],
    )
    assert rewritten == _rbsp("10001001011")


def test_empty_replacement_set_preserves_rbsp_exactly() -> None:
    original = _rbsp("11100010")
    assert replace_codewords(original, []) == original


@pytest.mark.parametrize(
    "replacements",
    [
        [(1, 5, [1]), (4, 7, [0])],
        [(1, 5, [1]), (1, 5, [0])],
        [(0, 9, [1])],
        [(4, 3, [1])],
        [(-1, 2, [1])],
        [(0, 1, [])],
        [(0, 1, [2])],
        [(0, 1, [True])],
    ],
)
def test_invalid_or_overlapping_codeword_ranges_fail_closed(replacements: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        replace_codewords(_rbsp("10101010"), replacements)


def test_missing_rbsp_stop_bit_is_rejected() -> None:
    with pytest.raises(ValueError, match="stop bit"):
        replace_codewords(b"\x00\x00", [(0, 1, [1])])
