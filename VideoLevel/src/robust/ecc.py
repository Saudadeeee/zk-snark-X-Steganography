"""Error correction for the robust carrier channel.

Constraint-length-7 convolutional codes with six zero tail bits and a
soft-decision Viterbi decoder: rate 1/2 (generators 171/133 octal, the
NASA/CCSDS code) and rate 1/3 (133/171/165 octal, the LTE generators).  Soft values follow one convention throughout the package: ``+1``
means a confident 1, ``-1`` a confident 0, ``0`` an erasure.  Integrity of the
decoded message is checked with CRC-32 by the caller (``message``).
"""

from __future__ import annotations

import struct
import zlib
from functools import cache

import numpy as np

CONSTRAINT_LENGTH = 7
RATE_HALF = (0o171, 0o133)
RATE_THIRD = (0o133, 0o171, 0o165)
CODES = {2: RATE_HALF, 3: RATE_THIRD}
TAIL_BITS = CONSTRAINT_LENGTH - 1
_STATES = 1 << TAIL_BITS
_REGISTER_MASK = (1 << CONSTRAINT_LENGTH) - 1


def _parity(value: int) -> int:
    return value.bit_count() & 1


def _require_rate(rate: int) -> tuple[int, ...]:
    if rate not in CODES:
        raise ValueError(f"unsupported code rate 1/{rate}")
    return CODES[rate]


@cache
def _tables(rate: int) -> tuple[np.ndarray, np.ndarray]:
    """For each next state: its two predecessors and their +-1 output tuples."""
    generators = _require_rate(rate)
    previous = np.zeros((_STATES, 2), dtype=np.int64)
    outputs = np.zeros((rate, _STATES, 2), dtype=np.float64)
    for state in range(_STATES):
        bit = state & 1
        for choice, high in enumerate((0, 1 << (TAIL_BITS - 1))):
            prior = (state >> 1) | high
            register = ((prior << 1) | bit) & _REGISTER_MASK
            previous[state, choice] = prior
            for branch, generator in enumerate(generators):
                outputs[branch, state, choice] = 2 * _parity(register & generator) - 1
    return previous, outputs


def coded_length(message_bits: int, rate: int = 2) -> int:
    _require_rate(rate)
    return rate * (message_bits + TAIL_BITS)


def conv_encode(bits: np.ndarray, rate: int = 2) -> np.ndarray:
    """Encode 0/1 bits; returns ``coded_length(len(bits), rate)`` 0/1 bits."""
    generators = _require_rate(rate)
    bits = np.asarray(bits, dtype=np.uint8)
    if bits.ndim != 1 or (bits > 1).any():
        raise ValueError("bits must be a 1-D array of 0/1 values")
    padded = np.concatenate([bits, np.zeros(TAIL_BITS, dtype=np.uint8)])
    out = np.empty(rate * len(padded), dtype=np.uint8)
    register = 0
    for index, bit in enumerate(padded.tolist()):
        register = ((register << 1) | bit) & _REGISTER_MASK
        for branch, generator in enumerate(generators):
            out[rate * index + branch] = _parity(register & generator)
    return out


def viterbi_decode(soft: np.ndarray, rate: int = 2) -> np.ndarray:
    """Maximum-likelihood decode of terminated codewords from soft values."""
    previous, outputs = _tables(rate)
    soft = np.asarray(soft, dtype=np.float64)
    if soft.ndim != 1 or len(soft) % rate or len(soft) < rate * (TAIL_BITS + 1):
        raise ValueError("soft input has an impossible length")
    steps = len(soft) // rate
    branches = soft.reshape(steps, rate)
    metric = np.full(_STATES, -np.inf)
    metric[0] = 0.0
    decisions = np.empty((steps, _STATES), dtype=np.uint8)
    for step in range(steps):
        gains = np.tensordot(branches[step], outputs, axes=1)
        candidates = metric[previous] + gains
        choice = (candidates[:, 1] > candidates[:, 0]).astype(np.uint8)
        decisions[step] = choice
        metric = np.where(choice, candidates[:, 1], candidates[:, 0])
        if step % 1024 == 1023:
            metric = metric - metric.max()
    bits = np.empty(steps, dtype=np.uint8)
    state = 0  # the tail drives the encoder back to state 0
    for step in range(steps - 1, -1, -1):
        bits[step] = state & 1
        state = int(previous[state, decisions[step, state]])
    return bits[:steps - TAIL_BITS]


def bytes_to_bits(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def bits_to_bytes(bits: np.ndarray) -> bytes:
    bits = np.asarray(bits, dtype=np.uint8)
    if len(bits) % 8:
        raise ValueError("bit count must be a multiple of 8")
    return np.packbits(bits).tobytes()


def with_crc(data: bytes) -> bytes:
    return data + struct.pack(">I", zlib.crc32(data) & 0xFFFFFFFF)


def strip_crc(data: bytes) -> bytes:
    """Return the body of ``with_crc`` output; raise ``ValueError`` on mismatch."""
    if len(data) < 4:
        raise ValueError("message is shorter than its CRC")
    body, (expected,) = data[:-4], struct.unpack(">I", data[-4:])
    if zlib.crc32(body) & 0xFFFFFFFF != expected:
        raise ValueError("message CRC-32 mismatch")
    return body
