"""Proof that a BDLOP commitment hides a binary message (every coefficient in {0, 1}).

Design and soundness analysis: ``docs/BINARY_PROOF_DESIGN.md``; theorem
statements: ``docs/paper/sections/binary_proof.tex``.

The statement commitment ``C = (t1, t2)`` is an ordinary commitment of
``bdlop.commit`` under the base parameter set (``bdlop-open-128-v1`` in
production), so it also works with the opening, equality and disclosure
proofs.  Each proof creates a fresh auxiliary BDLOP commitment ``D`` under its
own key, with randomness ``r'`` that is never reused, and proves a quadratic
relation across ``C`` and ``D`` with one challenge ``c``.

Notation: ``<a, b>`` is the coefficient inner product, ``ct`` the constant
coefficient, ``sigma(X) = X^-1`` (so ``ct(sigma(a) b) = <a, b>``), ``J`` the
all-ones polynomial and ``o`` the coefficient-wise product.

1. ``gamma_1..gamma_k <- H(x, C)``.  ``m`` is binary iff
   ``v = m o (m - J) = 0``, and ``<gamma_i, v> = ct(sigma(gamma_i o m) (m - J))``.
2. The prover commits in ``D`` to the lifts ``u_i = sigma(gamma_i o m)`` and to
   masks ``g_t`` with ``ct(g_t) = 0``.
3. ``rho_{t,i} in Z_q^N, mu_{t,i} in Z_q <- H(..., D)``.  With
   ``R_{t,i} = sigma(gamma_i o sigma(rho_{t,i}))`` the polynomial
   ``E_t = sum_i sigma(rho_{t,i}) u_i - R_{t,i} m + mu_{t,i} u_i (m - J)`` has
   ``ct(E_t) = sum_i <rho_{t,i}, u_i - sigma(gamma_i o m)> + mu_{t,i} <gamma_i, v>``.
   The prover sends ``h_t = g_t + E_t``; ``ct(h_t) = 0`` is implicit in the
   encoding.
4. ``alpha_t in R_q <- H(..., h)``: the relations ``g_t + E_t - h_t = 0`` are
   combined into ``P = sum_t alpha_t (g_t + E_t - h_t) = 0``.
5. Masked openings ``f = c t - <b, z>`` turn ``P`` into a degree-two
   polynomial in ``c`` whose linear term is committed as garbage ``G`` in
   ``D`` (Attema-Lyubashevsky-Seiler 2020); ``z = y + c r``, ``z' = y' + c r'``
   with uniform masking and rejection as in ``opening_proof``.

Proof bytes: ``Pack(t1', t_u, t_g) || Pack(h without ct) || Pack(t_G) || seed || Pack(z, z')``.
Self-implemented and unaudited; not constant time.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import struct
from dataclasses import dataclass
from functools import cached_property, lru_cache
from typing import Callable

import numpy as np

from . import bdlop, codec, fast_ring, ring, sampling
from .bdlop import Commitment, ternary_randomness
from .opening_proof import ProofResult, hedged_mask_key, prover_entropy, require_commitment
from .params import BDLOP_OPEN_128, CHALLENGE_SEED_BYTES, MAX_NAME_BYTES, TOY, BdlopParams

_DOMAIN = b"zkstego/lattice-zk/bdlop-binary/v1/"
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
MIN_SOUNDNESS_BITS = 128
# The acceptance probability of the production set is about 0.0142 per
# attempt; 16384 attempts all abort with probability about 2^-338.  The cap
# leaks nothing: acceptance does not depend on the witness.
MAX_ATTEMPTS = 16384

LiftOverride = Callable[[np.ndarray, np.ndarray], np.ndarray]


def _packed_bytes(count: int, bits: int) -> int:
    return (count * bits + 7) // 8


@dataclass(frozen=True)
class BinaryParams:
    """Binary-proof parameters on top of a base BDLOP set.

    ``lift_repetitions`` (k) independent ``gamma_i`` and ``check_repetitions``
    (k') independent functionals each contribute a ``q^-k`` and ``q^-k'``
    round soundness error; see :attr:`round_soundness_log2`.
    """

    name: str
    base: BdlopParams
    lift_repetitions: int
    check_repetitions: int
    setup_seed: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or not self.name.isascii():
            raise ValueError("parameter set name must be a non-empty ASCII string")
        if len(self.name) > MAX_NAME_BYTES:
            raise ValueError("parameter set name is too long")
        if not isinstance(self.base, BdlopParams):
            raise TypeError("base must be a BdlopParams set")
        for field in ("lift_repetitions", "check_repetitions"):
            value = getattr(self, field)
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_REPETITIONS:
                raise ValueError(f"{field} must be an integer in [1, {MAX_REPETITIONS}]")
        if not isinstance(self.setup_seed, bytes) or len(self.setup_seed) != 32:
            raise ValueError("setup seed must be exactly 32 bytes")
        if self.base.modulus > fast_ring.MAX_MODULUS:
            raise ValueError("binary proof arithmetic needs a modulus below 2^30")
        if self.degree % 8:
            raise ValueError("ring degree must be a multiple of 8")

    @property
    def degree(self) -> int:
        return self.base.degree

    @property
    def modulus(self) -> int:
        return self.base.modulus

    @property
    def aux_slots(self) -> int:
        """Message slots of D: k lifts, k' masks, one garbage polynomial."""
        return self.lift_repetitions + self.check_repetitions + 1

    @property
    def aux_width(self) -> int:
        return self.base.msis_rank + self.aux_slots + self.base.mlwe_rank

    @property
    def response_polys(self) -> int:
        return self.base.width + self.aux_width

    @property
    def message_bytes(self) -> int:
        return self.degree // 8

    @property
    def aux_commitment_bytes(self) -> int:
        rows = self.base.msis_rank + self.lift_repetitions + self.check_repetitions
        return _packed_bytes(rows * self.degree, self.base.modulus_bits)

    @property
    def mask_bytes(self) -> int:
        return _packed_bytes(self.check_repetitions * (self.degree - 1), self.base.modulus_bits)

    @property
    def garbage_bytes(self) -> int:
        return _packed_bytes(self.degree, self.base.modulus_bits)

    @property
    def response_bytes(self) -> int:
        return _packed_bytes(self.response_polys * self.degree, self.base.response_bits)

    @property
    def proof_bytes(self) -> int:
        return (self.aux_commitment_bytes + self.mask_bytes + self.garbage_bytes
                + CHALLENGE_SEED_BYTES + self.response_bytes)

    @property
    def acceptance_probability(self) -> float:
        base = self.base
        kept = (2 * base.response_bound + 1) / (2 * base.mask_bound)
        return kept ** (self.response_polys * self.degree)

    @property
    def mlwe_samples(self) -> int:
        """Ring samples of the auxiliary M-LWE instance (t1' and the slot rows)."""
        return self.base.msis_rank + self.aux_slots

    @property
    def round_soundness_log2(self) -> dict[str, float]:
        """log2 of the per-round soundness errors (design doc, Section 3)."""
        log_q = math.log2(self.modulus)
        return {
            "lift": -self.lift_repetitions * log_q,
            "check": -self.check_repetitions * log_q,
            "combine": -(self.degree // 2) * log_q,
            "challenge": 1.0 - self.base.challenge_space_bits,
        }

    @property
    def soundness_bits(self) -> float:
        return -max(self.round_soundness_log2.values())

    @cached_property
    def parameter_id(self) -> bytes:
        name = self.name.encode("ascii")
        encoded = (
            struct.pack(">H", len(name)) + name + self.base.parameter_id
            + struct.pack(">II", self.lift_repetitions, self.check_repetitions) + self.setup_seed
        )
        return hashlib.sha3_256(_PARAMETER_DOMAIN + encoded).digest()

    def require_production_strength(self) -> None:
        self.base.require_production_strength()
        if self.soundness_bits < MIN_SOUNDNESS_BITS:
            raise ValueError("round soundness error is above 2^-128")


def _setup_seed(label: str) -> bytes:
    return hashlib.sha3_256(_PARAMETER_DOMAIN + b"setup-seed\0" + label.encode("ascii")).digest()


BINARY_128 = BinaryParams(
    name="bdlop-binary-128-v1",
    base=BDLOP_OPEN_128,
    lift_repetitions=5,
    check_repetitions=5,
    setup_seed=_setup_seed("bdlop-binary-128-v1"),
)

# Fast, insecure set for unit tests only.
BINARY_TOY = BinaryParams(
    name="bdlop-binary-toy-v1",
    base=TOY,
    lift_repetitions=2,
    check_repetitions=2,
    setup_seed=_setup_seed("bdlop-binary-toy-v1"),
)


# --------------------------------------------------------------------------- keys


def _identity_block(rows: int, degree: int) -> np.ndarray:
    block = np.zeros((rows, rows, degree), dtype=np.int64)
    block[np.arange(rows), np.arange(rows), 0] = 1
    return block


@dataclass(frozen=True)
class _BaseKey:
    """``[B1; b2]`` of the base key as one (n + 1, k, N) matrix."""

    rows: np.ndarray


@dataclass(frozen=True)
class AuxKey:
    """Key of the auxiliary commitment; ``rows`` stacks ``B1'`` and every ``b_j``."""

    params: BinaryParams
    rows: np.ndarray        # (n + slots, aux_width, N)
    slot_tails: np.ndarray  # (slots, lam, N): b_j restricted to the M-LWE secret


def _freeze(array: np.ndarray) -> np.ndarray:
    array.flags.writeable = False
    return array


@lru_cache(maxsize=8)
def _base_key(base: BdlopParams) -> _BaseKey:
    key = bdlop.derive_key(base)
    n, width, degree = base.msis_rank, base.width, base.degree
    rows = np.zeros((n + 1, width, degree), dtype=np.int64)
    rows[:n, :n] = _identity_block(n, degree)
    rows[:n, n:] = key.b1_tail
    rows[n, n, 0] = 1
    rows[n, n + 1:] = key.b2_tail[0]
    return _BaseKey(_freeze(rows))


@lru_cache(maxsize=8)
def derive_aux_key(params: BinaryParams) -> AuxKey:
    """Expand the auxiliary key ``B1 = [I | B1']``, ``b_j = [0 | e_j | b_j']``."""
    base = params.base
    n, lam, slots, degree = base.msis_rank, base.mlwe_rank, params.aux_slots, base.degree
    stream = sampling.XofStream(_KEY_DOMAIN + params.parameter_id)
    b1_tail = sampling.uniform_poly(stream, base.modulus, n * (slots + lam) * degree)
    slot_tails = sampling.uniform_poly(stream, base.modulus, slots * lam * degree)
    b1_tail = b1_tail.reshape(n, slots + lam, degree)
    slot_tails = slot_tails.reshape(slots, lam, degree)
    rows = np.zeros((n + slots, params.aux_width, degree), dtype=np.int64)
    rows[:n, :n] = _identity_block(n, degree)
    rows[:n, n:] = b1_tail
    rows[n:, n:n + slots] = _identity_block(slots, degree)
    rows[n:, n + slots:] = slot_tails
    return AuxKey(params, _freeze(rows), _freeze(slot_tails))


# ------------------------------------------------------------------- polynomials


def sigma(polys: np.ndarray, q: int) -> np.ndarray:
    """The automorphism X -> X^-1 on the last axis: a_0 stays, a_i moves to -a_(N-i)."""
    polys = np.asarray(polys, dtype=np.int64)
    result = np.empty_like(polys)
    result[..., 0] = polys[..., 0] % q
    result[..., 1:] = (-polys[..., :0:-1]) % q
    return result


def _scalar_combination(scalars: np.ndarray, polys: np.ndarray, q: int) -> np.ndarray:
    """Return ``sum_b scalars[a, b] * polys[b]`` without overflowing int64."""
    result = np.zeros((scalars.shape[0], polys.shape[1]), dtype=np.int64)
    for index in range(scalars.shape[1]):
        result = (result + scalars[:, index:index + 1] * polys[index]) % q
    return result


def _ones(degree: int) -> np.ndarray:
    return np.ones(degree, dtype=np.int64)


# ---------------------------------------------------------------------- messages


def binary_message(params: BinaryParams, message: object) -> np.ndarray:
    """Require a (N,) integer array with every coefficient in {0, 1}."""
    values = bdlop.integer_array(message, (params.degree,), "message")
    if int(values.min()) < 0 or int(values.max()) > 1:
        raise ValueError("message coefficients must be binary")
    return values


def encode_bits(params: BinaryParams, data: bytes) -> np.ndarray:
    """Map exactly ``N / 8`` bytes to N binary coefficients, most significant bit first."""
    if not isinstance(data, bytes) or len(data) != params.message_bytes:
        raise ValueError(f"binary message must be exactly {params.message_bytes} bytes")
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8)).astype(np.int64)


