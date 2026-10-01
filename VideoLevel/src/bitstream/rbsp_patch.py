"""Validated variable-length CAVLC codeword replacement in one H.264 RBSP.

This low-level operation changes only caller-specified codeword bit ranges.
The caller remains responsible for validating the replacement CAVLC syntax,
neighbor context, carrier profile, and resulting video before publication.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


CodewordReplacement = tuple[int, int, Sequence[int]]


def replace_codewords(
    rbsp: bytes,
    replacements: Sequence[CodewordReplacement],
) -> bytes:
    """Replace disjoint codewords, preserving all other syntax and the stop bit.

    Bit ranges use MSB-first offsets into ``rbsp`` and exclude
    ``rbsp_stop_one_bit``. Replacement bit lengths may differ from the
    originals; the output is padded with the minimum zero bits to a byte.
    Malformed RBSP and ambiguous/overlapping ranges fail closed.
    """
    if not isinstance(rbsp, bytes) or not rbsp or rbsp[-1] == 0:
        raise ValueError("RBSP must end with a stop bit and at most seven pad zeros")
    if not isinstance(replacements, Sequence):
        raise TypeError("replacements must be a sequence")

    last_byte = rbsp[-1]
    pad_zeros = (last_byte & -last_byte).bit_length() - 1
    stop_bit_index = len(rbsp) * 8 - pad_zeros - 1
    checked: list[tuple[int, int, tuple[int, ...]]] = []
    for item in replacements:
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            raise TypeError("each replacement must be (start, end, bits)")
        start, end, bits = item
        if type(start) is not int or type(end) is not int:
            raise TypeError("codeword bit offsets must be integers")
        if not 0 <= start < end <= stop_bit_index:
            raise ValueError("codeword range is outside the syntax before the stop bit")
        if not isinstance(bits, Sequence) or not bits or any(
            type(bit) is not int or bit not in (0, 1) for bit in bits
        ):
            raise ValueError("replacement codeword must contain only 0/1 integer bits")
        checked.append((start, end, tuple(bits)))

    checked.sort(key=lambda item: item[0])
    if any(previous[1] > following[0] for previous, following in zip(checked, checked[1:])):
        raise ValueError("replacement codeword ranges overlap")
    if not checked:
        return rbsp

    source_bits = np.unpackbits(np.frombuffer(rbsp, dtype=np.uint8))
    parts: list[np.ndarray] = []
    cursor = 0
    for start, end, bits in checked:
        parts.append(source_bits[cursor:start])
        parts.append(np.asarray(bits, dtype=np.uint8))
        cursor = end
    parts.append(source_bits[cursor:stop_bit_index])
    parts.append(np.asarray([1], dtype=np.uint8))
    return np.packbits(np.concatenate(parts)).tobytes()
