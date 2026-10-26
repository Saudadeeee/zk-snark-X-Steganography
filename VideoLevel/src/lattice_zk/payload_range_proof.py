"""Proof that a payload commitment hides ``codec.encode_payload(p)`` for an L-byte ``p``.

Design, cost comparison and soundness: ``docs/PROOF_NHI_PHAN_VA_KHOANG.md``;
theorem statements: ``docs/paper/sections/binary_proof.tex``.

The statement is ``(x, L, C)`` with ``C = (t1, t2)`` an unchanged base
commitment (the commitment of an in-band envelope or of a credential) and a
*public* payload length ``L``.  The proof shows knowledge of a relaxed opening
of ``C`` whose message is exactly ``encode_payload(p)`` for some ``p`` of
``L`` bytes: every 24-bit coefficient (16-bit for the toy set) is the packing
of payload bits, coefficient 0 carries the length ``L``, and every other
coefficient is zero.  This is an exact range proof on the payload
coefficients, tied to the payload encoding by a bit decomposition.

``encode_payload(p) = e_L + A beta`` for the bits ``beta`` of ``p`` (most
significant bit first), a public offset ``e_L = encode_payload(0^L)`` and a
public Z_q-linear map ``A`` that sends payload bit ``s`` to one coefficient
with a power-of-two weight.  The bits fill ``l = ceil(8 L / N)`` binary
polynomials ``beta_j``.

Protocol (notation of ``binary_proof``; ``J`` all-ones, ``sigma(X) = X^-1``):

1. The prover commits ``beta_j`` in the first slots of a fresh auxiliary
   commitment ``D`` (``D_0 = (t1', t_beta)``).
2. ``gamma_a <- H(pid, x, L, C, D_0)`` for every lift ``a = (j, i)``, ``i < k``.
3. The prover adds rows to ``D`` (same randomness ``r'``) for the lifts
   ``u_a = sigma(gamma_a o beta_j)`` and masks ``g_t`` with ``ct(g_t) = 0``.
4. ``rho_{t,a}, mu_{t,a}, rho^L_t <- H(..., D_1)``.  The prover sends
   ``h_t = g_t + E_t`` without its constant coefficient, where
   ``E_t = sum_a [sigma(rho_{t,a}) u_a - R_{t,a} beta_j + mu_{t,a} u_a (beta_j - J)]
   + sigma(rho^L_t) m - sum_j sigma(A_j^T rho^L_t) beta_j - <rho^L_t, e_L>``, so that
   ``ct(E_t) = sum_a <rho_{t,a}, u_a - sigma(gamma_a o beta_j)> + mu_{t,a} <gamma_a,
   beta_j o (beta_j - J)> + <rho^L_t, m - A beta - e_L>``.
5. ``alpha_t <- H(..., h)`` combine the relations into one quadratic relation,
   proved with a garbage term exactly as in ``binary_proof``.

Proof bytes: ``Pack(D_0) || Pack(D_1) || Pack(h without ct) || Pack(t_G) || seed || Pack(z, z')``.
Self-implemented and unaudited; not constant time.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import numbers
import struct
from dataclasses import dataclass
from functools import cached_property, lru_cache
from typing import Callable

import numpy as np

from . import bdlop, codec, fast_ring, ring, sampling
from .bdlop import Commitment, ternary_randomness
from .binary_proof import _base_key, _identity_block, _ones, _scalar_combination, sigma
from .opening_proof import (
    HEDGE_PAYLOAD_RANGE, ProofResult, hedged_mask_key, prover_entropy, require_commitment,
)
from .params import (
    BDLOP_OPEN_128_V2, BDLOP_OPEN_128_V3, CHALLENGE_SEED_BYTES, MAX_NAME_BYTES, PAYLOAD_LENGTH_BYTES, TOY, BdlopParams,
)

_DOMAIN = b"zkstego/lattice-zk/bdlop-payload-range/v1/"
_PARAMETER_DOMAIN = _DOMAIN + b"parameters\0"
_KEY_DOMAIN = _DOMAIN + b"key\0"
_LIFT_DOMAIN = _DOMAIN + b"lift-challenge\0"
_CHECK_DOMAIN = _DOMAIN + b"check-challenge\0"
_COMBINE_DOMAIN = _DOMAIN + b"combine-challenge\0"
_CHALLENGE_DOMAIN = _DOMAIN + b"fiat-shamir\0"
_EXPAND_DOMAIN = _DOMAIN + b"expand\0"
_AUX_DOMAIN = _DOMAIN + b"aux-witness\0"
_MASK_DOMAIN = _DOMAIN + b"mask\0"
MAX_REPETITIONS = 64
MAX_BINARY_POLYS = 16
MIN_SOUNDNESS_BITS = 128
# Acceptance per attempt of the production set (bdlop-payload-range-128-v2) is
# about 0.0079 for l = 1 and 0.00094 for l = 4 (the production maximum); 2^17
# attempts all abort with probability below 2^-177.  The cap leaks nothing:
# acceptance does not depend on the witness.
MAX_ATTEMPTS = 1 << 17

LiftOverride = Callable[[np.ndarray, np.ndarray], np.ndarray]


def _packed_bytes(count: int, bits: int) -> int:
    return (count * bits + 7) // 8


@dataclass(frozen=True)
class Layout:
    """Shape of one proof for a payload of ``length`` bytes."""

    length: int
    binary_polys: int      # l
    lifts: int             # k l
    checks: int            # k'
    msis_rank: int
    mlwe_rank: int

    @property
    def slots(self) -> int:
        """Message slots of D: l bit polynomials, k l lifts, k' masks, one garbage polynomial."""
        return self.binary_polys + self.lifts + self.checks + 1

    @property
    def aux_width(self) -> int:
        return self.msis_rank + self.slots + self.mlwe_rank

    @property
    def first_rows(self) -> int:
        """Rows of ``D_0``: ``t1'`` and the bit rows."""
        return self.msis_rank + self.binary_polys

    @property
    def second_rows(self) -> int:
        """Rows of ``D_1``: lift and mask rows."""
        return self.lifts + self.checks

    @property
    def garbage_slot(self) -> int:
        return self.slots - 1