def decode_bits(params: BinaryParams, message: np.ndarray) -> bytes:
    return np.packbits(binary_message(params, message).astype(np.uint8)).tobytes()


def commit(params: BinaryParams, message: np.ndarray, randomness: np.ndarray) -> Commitment:
    """Commit under the base key; ``message`` may be any reduced polynomial."""
    return bdlop.commit(params.base, message, randomness)


def sample_randomness(params: BinaryParams, seed: bytes | None = None) -> np.ndarray:
    return bdlop.sample_randomness(params.base, seed)


# ---------------------------------------------------------------- Fiat-Shamir


def _length_prefixed(data: bytes) -> bytes:
    return struct.pack(">Q", len(data)) + data


def _seed(domain: bytes, *parts: bytes) -> bytes:
    transcript = hashlib.shake_256(domain)
    for part in parts:
        transcript.update(part)
    return transcript.digest(CHALLENGE_SEED_BYTES)


def _expand(seed: bytes, q: int, count: int) -> np.ndarray:
    return sampling.uniform_poly(sampling.XofStream(_EXPAND_DOMAIN + seed), q, count)


def _lift_seed(params: BinaryParams, statement: bytes, commitment_bytes: bytes) -> bytes:
    return _seed(_LIFT_DOMAIN, params.parameter_id, _length_prefixed(statement), commitment_bytes)


