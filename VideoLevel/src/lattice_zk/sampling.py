"""Deterministic SHAKE-256 samplers; every draw uses rejection, never ``%``."""

from __future__ import annotations

import hashlib

import numpy as np

_INITIAL_BUFFER = 4096


class XofStream:
    """Sequential reader over a SHAKE-256 output stream."""

    def __init__(self, seed: bytes) -> None:
        if not isinstance(seed, bytes) or not seed:
            raise ValueError("XOF seed must be non-empty bytes")
        self._seed = seed
        self._buffer = b""
        self._offset = 0

    def read(self, count: int) -> bytes:
        end = self._offset + count
        if end > len(self._buffer):
            size = max(_INITIAL_BUFFER, 2 * end)
            self._buffer = hashlib.shake_256(self._seed).digest(size)
        chunk = self._buffer[self._offset:end]
        self._offset = end
        return chunk

    def read_uints(self, count: int, byte_width: int) -> np.ndarray:
        """Read ``count`` little-endian unsigned integers of ``byte_width`` bytes."""
        raw = np.frombuffer(self.read(count * byte_width), dtype=np.uint8)
        padded = np.zeros((count, 8), dtype=np.uint8)
        padded[:, :byte_width] = raw.reshape(count, byte_width)
        return padded.view("<u8").reshape(count).astype(np.int64)


def _rejection_sample(stream: XofStream, count: int, bits: int, bound: int) -> np.ndarray:
    """Return ``count`` uniform integers in [0, bound) from ``bits``-bit draws."""
    byte_width = (bits + 7) // 8
    mask = (1 << bits) - 1
    accepted = np.empty(0, dtype=np.int64)
    while len(accepted) < count:
        draws = stream.read_uints(count - len(accepted) + 16, byte_width) & mask
        accepted = np.concatenate([accepted, draws[draws < bound]])
    return accepted[:count]


def uniform_poly(stream: XofStream, q: int, degree: int) -> np.ndarray:
    return _rejection_sample(stream, degree, (q - 1).bit_length(), q)


def ternary_vector(stream: XofStream, shape: tuple[int, int]) -> np.ndarray:
    """Uniform coefficients in {-1, 0, 1}."""
    count = shape[0] * shape[1]
    return (_rejection_sample(stream, count, 2, 3) - 1).reshape(shape)


def mask_vector(stream: XofStream, gamma: int, shape: tuple[int, int]) -> np.ndarray:
    """Uniform coefficients in [-gamma + 1, gamma] for a power-of-two gamma."""
    if gamma < 2 or gamma & (gamma - 1):
        raise ValueError("mask bound must be a power of two")
    count = shape[0] * shape[1]
    draws = _rejection_sample(stream, count, gamma.bit_length(), 2 * gamma)
    return (gamma - draws).reshape(shape)


def challenge_poly(seed: bytes, degree: int, weight: int) -> np.ndarray:
    """Expand a seed to a polynomial with exactly ``weight`` coefficients +-1."""
    if not 0 < weight <= degree:
        raise ValueError("challenge weight is out of range")
    stream = XofStream(b"zkstego/lattice-zk/challenge-poly/v1\0" + seed)
    signs = _rejection_sample(stream, weight, 1, 2)
    poly = np.zeros(degree, dtype=np.int64)
    # Fisher-Yates over the last ``weight`` positions, as in ML-DSA SampleInBall.
    for step, index in enumerate(range(degree - weight, degree)):
        swap = int(_rejection_sample(stream, 1, index.bit_length(), index + 1)[0])
        poly[index] = poly[swap]
        poly[swap] = 1 - 2 * int(signs[step])
    return poly
