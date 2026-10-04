"""Poseidon hash over the BN254 scalar field, compatible with circomlib's ``Poseidon(n)``.

Only 1 and 2 inputs are needed (camera public key and Merkle nodes). The
round constants and MDS matrices are circomlib's reference parameters
(``poseidon_constants.json``); this is the straightforward reference
permutation, which circomlib's optimized circuit computes identically.
Cross-checked against the compiled circuit's witness in the test suite.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

FIELD_MODULUS = 21888242871839275222246405745257275088548364400416034343698204186575808495617
FULL_ROUNDS = 8
_CONSTANTS_FILE = Path(__file__).with_name("poseidon_constants.json")


@lru_cache(maxsize=None)
def _parameters(width: int) -> tuple[tuple[int, ...], tuple[tuple[int, ...], ...], int]:
    data = json.loads(_CONSTANTS_FILE.read_text(encoding="utf-8"))
    table = data[str(width)]
    constants = tuple(int(value) for value in table["C"])
    matrix = tuple(tuple(int(value) for value in row) for row in table["M"])
    return constants, matrix, int(data["rounds_partial"][str(width)])


def _check_field_element(value: int) -> int:
    if type(value) is not int or not 0 <= value < FIELD_MODULUS:
        raise ValueError("Poseidon inputs must be integers in [0, BN254 scalar field)")
    return value


def poseidon(inputs: list[int] | tuple[int, ...]) -> int:
    """circomlib ``Poseidon(len(inputs))`` for one or two field elements."""
    if len(inputs) not in (1, 2):
        raise ValueError("this Poseidon supports one or two inputs")
    width = len(inputs) + 1
    constants, matrix, partial_rounds = _parameters(width)
    state = [0, *(_check_field_element(value) for value in inputs)]
    for round_index in range(FULL_ROUNDS + partial_rounds):
        state = [(value + constants[round_index * width + i]) % FIELD_MODULUS for i, value in enumerate(state)]
        full = round_index < FULL_ROUNDS // 2 or round_index >= partial_rounds + FULL_ROUNDS // 2
        state = [pow(value, 5, FIELD_MODULUS) if full or i == 0 else value for i, value in enumerate(state)]
        state = [sum(row[j] * state[j] for j in range(width)) % FIELD_MODULUS for row in matrix]
    return state[0]