def _lift_challenges(params: BinaryParams, seed: bytes) -> np.ndarray:
    k, degree = params.lift_repetitions, params.degree
    return _expand(seed, params.modulus, k * degree).reshape(k, degree)


@dataclass(frozen=True)
class _Check:
    """Functionals of step 3 that do not depend on ``alpha``."""

    sigma_rho: np.ndarray   # (k', k, N): sigma(rho_{t,i})
    mu: np.ndarray          # (k', k)
    r_sum: np.ndarray       # (k', N): sum_i R_{t,i}


def _check_challenges(params: BinaryParams, seed: bytes, gammas: np.ndarray) -> _Check:
    q, degree = params.modulus, params.degree
    k, checks = params.lift_repetitions, params.check_repetitions
    expanded = _expand(seed, q, checks * k * (degree + 1))
    rho = expanded[:checks * k * degree].reshape(checks, k, degree)
    mu = expanded[checks * k * degree:].reshape(checks, k)
    sigma_rho = sigma(rho, q)
    r_terms = sigma((gammas[np.newaxis] * sigma_rho) % q, q)
    r_sum = np.zeros((checks, degree), dtype=np.int64)
    for index in range(k):
        r_sum = (r_sum + r_terms[:, index]) % q
    return _Check(sigma_rho, mu, r_sum)


