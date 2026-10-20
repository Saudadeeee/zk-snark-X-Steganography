"""BDLOP commitment to one message polynomial (Baum et al., SCN 2018).

Public key, with k = n + lam + 1 and all blocks derived from the setup seed:

    B1 = [ I_n | B1' ]        B1' in R_q^(n x (lam + 1))
    b2 = [ 0^n | 1 | b2' ]    b2' in R_q^(1 x lam)

    Commit(m; r):  t1 = B1 r,  t2 = <b2, r> + m,   r ternary in R^k

Hiding reduces to M-LWE and binding to M-SIS for the pinned parameters.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from . import codec, ring, sampling
from .params import BdlopParams

_KEY_DOMAIN = b"zkstego/lattice-zk/bdlop-open/v1/key\0"
_RANDOMNESS_DOMAIN = b"zkstego/lattice-zk/bdlop-open/v1/randomness\0"


@dataclass(frozen=True)
class CommitmentKey:
    params: BdlopParams
    b1_tail: np.ndarray
    b2_tail: np.ndarray

    def apply_b1(self, vector: np.ndarray) -> np.ndarray:
        """Return B1 * vector for a (k, N) vector reduced modulo q."""
        q, n = self.params.modulus, self.params.msis_rank
        return (vector[:n] + ring.mat_vec(self.b1_tail, vector[n:], q)) % q

    def apply_b2(self, vector: np.ndarray) -> np.ndarray:
        """Return <b2, vector>."""
        q, n = self.params.modulus, self.params.msis_rank
        return (vector[n] + ring.mat_vec(self.b2_tail, vector[n + 1:], q)[0]) % q


@dataclass(frozen=True)
class Commitment:
    t1: np.ndarray
    t2: np.ndarray

    def to_bytes(self, params: BdlopParams) -> bytes:
        coefficients = np.concatenate([self.t1.reshape(-1), self.t2])
        return codec.pack_uints(coefficients, params.modulus_bits)

    @classmethod
    def from_bytes(cls, params: BdlopParams, data: bytes) -> "Commitment":
        count = (params.msis_rank + 1) * params.degree
        values = codec.unpack_uints(data, count, params.modulus_bits, params.modulus)
        split = params.msis_rank * params.degree
        return cls(values[:split].reshape(params.msis_rank, params.degree), values[split:])


@lru_cache(maxsize=8)
def derive_key(params: BdlopParams) -> CommitmentKey:
    stream = sampling.XofStream(_KEY_DOMAIN + params.parameter_id)

    def block(rows: int, cols: int) -> np.ndarray:
        polys = [sampling.uniform_poly(stream, params.modulus, params.degree) for _ in range(rows * cols)]
        return np.stack(polys).reshape(rows, cols, params.degree)

    b1_tail = block(params.msis_rank, params.mlwe_rank + 1)
    b2_tail = block(1, params.mlwe_rank)
    for shared in (b1_tail, b2_tail):
        shared.flags.writeable = False  # the cached key is shared by all callers
    return CommitmentKey(params, b1_tail, b2_tail)


def sample_randomness(params: BdlopParams, seed: bytes | None = None) -> np.ndarray:
    """Sample the ternary commitment randomness r; fresh entropy by default."""
    entropy = os.urandom(32) if seed is None else seed
    stream = sampling.XofStream(_RANDOMNESS_DOMAIN + entropy)
    return sampling.ternary_vector(stream, (params.width, params.degree))


def commit(params: BdlopParams, message: np.ndarray, randomness: np.ndarray) -> Commitment:
    if randomness.shape != (params.width, params.degree):
        raise ValueError("commitment randomness must be a (k, N) vector")
    if message.shape != (params.degree,) or int(message.min()) < 0 or int(message.max()) >= params.modulus:
        raise ValueError("message must be a reduced polynomial")
    key = derive_key(params)
    reduced = randomness % params.modulus
    t2 = (key.apply_b2(reduced) + message) % params.modulus
    return Commitment(key.apply_b1(reduced), t2)


def verify_opening(
    params: BdlopParams, commitment: Commitment, message: np.ndarray, randomness: np.ndarray
) -> bool:
    """Check an honest (non-relaxed) opening, as used for later disclosure."""
    if randomness.shape != (params.width, params.degree) or int(np.abs(randomness).max()) > 1:
        return False
    try:
        expected = commit(params, message, randomness)
    except ValueError:
        return False
    return np.array_equal(expected.t1, commitment.t1) and np.array_equal(expected.t2, commitment.t2)
