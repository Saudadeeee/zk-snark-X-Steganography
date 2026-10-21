"""BDLOP commitment to one message polynomial (Baum et al., SCN 2018).

Public key, with k = n + lam + 1 and all blocks derived from the setup seed:

    B1 = [ I_n | B1' ]        B1' in R_q^(n x (lam + 1))
    b2 = [ 0^n | 1 | b2' ]    b2' in R_q^(1 x lam)

    Commit(m; r):  t1 = B1 r,  t2 = <b2, r> + m,   r ternary in R^k

Hiding reduces to M-LWE and binding to M-SIS for the pinned parameters.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from . import codec, ring, sampling
from .params import BdlopParams

_KEY_DOMAIN = b"zkstego/lattice-zk/bdlop-open/v1/key\0"
_RANDOMNESS_DOMAIN = b"zkstego/lattice-zk/bdlop-open/v1/randomness\0"
MIN_SEED_BYTES = 32


def integer_array(value: object, shape: tuple[int, ...], name: str) -> np.ndarray:
    """Return ``value`` as ``int64`` after checking its type and exact shape."""
    if not isinstance(value, np.ndarray) or not np.issubdtype(value.dtype, np.integer):
        raise TypeError(f"{name} must be an integer numpy array")
    if value.shape != shape:
        raise ValueError(f"{name} must have shape {shape}")
    if value.dtype == np.uint64 and value.size and int(value.max()) >= 1 << 63:
        raise ValueError(f"{name} has coefficients outside the int64 range")
    return value.astype(np.int64, copy=False)


def reduced_array(
    params: BdlopParams, value: object, shape: tuple[int, ...], name: str
) -> np.ndarray:
    """Require an integer array of ``shape`` with every coefficient in [0, q)."""
    values = integer_array(value, shape, name)
    if values.size and (int(values.min()) < 0 or int(values.max()) >= params.modulus):
        raise ValueError(f"{name} must be reduced modulo q")
    return values


def ternary_randomness(params: BdlopParams, randomness: object) -> np.ndarray:
    """Require commitment randomness in S_1^k: a (k, N) vector over {-1, 0, 1}."""
    values = integer_array(randomness, (params.width, params.degree), "commitment randomness")
    # Compare directly: np.abs(int64 min) overflows and stays negative.
    if int(values.min()) < -1 or int(values.max()) > 1:
        raise ValueError("commitment randomness must be ternary")
    return values


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


def _is_frozen(values: object) -> bool:
    return isinstance(values, np.ndarray) and values.dtype == np.int64 and not values.flags.writeable


@dataclass(frozen=True)
class Commitment:
    """A BDLOP commitment ``(t1, t2)`` that is canonical for ``params``.

    Construction rejects anything but integer arrays of the exact shapes with
    every coefficient in ``[0, q)`` and stores read-only ``int64`` copies, so
    an unreduced or later-mutated commitment cannot reach a verifier, an
    encoder or a pinned-credential comparison.
    """

    t1: np.ndarray
    t2: np.ndarray
    params: BdlopParams = field(kw_only=True, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.params, BdlopParams):
            raise TypeError("commitment params must be a BdlopParams set")
        shapes = (("t1", (self.params.msis_rank, self.params.degree)), ("t2", (self.params.degree,)))
        for name, shape in shapes:
            values = reduced_array(self.params, getattr(self, name), shape, f"commitment {name}")
            frozen = values.astype(np.int64, copy=True)
            frozen.flags.writeable = False
            object.__setattr__(self, name, frozen)

    def normalized(self, params: BdlopParams) -> "Commitment":
        """Return this commitment checked for ``params``; raise unless canonical there."""
        own = getattr(self, "params", None)
        if not isinstance(own, BdlopParams) or not isinstance(params, BdlopParams):
            raise TypeError("commitment params must be a BdlopParams set")
        t1, t2 = getattr(self, "t1", None), getattr(self, "t2", None)
        if own == params and _is_frozen(t1) and _is_frozen(t2):
            # Re-check: an object built around __init__ must not pass as canonical.
            reduced_array(params, t1, (params.msis_rank, params.degree), "commitment t1")
            reduced_array(params, t2, (params.degree,), "commitment t2")
            return self
        return Commitment(t1, t2, params=params)

    def validate(self, params: BdlopParams) -> None:
        self.normalized(params)

    def is_canonical(self, params: BdlopParams) -> bool:
        try:
            self.validate(params)
        except (TypeError, ValueError):
            return False
        return True

    def to_bytes(self, params: BdlopParams) -> bytes:
        checked = self.normalized(params)
        coefficients = np.concatenate([checked.t1.reshape(-1), checked.t2])
        return codec.pack_uints(coefficients, params.modulus_bits)

    @classmethod
    def from_bytes(cls, params: BdlopParams, data: bytes) -> "Commitment":
        count = (params.msis_rank + 1) * params.degree
        values = codec.unpack_uints(data, count, params.modulus_bits, params.modulus)
        split = params.msis_rank * params.degree
        return cls(values[:split].reshape(params.msis_rank, params.degree), values[split:], params=params)


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
    if seed is not None and (not isinstance(seed, bytes) or len(seed) < MIN_SEED_BYTES):
        raise ValueError(f"randomness seed must be at least {MIN_SEED_BYTES} bytes")
    entropy = os.urandom(32) if seed is None else seed
    stream = sampling.XofStream(_RANDOMNESS_DOMAIN + entropy)
    return sampling.ternary_vector(stream, (params.width, params.degree))


def commit(params: BdlopParams, message: np.ndarray, randomness: np.ndarray) -> Commitment:
    """Commit to a reduced message polynomial under ternary randomness."""
    reduced = ternary_randomness(params, randomness) % params.modulus
    message = reduced_array(params, message, (params.degree,), "message")
    key = derive_key(params)
    t2 = (key.apply_b2(reduced) + message) % params.modulus
    return Commitment(key.apply_b1(reduced), t2, params=params)


def verify_opening(
    params: BdlopParams, commitment: Commitment, message: np.ndarray, randomness: np.ndarray
) -> bool:
    """Check an honest (non-relaxed) opening; malformed input returns ``False``."""
    if not isinstance(commitment, Commitment) or not commitment.is_canonical(params):
        return False
    try:
        expected = commit(params, message, randomness)
    except (TypeError, ValueError):
        return False
    return np.array_equal(expected.t1, commitment.t1) and np.array_equal(expected.t2, commitment.t2)