@dataclass(frozen=True)
class _Combination:
    """Coefficients of the combined relation ``P`` after ``alpha`` is known.

    ``P = psi m + coef_m m + sum_j coef[j] s_j - H`` with ``psi = sum_i beta_i u_i``
    and ``s_j`` the lifts and masks committed in D.
    """

    beta: np.ndarray        # (k, N)
    coef: np.ndarray        # (k + k', N)
    coef_m: np.ndarray      # (N,)
    combined_mask: np.ndarray  # (N,): H = sum_t alpha_t h_t
    projections: np.ndarray    # (3, aux_width, N): rows for psi, the linear part, G


def _combination(
    params: BinaryParams, check: _Check, alphas: np.ndarray, masks: np.ndarray
) -> _Combination:
    q, degree = params.modulus, params.degree
    k, n = params.lift_repetitions, params.base.msis_rank
    aux = derive_aux_key(params)
    beta = _scalar_combination(check.mu.T, alphas, q)
    pi = fast_ring.matvec(check.sigma_rho.transpose(1, 0, 2), alphas, q)
    coef = np.concatenate([(pi - fast_ring.scale(_ones(degree), beta, q)) % q, alphas])
    coef_m = (-fast_ring.dot(check.r_sum, alphas, q)) % q
    combined_mask = fast_ring.dot(masks, alphas, q)
    lam_first = aux.slot_tails.transpose(1, 0, 2)  # (lam, slots, N)
    projections = np.zeros((3, params.aux_width, degree), dtype=np.int64)
    slot = slice(n, n + params.aux_slots)
    projections[0, slot][:k] = beta
    projections[0, n + params.aux_slots:] = fast_ring.matvec(lam_first[:, :k], beta, q)
    projections[1, slot][:len(coef)] = coef
    projections[1, n + params.aux_slots:] = fast_ring.matvec(lam_first[:, :len(coef)], coef, q)
    projections[2] = aux.rows[n + params.aux_slots - 1]
    return _Combination(beta, coef, coef_m, combined_mask, projections)