@dataclass(frozen=True)
class PayloadRangeParams:
    """Payload-range-proof parameters on top of a base BDLOP set.

    ``lift_repetitions`` (k) lifts per bit polynomial and ``check_repetitions``
    (k') random functionals give round errors ``q^-k`` and ``q^-k'``; payloads
    of up to ``max_binary_polys * N / 8`` bytes are supported.
    """

    name: str
    base: BdlopParams
    lift_repetitions: int
    check_repetitions: int
    max_binary_polys: int
    setup_seed: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or not self.name.isascii():
            raise ValueError("parameter set name must be a non-empty ASCII string")
        if len(self.name) > MAX_NAME_BYTES:
            raise ValueError("parameter set name is too long")
        if not isinstance(self.base, BdlopParams):
            raise TypeError("base must be a BdlopParams set")
        limits = {"lift_repetitions": MAX_REPETITIONS, "check_repetitions": MAX_REPETITIONS,
                  "max_binary_polys": MAX_BINARY_POLYS}
        for field, limit in limits.items():
            value = getattr(self, field)
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= limit:
                raise ValueError(f"{field} must be an integer in [1, {limit}]")
        if not isinstance(self.setup_seed, bytes) or len(self.setup_seed) != 32:
            raise ValueError("setup seed must be exactly 32 bytes")
        if self.base.modulus > fast_ring.MAX_MODULUS:
            raise ValueError("payload proof arithmetic needs a modulus of at most 2^30")
        if self.degree % 8:
            raise ValueError("ring degree must be a multiple of 8")
        if self.base.payload_bytes_per_coefficient < 1:
            raise ValueError("base set has no room for payload bytes")

    @property
    def degree(self) -> int:
        return self.base.degree

    @property
    def modulus(self) -> int:
        return self.base.modulus

    @property
    def max_payload_bytes(self) -> int:
        return min(self.max_binary_polys * self.degree // 8, self.base.max_payload_bytes)

    def layout(self, length: int) -> Layout:
        # Any integral type (e.g. a numpy integer) names a length; bools do not.
        if isinstance(length, bool) or not isinstance(length, numbers.Integral):
            raise ValueError("payload length must be an integer")
        length = int(length)
        if not 0 <= length <= self.max_payload_bytes:
            raise ValueError(f"payload length must be an integer in [0, {self.max_payload_bytes}]")
        polys = max(1, -(-8 * length // self.degree))
        return Layout(length, polys, self.lift_repetitions * polys, self.check_repetitions,
                      self.base.msis_rank, self.base.mlwe_rank)

    def proof_parts(self, length: int) -> dict[str, int]:
        layout, bits = self.layout(length), self.base.modulus_bits
        return {
            "aux_commitment_d0": _packed_bytes(layout.first_rows * self.degree, bits),
            "aux_commitment_d1": _packed_bytes(layout.second_rows * self.degree, bits),
            "masks_h": _packed_bytes(layout.checks * (self.degree - 1), bits),
            "garbage_t_G": _packed_bytes(self.degree, bits),
            "challenge_seed": CHALLENGE_SEED_BYTES,
            "responses_z_z_aux": _packed_bytes(
                (self.base.width + layout.aux_width) * self.degree, self.base.response_bits),
        }

    def proof_bytes(self, length: int) -> int:
        return sum(self.proof_parts(length).values())

    def acceptance_probability(self, length: int) -> float:
        base, layout = self.base, self.layout(length)
        kept = (2 * base.response_bound + 1) / (2 * base.mask_bound)
        return kept ** ((base.width + layout.aux_width) * self.degree)

    def mlwe_samples(self, length: int) -> int:
        """Ring samples of the auxiliary M-LWE instance (t1' and every slot row)."""
        return self.base.msis_rank + self.layout(length).slots

    @property
    def round_soundness_log2(self) -> dict[str, float]:
        """log2 of the per-round soundness errors (independent of the payload length)."""
        log_q = math.log2(self.modulus)
        return {
            "lift": -self.lift_repetitions * log_q,
            "check": -self.check_repetitions * log_q,
            "combine": -(self.degree // 2) * log_q,
            "challenge": 1.0 - self.base.challenge_space_bits,
        }

    @property
    def soundness_bits(self) -> float:
        """-log2 of the per-round soundness error, summed over the four rounds."""
        return -math.log2(sum(2.0 ** value for value in self.round_soundness_log2.values()))

    @cached_property
    def parameter_id(self) -> bytes:
        name = self.name.encode("ascii")
        encoded = (
            struct.pack(">H", len(name)) + name + self.base.parameter_id
            + struct.pack(">III", self.lift_repetitions, self.check_repetitions, self.max_binary_polys)
            + self.setup_seed
        )
        return hashlib.sha3_256(_PARAMETER_DOMAIN + encoded).digest()

    def require_production_strength(self) -> None:
        self.base.require_production_strength()
        if self.soundness_bits < MIN_SOUNDNESS_BITS:
            raise ValueError("round soundness error is above 2^-128")


def _setup_seed(label: str) -> bytes:
    return hashlib.sha3_256(_PARAMETER_DOMAIN + b"setup-seed\0" + label.encode("ascii")).digest()


# Over bdlop-open-128-v2; kept so earlier proofs and estimates stay reproducible.
PAYLOAD_RANGE_128_V1 = PayloadRangeParams(
    name="bdlop-payload-range-128-v1",
    base=BDLOP_OPEN_128_V2,
    lift_repetitions=5,
    check_repetitions=5,
    max_binary_polys=4,
    setup_seed=_setup_seed("bdlop-payload-range-128-v1"),
)

# Current production set, over bdlop-open-128-v3.
PAYLOAD_RANGE_128_V2 = PayloadRangeParams(
    name="bdlop-payload-range-128-v2",
    base=BDLOP_OPEN_128_V3,
    lift_repetitions=5,
    check_repetitions=5,
    max_binary_polys=4,
    setup_seed=_setup_seed("bdlop-payload-range-128-v2"),
)

PAYLOAD_RANGE_128 = PAYLOAD_RANGE_128_V2

# Fast, insecure set for unit tests only.
PAYLOAD_RANGE_TOY = PayloadRangeParams(
    name="bdlop-payload-range-toy-v1",
    base=TOY,
    lift_repetitions=2,
    check_repetitions=2,
    max_binary_polys=4,
    setup_seed=_setup_seed("bdlop-payload-range-toy-v1"),
)


# ------------------------------------------------------------------ encoding


@dataclass(frozen=True)
class PayloadEncoding:
    """``encode_payload(p) = offset + sum_s weight[s] * bit_s * X^index[s]`` for |p| = L."""

    offset: np.ndarray  # (N,): encode_payload(0^L)
    index: np.ndarray   # (8L,): coefficient fed by payload bit s
    weight: np.ndarray  # (8L,): its power-of-two weight


@lru_cache(maxsize=64)
def payload_encoding(base: BdlopParams, length: int) -> PayloadEncoding:
    width = base.payload_bytes_per_coefficient
    bits = np.arange(8 * length, dtype=np.int64)
    byte = PAYLOAD_LENGTH_BYTES + bits // 8
    shift = 8 * (width - 1 - byte % width) + 7 - bits % 8
    offset = codec.encode_payload(base, bytes(length))
    arrays = (offset, byte // width, np.left_shift(np.int64(1), shift))
    for array in arrays:
        array.flags.writeable = False
    return PayloadEncoding(*arrays)


def decompose(params: PayloadRangeParams, payload: bytes) -> np.ndarray:
    """The bits of ``payload``, most significant bit first, as ``(l, N)`` binary polynomials."""
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    layout = params.layout(len(payload))
    padded = payload.ljust(layout.binary_polys * params.degree // 8, b"\x00")
    bits = np.unpackbits(np.frombuffer(padded, dtype=np.uint8)).astype(np.int64)
    return bits.reshape(layout.binary_polys, params.degree)


def recompose(params: PayloadRangeParams, length: int, bits: np.ndarray) -> np.ndarray:
    """``e_L + A bits`` modulo q: the payload polynomial the bit polynomials encode."""
    layout = params.layout(length)
    encoding = payload_encoding(params.base, length)
    flat = bdlop.integer_array(bits, (layout.binary_polys, params.degree), "bits").reshape(-1)
    q = params.modulus
    message = encoding.offset.copy()
    np.add.at(message, encoding.index, (encoding.weight * (flat[:8 * length] % q)) % q)
    return message % q


# --------------------------------------------------------------------- keys


@dataclass(frozen=True)
class AuxKey:
    """``B1' = [I | B1'_tail]`` and every slot row ``b_s = [0 | e_s | b_s']`` in one array."""

    binary_polys: int
    rows: np.ndarray  # (n + slots, aux_width, N)


def derive_aux_key(params: PayloadRangeParams, binary_polys: int) -> AuxKey:
    """Expand the auxiliary key for ``binary_polys`` bit polynomials from ``parameter_id``."""
    if (not isinstance(binary_polys, int) or isinstance(binary_polys, bool)
            or not 1 <= binary_polys <= params.max_binary_polys):
        raise ValueError(f"binary_polys must be an integer in [1, {params.max_binary_polys}]")
    return _derive_aux_key(params, binary_polys)


@lru_cache(maxsize=16)
def _derive_aux_key(params: PayloadRangeParams, binary_polys: int) -> AuxKey:
    base = params.base
    n, lam, degree = base.msis_rank, base.mlwe_rank, base.degree
    slots = binary_polys * (1 + params.lift_repetitions) + params.check_repetitions + 1
    width = n + slots + lam
    stream = sampling.XofStream(_KEY_DOMAIN + params.parameter_id + struct.pack(">I", binary_polys))
    b1_tail = sampling.uniform_poly(stream, base.modulus, n * (slots + lam) * degree)
    slot_tails = sampling.uniform_poly(stream, base.modulus, slots * lam * degree)
    rows = np.zeros((n + slots, width, degree), dtype=np.int64)
    rows[:n, :n] = _identity_block(n, degree)
    rows[:n, n:] = b1_tail.reshape(n, slots + lam, degree)
    rows[n:, n:n + slots] = _identity_block(slots, degree)
    rows[n:, n + slots:] = slot_tails.reshape(slots, lam, degree)
    rows.flags.writeable = False
    return AuxKey(binary_polys, rows)


def _aux_key(params: PayloadRangeParams, layout: Layout) -> AuxKey:
    return _derive_aux_key(params, layout.binary_polys)


# -------------------------------------------------------------- Fiat-Shamir


def _seed(domain: bytes, *parts: bytes) -> bytes:
    transcript = hashlib.shake_256(domain)
    for part in parts:
        transcript.update(part)
    return transcript.digest(CHALLENGE_SEED_BYTES)


def _expand(seed: bytes, q: int, count: int) -> np.ndarray:
    return sampling.uniform_poly(sampling.XofStream(_EXPAND_DOMAIN + seed), q, count)


def _lift_seed(
    params: PayloadRangeParams, statement: bytes, length: int, commitment_bytes: bytes, first_bytes: bytes
) -> bytes:
    return _seed(
        _LIFT_DOMAIN, params.parameter_id, struct.pack(">Q", len(statement)) + statement,
        struct.pack(">I", length), commitment_bytes, first_bytes,
    )


@dataclass(frozen=True)
class _Check:
    """Functionals of step 4 that do not depend on ``alpha``."""

    sigma_rho: np.ndarray   # (k', K, N): sigma(rho_{t,a})
    mu: np.ndarray          # (k', K)
    r_sum: np.ndarray       # (k', l, N): sum_i R_{t,(j,i)}
    link_m: np.ndarray      # (k', N): sigma(rho^L_t)
    link_bits: np.ndarray   # (k', l, N): sigma(A_j^T rho^L_t)
    link_const: np.ndarray  # (k',): <rho^L_t, e_L>


def _check_challenges(
    params: PayloadRangeParams, layout: Layout, seed: bytes, gammas: np.ndarray
) -> _Check:
    q, degree, k = params.modulus, params.degree, params.lift_repetitions
    checks, lifts, polys = layout.checks, layout.lifts, layout.binary_polys
    sizes = (checks * lifts * degree, checks * lifts, checks * degree)
    expanded = _expand(seed, q, sum(sizes))
    rho = expanded[:sizes[0]].reshape(checks, lifts, degree)
    mu = expanded[sizes[0]:sizes[0] + sizes[1]].reshape(checks, lifts)
    rho_link = expanded[sizes[0] + sizes[1]:].reshape(checks, degree)
    sigma_rho = sigma(rho, q)
    r_terms = sigma((gammas[np.newaxis] * sigma_rho) % q, q)
    r_sum = r_terms.reshape(checks, polys, k, degree).sum(axis=2) % q
    encoding = payload_encoding(params.base, layout.length)
    transposed = np.zeros((checks, polys * degree), dtype=np.int64)
    transposed[:, :encoding.index.size] = (rho_link[:, encoding.index] * encoding.weight) % q
    link_bits = sigma(transposed.reshape(checks, polys, degree), q)
    link_const = ((rho_link * encoding.offset) % q).sum(axis=1) % q
    return _Check(sigma_rho, mu, r_sum, sigma(rho_link, q), link_bits, link_const)


@dataclass(frozen=True)
class _Combination:
    """``P = sum_j psi_j beta_j + coef_m m + sum_s coef[s] s - rhs`` after ``alpha``.

    ``psi_j = sum_i lift_scalars[(j, i)] u_(j, i)``; ``coef`` covers the bit,
    lift and mask slots of D in slot order.
    """

    lift_scalars: np.ndarray  # (K, N)
    coef: np.ndarray          # (slots - 1, N)
    coef_m: np.ndarray        # (N,)
    rhs: np.ndarray           # (N,): sum_t alpha_t (h_t + <rho^L_t, e_L>)
    opening_rows: np.ndarray  # (n + slots + l + 1, aux_width, N): key rows, psi_j rows, L row


def _combination(
    params: PayloadRangeParams, layout: Layout, check: _Check, alphas: np.ndarray, masks: np.ndarray
) -> _Combination:
    q, degree, k, n = params.modulus, params.degree, params.lift_repetitions, params.base.msis_rank
    lift_scalars = _scalar_combination(check.mu.T, alphas, q)
    pi = fast_ring.matvec(check.sigma_rho.transpose(1, 0, 2), alphas, q)
    coef_lift = (pi - fast_ring.scale(_ones(degree), lift_scalars, q)) % q
    coef_bits = (-(fast_ring.matvec(check.r_sum.transpose(1, 0, 2), alphas, q)
                   + fast_ring.matvec(check.link_bits.transpose(1, 0, 2), alphas, q))) % q
    coef = np.concatenate([coef_bits, coef_lift, alphas])
    coef_m = fast_ring.dot(check.link_m, alphas, q)
    rhs = (fast_ring.dot(masks, alphas, q) + _scalar_combination(check.link_const[np.newaxis], alphas, q)[0]) % q
    # <sum_s coef_s b_s, y> = sum_s coef_s <b_s, y>: fold the combinations into key rows once.
    slot_rows = _aux_key(params, layout).rows[n:]
    first_lift = n + layout.binary_polys
    psi_rows = [
        fast_ring.matvec(slot_rows[first_lift - n + start:first_lift - n + start + k].transpose(1, 0, 2),
                         lift_scalars[start:start + k], q)
        for start in range(0, layout.lifts, k)
    ]
    linear_row = fast_ring.matvec(slot_rows[:-1].transpose(1, 0, 2), coef, q)
    opening_rows = np.concatenate([_aux_key(params, layout).rows, np.stack(psi_rows + [linear_row])])
    return _Combination(lift_scalars, coef, coef_m, rhs, opening_rows)


def _per_poly_dot(scalars: np.ndarray, polys: np.ndarray, k: int, q: int) -> np.ndarray:
    """``sum_i scalars[(j, i)] * polys[(j, i)]`` for every bit polynomial j."""
    return np.stack([
        fast_ring.dot(scalars[start:start + k], polys[start:start + k], q)
        for start in range(0, len(scalars), k)
    ])


def _challenge_seed(
    combine_seed: bytes, garbage_bytes: bytes, w: np.ndarray, w_aux: np.ndarray, v: np.ndarray
) -> bytes:
    return _seed(
        _CHALLENGE_DOMAIN, combine_seed, garbage_bytes,
        w.astype(">u8").tobytes(), w_aux.astype(">u8").tobytes(), v.astype(">u8").tobytes(),
    )


def abort_probability_log2(params: PayloadRangeParams, length: int, attempts: int | None = None) -> float:
    attempts = MAX_ATTEMPTS if attempts is None else attempts
    accepted = params.acceptance_probability(length)
    if accepted >= 1.0:
        return -math.inf
    return attempts * math.log2(1.0 - accepted)


# ----------------------------------------------------------- masked openings


@dataclass(frozen=True)
class _Openings:
    """Products of one masked vector: ``a_j = <b_j, y>`` (prover) or ``<b_j, z>`` (verifier)."""

    w: np.ndarray        # (n, N)
    a_m: np.ndarray      # (N,)
    w_aux: np.ndarray    # (n, N)
    a_bits: np.ndarray   # (l, N)
    a_garbage: np.ndarray  # (N,)
    a_psi: np.ndarray    # (l, N)
    a_linear: np.ndarray  # (N,): coef_m a_m + sum_s coef_s a_s


def _open(
    params: PayloadRangeParams, layout: Layout, combo: _Combination, vector: np.ndarray, aux_vector: np.ndarray
) -> _Openings:
    q, n, polys = params.modulus, params.base.msis_rank, layout.binary_polys
    base_rows = fast_ring.matvec(_base_key(params.base).rows, vector, q)
    aux = fast_ring.matvec(combo.opening_rows, aux_vector, q)
    a_m = base_rows[n]
    end = n + layout.slots
    a_linear = (aux[-1] + fast_ring.mul(combo.coef_m, a_m, q)) % q
    return _Openings(base_rows[:n], a_m, aux[:n], aux[n:n + polys], aux[end - 1],
                     aux[end:end + polys], a_linear)


def _pack_rows(rows: np.ndarray, bits: int) -> bytes:
    return codec.pack_uints(rows.reshape(-1), bits)


# --------------------------------------------------------------------- prover


def _prove(
    params: PayloadRangeParams, statement: bytes, commitment: Commitment, message: np.ndarray,
    randomness: np.ndarray, bits: np.ndarray, length: int, entropy: bytes,
    *, lift_override: LiftOverride | None = None,
) -> ProofResult:
    """Run the protocol; the caller has validated the witness (tests skip that)."""
    base, q, degree = params.base, params.modulus, params.degree
    layout, k, n = params.layout(length), params.lift_repetitions, base.msis_rank
    aux_key = _aux_key(params, layout)
    commitment_bytes = commitment.to_bytes(base)
    # parameter_id and L pin the auxiliary key, so r' is never reused under two keys.
    mask_key = hedged_mask_key(
        entropy, statement, struct.pack(">I", length), commitment_bytes, message, randomness, bits,
        protocol=HEDGE_PAYLOAD_RANGE, parameter_id=params.parameter_id,
    )
    witness_stream = sampling.XofStream(_AUX_DOMAIN + mask_key)
    aux_randomness = sampling.ternary_vector(witness_stream, (layout.aux_width, degree))
    garbage = sampling.uniform_poly(witness_stream, q, layout.checks * degree).reshape(layout.checks, degree)
    garbage[:, 0] = 0
    aux_rows = fast_ring.matvec(aux_key.rows, aux_randomness % q, q)
    polys = layout.binary_polys
    first = np.concatenate([aux_rows[:n], (aux_rows[n:n + polys] + bits) % q])
    first_bytes = _pack_rows(first, base.modulus_bits)

    lift_seed = _lift_seed(params, statement, length, commitment_bytes, first_bytes)
    gammas = _expand(lift_seed, q, layout.lifts * degree).reshape(layout.lifts, degree)
    lifts = sigma((gammas * np.repeat(bits, k, axis=0)) % q, q)
    if lift_override is not None:
        lifts = np.asarray(lift_override(lifts, gammas), dtype=np.int64) % q
    second_messages = np.concatenate([lifts, garbage])
    second = (aux_rows[n + polys:n + layout.slots - 1] + second_messages) % q
    second_bytes = _pack_rows(second, base.modulus_bits)

    check_seed = _seed(_CHECK_DOMAIN, lift_seed, second_bytes)
    check = _check_challenges(params, layout, check_seed, gammas)
    masks = _masks_from(params, layout, check, lifts, garbage, bits, message)
    mask_bytes = _pack_rows(masks[:, 1:], base.modulus_bits)

    combine_seed = _seed(_COMBINE_DOMAIN, check_seed, mask_bytes)
    alphas = _expand(combine_seed, q, layout.checks * degree).reshape(layout.checks, degree)
    combo = _combination(params, layout, check, alphas, masks)
    psi = _per_poly_dot(combo.lift_scalars, lifts, k, q)
    garbage_randomness = aux_rows[n + layout.garbage_slot]
    secrets = np.concatenate([randomness, aux_randomness]) % q
    header = first_bytes + second_bytes + mask_bytes
    reduced_bits = bits % q

    for attempt in range(1, MAX_ATTEMPTS + 1):
        stream = sampling.XofStream(_MASK_DOMAIN + mask_key + struct.pack(">I", attempt))
        mask = sampling.mask_vector(stream, base.mask_bound, (base.width, degree))
        aux_mask = sampling.mask_vector(stream, base.mask_bound, (layout.aux_width, degree))
        opened = _open(params, layout, combo, mask % q, aux_mask % q)
        # Gamma_1 = -(sum_j psi_j a_beta_j + a_psi_j beta_j + L(a)), committed in slot G.
        cross = fast_ring.dot(np.concatenate([psi, opened.a_psi]),
                              np.concatenate([opened.a_bits, reduced_bits]), q)
        garbage_term = (-(cross + opened.a_linear)) % q
        garbage_bytes = codec.pack_uints((garbage_randomness + garbage_term) % q, base.modulus_bits)
        v = (fast_ring.dot(opened.a_psi, opened.a_bits, q) + opened.a_garbage) % q
        seed = _challenge_seed(combine_seed, garbage_bytes, opened.w, opened.w_aux, v)
        challenge = sampling.challenge_poly(seed, degree, base.challenge_weight)
        shifts = ring.center(fast_ring.scale(challenge % q, secrets, q), q)
        responses = np.concatenate([mask, aux_mask]) + shifts
        if int(np.abs(responses).max()) > base.response_bound:
            continue
        packed = codec.pack_uints(responses + base.response_bound, base.response_bits)
        return ProofResult(header + garbage_bytes + seed + packed, attempt)
    raise RuntimeError("rejection sampling did not terminate")


def _masks_from(
    params: PayloadRangeParams, layout: Layout, check: _Check, lifts: np.ndarray,
    garbage: np.ndarray, bits: np.ndarray, message: np.ndarray,
) -> np.ndarray:
    """``h_t = g_t + E_t`` of step 4 (``ct(h_t) = 0`` for an honest witness)."""
    q, degree, k = params.modulus, params.degree, params.lift_repetitions
    bits = bits % q
    shifted = (bits - _ones(degree)) % q
    quadratic = np.concatenate([
        fast_ring.scale(shifted[j], lifts[j * k:(j + 1) * k], q) for j in range(layout.binary_polys)
    ])
    linear = fast_ring.matvec(check.sigma_rho, lifts, q)
    recentred = fast_ring.matvec(check.r_sum, bits, q)
    link = (fast_ring.scale(message % q, check.link_m, q) - fast_ring.matvec(check.link_bits, bits, q)) % q
    masks = (garbage + linear - recentred + _scalar_combination(check.mu, quadratic, q) + link) % q
    masks[:, 0] = (masks[:, 0] - check.link_const) % q
    return masks


def prove_with_stats(
    params: PayloadRangeParams, statement: bytes, commitment: Commitment, payload: bytes,
    randomness: np.ndarray, *, mask_seed: bytes | None = None,
) -> ProofResult:
    """Prove that ``commitment`` hides ``encode_payload(payload)``, bound to ``statement``.

    The length ``len(payload)`` is public; the payload bytes stay hidden.
    """
    if not isinstance(params, PayloadRangeParams):
        raise TypeError("params must be a PayloadRangeParams set")
    if not isinstance(statement, bytes):
        raise TypeError("statement must be bytes")
    bits = decompose(params, payload)
    message = codec.encode_payload(params.base, payload)
    randomness = ternary_randomness(params.base, randomness)
    commitment = require_commitment(params.base, commitment)
    if not bdlop.verify_opening(params.base, commitment, message, randomness):
        raise ValueError("payload and randomness do not open the commitment")
    if not np.array_equal(recompose(params, len(payload), bits), message):
        raise RuntimeError("bit decomposition does not reproduce the payload encoding")
    return _prove(params, statement, commitment, message, randomness, bits, len(payload),
                  prover_entropy(mask_seed))


def prove(
    params: PayloadRangeParams, statement: bytes, commitment: Commitment, payload: bytes,
    randomness: np.ndarray,
) -> bytes:
    return prove_with_stats(params, statement, commitment, payload, randomness).proof


# ------------------------------------------------------------------- verifier


@dataclass(frozen=True)
class _ParsedProof:
    first_bytes: bytes
    first: np.ndarray       # (n + l, N): t1' and the bit rows
    second_bytes: bytes
    second: np.ndarray      # (K + k', N): lift and mask rows
    mask_bytes: bytes
    masks: np.ndarray       # (k', N) with ct = 0
    garbage_bytes: bytes
    garbage: np.ndarray     # (N,)
    seed: bytes
    responses: np.ndarray   # (k_base + aux_width, N), centred


def _parse(params: PayloadRangeParams, layout: Layout, proof: bytes) -> _ParsedProof:
    """Split and canonically decode a proof of the exact length; raise ``ValueError``."""
    base, q, degree = params.base, params.modulus, params.degree
    sizes = list(params.proof_parts(layout.length).values())
    if len(proof) != sum(sizes):
        raise ValueError("payload range proof has the wrong length")
    fields, offset = [], 0
    for size in sizes:
        fields.append(proof[offset:offset + size])
        offset += size
    first_bytes, second_bytes, mask_bytes, garbage_bytes, seed, response_bytes = fields
    bits = base.modulus_bits
    first = codec.unpack_uints(first_bytes, layout.first_rows * degree, bits, q)
    second = codec.unpack_uints(second_bytes, layout.second_rows * degree, bits, q)
    tails = codec.unpack_uints(mask_bytes, layout.checks * (degree - 1), bits, q)
    masks = np.zeros((layout.checks, degree), dtype=np.int64)
    masks[:, 1:] = tails.reshape(layout.checks, degree - 1)
    garbage = codec.unpack_uints(garbage_bytes, degree, bits, q)
    count = (base.width + layout.aux_width) * degree
    shifted = codec.unpack_uints(response_bytes, count, base.response_bits, 2 * base.response_bound + 1)
    responses = (shifted - base.response_bound).reshape(base.width + layout.aux_width, degree)
    return _ParsedProof(
        first_bytes, first.reshape(layout.first_rows, degree), second_bytes,
        second.reshape(layout.second_rows, degree), mask_bytes, masks, garbage_bytes, garbage,
        seed, responses,
    )


def _recomputed_seed(
    params: PayloadRangeParams, layout: Layout, statement: bytes, commitment: Commitment, parsed: _ParsedProof
) -> bytes:
    base, q, degree = params.base, params.modulus, params.degree
    k, n, polys = params.lift_repetitions, base.msis_rank, layout.binary_polys
    commitment_bytes = commitment.to_bytes(base)
    lift_seed = _lift_seed(params, statement, layout.length, commitment_bytes, parsed.first_bytes)
    gammas = _expand(lift_seed, q, layout.lifts * degree).reshape(layout.lifts, degree)
    check_seed = _seed(_CHECK_DOMAIN, lift_seed, parsed.second_bytes)
    check = _check_challenges(params, layout, check_seed, gammas)
    combine_seed = _seed(_COMBINE_DOMAIN, check_seed, parsed.mask_bytes)
    alphas = _expand(combine_seed, q, layout.checks * degree).reshape(layout.checks, degree)
    combo = _combination(params, layout, check, alphas, parsed.masks)

    challenge = sampling.challenge_poly(parsed.seed, degree, base.challenge_weight) % q
    responses = parsed.responses % q
    opened = _open(params, layout, combo, responses[:base.width], responses[base.width:])
    bit_rows = parsed.first[n:]
    # The committed values whose masked openings the relation uses: psi_j, L, beta_j, G.
    psi_commitment = _per_poly_dot(combo.lift_scalars, parsed.second[:layout.lifts], k, q)
    slot_rows = np.concatenate([bit_rows, parsed.second])
    linear_commitment = (fast_ring.mul(combo.coef_m, commitment.t2, q)
                         + fast_ring.dot(combo.coef, slot_rows, q)) % q
    scaled = fast_ring.scale(challenge, np.concatenate([
        commitment.t1, parsed.first[:n], psi_commitment, bit_rows,
        np.stack([linear_commitment, parsed.garbage, combo.rhs]),
    ]), q)
    w = (opened.w - scaled[:n]) % q
    w_aux = (opened.w_aux - scaled[n:2 * n]) % q
    f_psi = (scaled[2 * n:2 * n + polys] - opened.a_psi) % q
    f_bits = (scaled[2 * n + polys:2 * n + 2 * polys] - opened.a_bits) % q
    c_linear, c_garbage, c_rhs = scaled[2 * n + 2 * polys:]
    f_linear = (c_linear - opened.a_linear) % q
    f_garbage = (c_garbage - opened.a_garbage) % q
    # V(c) = sum_j f_psi_j f_beta_j + c (L(f) - c rhs);  v = V(c) - f_G.
    inner = (f_linear - c_rhs) % q
    value = (fast_ring.dot(f_psi, f_bits, q) + fast_ring.mul(challenge, inner, q) - f_garbage) % q
    return _challenge_seed(combine_seed, parsed.garbage_bytes, w, w_aux, value)


def verify(
    params: PayloadRangeParams, statement: bytes, commitment: Commitment, length: int, proof: bytes
) -> bool:
    """Accept iff ``proof`` shows ``commitment`` hides the encoding of a ``length``-byte payload.

    Malformed or non-canonical input returns ``False``.
    """
    if not isinstance(params, PayloadRangeParams):
        return False
    if not isinstance(statement, bytes) or not isinstance(proof, bytes):
        return False
    try:
        layout = params.layout(length)
        commitment = require_commitment(params.base, commitment)
        parsed = _parse(params, layout, proof)
    except (TypeError, ValueError):
        return False
    expected = _recomputed_seed(params, layout, statement, commitment, parsed)
    return hmac.compare_digest(parsed.seed, expected)


__all__ = [
    "MAX_ATTEMPTS",
    "PAYLOAD_RANGE_128",
    "PAYLOAD_RANGE_128_V1",
    "PAYLOAD_RANGE_128_V2",
    "PAYLOAD_RANGE_TOY",
    "AuxKey",
    "Layout",
    "PayloadEncoding",
    "PayloadRangeParams",
    "abort_probability_log2",
    "decompose",
    "derive_aux_key",
    "payload_encoding",
    "prove",
    "prove_with_stats",
    "recompose",
    "verify",
]