def _challenge_seed(
    combine_seed: bytes, garbage_bytes: bytes, w: np.ndarray, w_aux: np.ndarray, v: np.ndarray
) -> bytes:
    return _seed(
        _CHALLENGE_DOMAIN, combine_seed, garbage_bytes,
        w.astype(">u8").tobytes(), w_aux.astype(">u8").tobytes(), v.astype(">u8").tobytes(),
    )


def abort_probability_log2(params: BinaryParams, attempts: int | None = None) -> float:
    attempts = MAX_ATTEMPTS if attempts is None else attempts
    accepted = params.acceptance_probability
    if accepted >= 1.0:
        return -math.inf
    return attempts * math.log2(1.0 - accepted)


# ------------------------------------------------------------------------ prover


@dataclass(frozen=True)
class _Openings:
    """Products of one masked vector (``y`` honest, ``z`` in the verifier)."""

    w: np.ndarray
    a_m: np.ndarray
    w_aux: np.ndarray
    a_psi: np.ndarray
    a_linear: np.ndarray
    a_garbage: np.ndarray


def _open(params: BinaryParams, combo: _Combination, vector: np.ndarray, aux_vector: np.ndarray) -> _Openings:
    q, n = params.modulus, params.base.msis_rank
    base_rows = fast_ring.matvec(_base_key(params.base).rows, vector, q)
    aux_rows = derive_aux_key(params).rows[:n]
    aux = fast_ring.matvec(np.concatenate([aux_rows, combo.projections]), aux_vector, q)
    a_m = base_rows[n]
    a_linear = (aux[n + 1] + ring.poly_mul(combo.coef_m, a_m, q)) % q
    return _Openings(base_rows[:n], a_m, aux[:n], aux[n], a_linear, aux[n + 2])


def _masks_from(
    params: BinaryParams, check: _Check, lifts: np.ndarray, garbage: np.ndarray, message: np.ndarray
) -> np.ndarray:
    """``h_t = g_t + E_t`` of step 3."""
    q, degree = params.modulus, params.degree
    shifted = (message - _ones(degree)) % q
    quadratic = fast_ring.scale(shifted, lifts, q)
    linear = fast_ring.matvec(check.sigma_rho, lifts, q)
    recentred = fast_ring.scale(message % q, check.r_sum, q)
    return (garbage + linear - recentred + _scalar_combination(check.mu, quadratic, q)) % q


def _pack_rows(rows: np.ndarray, bits: int) -> bytes:
    return codec.pack_uints(rows.reshape(-1), bits)


def _prove(
    params: BinaryParams, statement: bytes, commitment: Commitment, message: np.ndarray,
    randomness: np.ndarray, entropy: bytes, *, lift_override: LiftOverride | None = None,
) -> ProofResult:
    """Run the protocol; the caller has validated the witness (tests skip that)."""
    base, q, degree = params.base, params.modulus, params.degree
    k, n = params.lift_repetitions, base.msis_rank
    aux_key = derive_aux_key(params)
    commitment_bytes = commitment.to_bytes(base)
    mask_key = hedged_mask_key(entropy, statement, commitment_bytes, message, randomness)

    lift_seed = _lift_seed(params, statement, commitment_bytes)
    gammas = _lift_challenges(params, lift_seed)
    lifts = sigma((gammas * message) % q, q)
    if lift_override is not None:
        lifts = np.asarray(lift_override(lifts, gammas), dtype=np.int64) % q
    witness_stream = sampling.XofStream(_AUX_DOMAIN + mask_key)
    aux_randomness = sampling.ternary_vector(witness_stream, (params.aux_width, degree))
    garbage = sampling.uniform_poly(
        witness_stream, q, params.check_repetitions * degree
    ).reshape(params.check_repetitions, degree)
    garbage[:, 0] = 0
    aux_rows = fast_ring.matvec(aux_key.rows, aux_randomness % q, q)
    aux_commitment = np.concatenate([aux_rows[:n], (aux_rows[n:n + k + len(garbage)]
                                                   + np.concatenate([lifts, garbage])) % q])
    aux_bytes = _pack_rows(aux_commitment, base.modulus_bits)

    check_seed = _seed(_CHECK_DOMAIN, lift_seed, aux_bytes)
    check = _check_challenges(params, check_seed, gammas)
    masks = _masks_from(params, check, lifts, garbage, message)
    mask_bytes = _pack_rows(masks[:, 1:], base.modulus_bits)

    combine_seed = _seed(_COMBINE_DOMAIN, check_seed, mask_bytes)
    alphas = _expand(combine_seed, q, params.check_repetitions * degree).reshape(-1, degree)
    combo = _combination(params, check, alphas, masks)
    psi = fast_ring.dot(combo.beta, lifts, q)
    garbage_randomness = aux_rows[n + params.aux_slots - 1]
    secrets = np.concatenate([randomness, aux_randomness]) % q

    for attempt in range(1, MAX_ATTEMPTS + 1):
        stream = sampling.XofStream(_MASK_DOMAIN + mask_key + struct.pack(">I", attempt))
        mask = sampling.mask_vector(stream, base.mask_bound, (base.width, degree))
        aux_mask = sampling.mask_vector(stream, base.mask_bound, (params.aux_width, degree))
        opened = _open(params, combo, mask % q, aux_mask % q)
        first_order = fast_ring.scale(opened.a_m, np.stack([psi, opened.a_psi]), q)
        quadratic_linear = (ring.poly_mul(opened.a_psi, message % q, q) + first_order[0]) % q
        garbage_term = (-(quadratic_linear + opened.a_linear)) % q
        garbage_bytes = codec.pack_uints((garbage_randomness + garbage_term) % q, base.modulus_bits)
        v = (first_order[1] + opened.a_garbage) % q
        seed = _challenge_seed(combine_seed, garbage_bytes, opened.w, opened.w_aux, v)
        challenge = sampling.challenge_poly(seed, degree, base.challenge_weight)
        shifts = ring.center(fast_ring.scale(challenge % q, secrets, q), q)
        responses = np.concatenate([mask, aux_mask]) + shifts
        if int(np.abs(responses).max()) > base.response_bound:
            continue
        packed = codec.pack_uints(responses + base.response_bound, base.response_bits)
        return ProofResult(aux_bytes + mask_bytes + garbage_bytes + seed + packed, attempt)
    raise RuntimeError("rejection sampling did not terminate")


def prove_with_stats(
    params: BinaryParams, statement: bytes, commitment: Commitment, message: np.ndarray,
    randomness: np.ndarray, *, mask_seed: bytes | None = None,
) -> ProofResult:
    """Prove that ``commitment`` hides the binary ``message``, bound to ``statement``."""
    if not isinstance(params, BinaryParams):
        raise TypeError("params must be a BinaryParams set")
    if not isinstance(statement, bytes):
        raise TypeError("statement must be bytes")
    message = binary_message(params, message)
    randomness = ternary_randomness(params.base, randomness)
    commitment = require_commitment(params.base, commitment)
    if not bdlop.verify_opening(params.base, commitment, message, randomness):
        raise ValueError("message and randomness do not open the commitment")
    return _prove(params, statement, commitment, message, randomness, prover_entropy(mask_seed))


def prove(
    params: BinaryParams, statement: bytes, commitment: Commitment, message: np.ndarray,
    randomness: np.ndarray,
) -> bytes:
    return prove_with_stats(params, statement, commitment, message, randomness).proof


# ---------------------------------------------------------------------- verifier


@dataclass(frozen=True)
class _ParsedProof:
    aux_bytes: bytes
    aux_commitment: np.ndarray  # (n + k + k', N)
    mask_bytes: bytes
    masks: np.ndarray           # (k', N) with ct = 0
    garbage_bytes: bytes
    garbage: np.ndarray         # (N,)
    seed: bytes
    responses: np.ndarray       # (k_base + aux_width, N), centred


def _parse(params: BinaryParams, proof: bytes) -> _ParsedProof:
    """Split and canonically decode a proof of the exact length; raise ``ValueError``."""
    base, q, degree = params.base, params.modulus, params.degree
    k, checks, n = params.lift_repetitions, params.check_repetitions, base.msis_rank
    sizes = (params.aux_commitment_bytes, params.mask_bytes, params.garbage_bytes,
             CHALLENGE_SEED_BYTES, params.response_bytes)
    if len(proof) != sum(sizes):
        raise ValueError("binary proof has the wrong length")
    fields, offset = [], 0
    for size in sizes:
        fields.append(proof[offset:offset + size])
        offset += size
    aux_bytes, mask_bytes, garbage_bytes, seed, response_bytes = fields
    rows = n + k + checks
    aux_commitment = codec.unpack_uints(aux_bytes, rows * degree, base.modulus_bits, q)
    tails = codec.unpack_uints(mask_bytes, checks * (degree - 1), base.modulus_bits, q)
    masks = np.zeros((checks, degree), dtype=np.int64)
    masks[:, 1:] = tails.reshape(checks, degree - 1)
    garbage = codec.unpack_uints(garbage_bytes, degree, base.modulus_bits, q)
    shifted = codec.unpack_uints(
        response_bytes, params.response_polys * degree, base.response_bits, 2 * base.response_bound + 1
    )
    responses = (shifted - base.response_bound).reshape(params.response_polys, degree)
    return _ParsedProof(
        aux_bytes, aux_commitment.reshape(rows, degree), mask_bytes, masks,
        garbage_bytes, garbage, seed, responses,
    )


def _recomputed_seed(
    params: BinaryParams, statement: bytes, commitment: Commitment, parsed: _ParsedProof
) -> bytes:
    base, q, degree = params.base, params.modulus, params.degree
    k, n = params.lift_repetitions, base.msis_rank
    commitment_bytes = commitment.to_bytes(base)
    lift_seed = _lift_seed(params, statement, commitment_bytes)
    gammas = _lift_challenges(params, lift_seed)
    check_seed = _seed(_CHECK_DOMAIN, lift_seed, parsed.aux_bytes)
    check = _check_challenges(params, check_seed, gammas)
    combine_seed = _seed(_COMBINE_DOMAIN, check_seed, parsed.mask_bytes)
    alphas = _expand(combine_seed, q, params.check_repetitions * degree).reshape(-1, degree)
    combo = _combination(params, check, alphas, parsed.masks)

    challenge = sampling.challenge_poly(parsed.seed, degree, base.challenge_weight) % q
    responses = parsed.responses % q
    opened = _open(params, combo, responses[:base.width], responses[base.width:])
    slot_rows = parsed.aux_commitment[n:]
    psi_commitment = fast_ring.dot(combo.beta, slot_rows[:k], q)
    linear_commitment = (fast_ring.dot(combo.coef, slot_rows, q)
                         + ring.poly_mul(combo.coef_m, commitment.t2, q)) % q
    scaled = fast_ring.scale(challenge, np.concatenate([
        commitment.t1, parsed.aux_commitment[:n],
        np.stack([commitment.t2, psi_commitment, linear_commitment,
                  combo.combined_mask, parsed.garbage]),
    ]), q)
    c_t1, c_t1_aux = scaled[:n], scaled[n:2 * n]
    c_t2, c_psi, c_linear, c_mask, c_garbage = scaled[2 * n:]
    w = (opened.w - c_t1) % q
    w_aux = (opened.w_aux - c_t1_aux) % q
    f_m = (c_t2 - opened.a_m) % q
    f_psi = (c_psi - opened.a_psi) % q
    f_linear = (c_linear - opened.a_linear) % q
    f_garbage = (c_garbage - opened.a_garbage) % q
    # F(c) = f_psi f_m + c (L(f) - c H);  v = F(c) - f_G.
    inner = (f_linear - c_mask) % q
    value = (ring.poly_mul(f_psi, f_m, q) + ring.poly_mul(challenge, inner, q) - f_garbage) % q
    return _challenge_seed(combine_seed, parsed.garbage_bytes, w, w_aux, value)


def verify(params: BinaryParams, statement: bytes, commitment: Commitment, proof: bytes) -> bool:
    """Verify a binary proof; malformed or non-canonical input returns ``False``."""
    if not isinstance(params, BinaryParams):
        return False
    if not isinstance(statement, bytes) or not isinstance(proof, bytes):
        return False
    if len(proof) != params.proof_bytes:
        return False
    try:
        commitment = require_commitment(params.base, commitment)
        parsed = _parse(params, proof)
    except (TypeError, ValueError):
        return False
    expected = _recomputed_seed(params, statement, commitment, parsed)
    return hmac.compare_digest(parsed.seed, expected)


__all__ = [
    "BINARY_128",
    "BINARY_TOY",
    "MAX_ATTEMPTS",
    "AuxKey",
    "BinaryParams",
    "abort_probability_log2",
    "binary_message",
    "commit",
    "decode_bits",
    "derive_aux_key",
    "encode_bits",
    "prove",
    "prove_with_stats",
    "sample_randomness",
    "sigma",
    "verify",
]
