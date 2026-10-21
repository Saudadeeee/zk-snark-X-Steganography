"""Fiat-Shamir-with-aborts proof of knowledge of a BDLOP opening.

Interactive protocol (Baum et al., SCN 2018, opening proof):

    P: y <- mask^k,  w = B1 y                 V: c <- challenge set
    P: z = y + c r,  abort unless ||z||_inf <= gamma - kappa - 1
    V: accept iff ||z||_inf is in range and B1 z = w + c t1

The non-interactive proof is ``(seed, z)`` with
``seed = H(parameter_id, statement, commitment, w)`` and ``c`` expanded from
``seed``.  Two accepting transcripts with one ``w`` give a relaxed opening
``B1 (z - z') = (c - c') t1`` with an invertible ``c - c'``; accepted ``z`` is
uniform on its range, independent of ``r``.  Only accepted transcripts leave
this module.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct
from dataclasses import dataclass

import numpy as np

from . import codec, ring, sampling
from .bdlop import Commitment, CommitmentKey, derive_key, ternary_randomness
from .params import BDLOP_OPEN_128_V1, CHALLENGE_SEED_BYTES, BdlopParams

_CHALLENGE_DOMAIN = b"zkstego/lattice-zk/bdlop-open/v1/fiat-shamir\0"
_MASK_DOMAIN = b"zkstego/lattice-zk/bdlop-open/v1/mask\0"
MAX_ATTEMPTS = 512
ENTROPY_BYTES = 32
# D7: domain tag of the hedged mask key, and the protocols that use it.
_HEDGE_DOMAIN = b"zkstego/lattice-zk/hedged-mask-key/v2\0"
HEDGE_OPENING = b"bdlop-open"
HEDGE_EQUALITY = b"bdlop-equal"
HEDGE_BINARY = b"bdlop-binary"
HEDGE_PROTOCOLS = frozenset({HEDGE_OPENING, HEDGE_EQUALITY, HEDGE_BINARY})
# Frozen pre-D7 derivation, kept only for bdlop-open-128-v1 (kat_v1.json).
_UNTAGGED_HEDGE_PARAMETER_IDS = frozenset({BDLOP_OPEN_128_V1.parameter_id})
_UNTAGGED_HEDGE_PROTOCOLS = frozenset({HEDGE_OPENING, HEDGE_EQUALITY})


@dataclass(frozen=True)
class ProofResult:
    proof: bytes
    attempts: int


def _challenge_seed(
    params: BdlopParams, statement: bytes, commitment_bytes: bytes, w: np.ndarray
) -> bytes:
    transcript = hashlib.shake_256()
    transcript.update(_CHALLENGE_DOMAIN + params.parameter_id)
    transcript.update(struct.pack(">Q", len(statement)) + statement)
    transcript.update(commitment_bytes)
    transcript.update(w.astype(">u8").tobytes())
    return transcript.digest(CHALLENGE_SEED_BYTES)


def prover_entropy(mask_seed: bytes | None) -> bytes:
    """Fresh 32-byte prover entropy, or an explicit seed for known-answer tests."""
    if mask_seed is None:
        return os.urandom(ENTROPY_BYTES)
    if not isinstance(mask_seed, bytes) or len(mask_seed) != ENTROPY_BYTES:
        raise ValueError(f"mask seed must be exactly {ENTROPY_BYTES} bytes")
    return mask_seed


def require_commitment(params: BdlopParams, commitment: object) -> Commitment:
    """Return an ``int64`` copy of a canonical commitment for ``params``, else raise."""
    if not isinstance(commitment, Commitment):
        raise TypeError("commitment must be a BDLOP Commitment")
    return commitment.normalized(params)


def _canonical_or_none(params: BdlopParams, commitment: object) -> Commitment | None:
    try:
        return require_commitment(params, commitment)
    except (TypeError, ValueError):
        return None


def hedged_mask_key(
    entropy: bytes, statement: bytes, *witness_context: bytes | np.ndarray,
    protocol: bytes, parameter_id: bytes,
) -> bytes:
    """Bind mask randomness to the statement and witness, as hedged ML-DSA does.

    Reusing one mask for two challenges would reveal the witness, so the mask
    stream never depends on the entropy alone.  The entropy is not length
    prefixed, so it must have the fixed width ``ENTROPY_BYTES``.

    The hash input starts with a domain tag, the proof protocol and the
    parameter-set identifier (D7), so it is separated from every other
    SHA3-256 use and from the other proofs' mask keys without relying on the
    entropy being uniform.  Only ``bdlop-open-128-v1`` opening and equality
    proofs keep the earlier untagged derivation, so its known-answer vectors
    stay reproducible.  The derivation is prover-side only: a verifier never
    recomputes a mask, so proofs from either derivation verify identically.
    """
    if not isinstance(entropy, bytes) or len(entropy) != ENTROPY_BYTES:
        raise ValueError(f"prover entropy must be exactly {ENTROPY_BYTES} bytes")
    if protocol not in HEDGE_PROTOCOLS:
        raise ValueError("unknown proof protocol for the hedged mask key")
    if not isinstance(parameter_id, bytes) or len(parameter_id) != 32:
        raise ValueError("parameter id must be exactly 32 bytes")
    if parameter_id in _UNTAGGED_HEDGE_PARAMETER_IDS and protocol in _UNTAGGED_HEDGE_PROTOCOLS:
        digest = hashlib.sha3_256()
    else:
        digest = hashlib.sha3_256(_HEDGE_DOMAIN)
        for label in (protocol, parameter_id):
            digest.update(struct.pack(">Q", len(label)) + label)
    digest.update(entropy + struct.pack(">Q", len(statement)) + statement)
    for item in witness_context:
        encoded = item if isinstance(item, bytes) else item.astype(">i8").tobytes()
        digest.update(struct.pack(">Q", len(encoded)) + encoded)
    return digest.digest()


def uses_untagged_hedge(parameter_id: bytes, protocol: bytes) -> bool:
    """True only for the frozen pre-D7 derivation (``bdlop-open-128-v1``)."""
    return parameter_id in _UNTAGGED_HEDGE_PARAMETER_IDS and protocol in _UNTAGGED_HEDGE_PROTOCOLS


def _challenge_times(challenge: np.ndarray, vector: np.ndarray, q: int) -> np.ndarray:
    reduced = challenge % q
    return np.stack([ring.poly_mul(reduced, poly, q) for poly in vector % q])


def _respond(
    params: BdlopParams, key: CommitmentKey, statement: bytes, commitment_bytes: bytes,
    randomness: np.ndarray, mask: np.ndarray,
) -> tuple[bytes, np.ndarray] | None:
    """Run one attempt; return ``(seed, z)`` or ``None`` on abort."""
    q = params.modulus
    seed = _challenge_seed(params, statement, commitment_bytes, key.apply_b1(mask % q))
    challenge = sampling.challenge_poly(seed, params.degree, params.challenge_weight)
    # |c r| <= kappa < q/2, so centering recovers the integer product exactly.
    response = mask + ring.center(_challenge_times(challenge, randomness, q), q)
    if int(np.abs(response).max()) > params.response_bound:
        return None
    return seed, response


def prove_with_stats(
    params: BdlopParams, statement: bytes, commitment: Commitment, randomness: np.ndarray,
    *, mask_seed: bytes | None = None,
) -> ProofResult:
    """Prove knowledge of ``randomness`` opening ``commitment``, bound to ``statement``."""
    if not isinstance(statement, bytes):
        raise TypeError("statement must be bytes")
    randomness = ternary_randomness(params, randomness)
    commitment = require_commitment(params, commitment)
    commitment_bytes = commitment.to_bytes(params)
    key = derive_key(params)
    if not np.array_equal(key.apply_b1(randomness % params.modulus), commitment.t1):
        raise ValueError("randomness does not open the commitment")
    entropy = prover_entropy(mask_seed)
    mask_key = hedged_mask_key(
        entropy, statement, commitment_bytes, randomness,
        protocol=HEDGE_OPENING, parameter_id=params.parameter_id,
    )
    for attempt in range(1, MAX_ATTEMPTS + 1):
        stream = sampling.XofStream(_MASK_DOMAIN + mask_key + struct.pack(">I", attempt))
        mask = sampling.mask_vector(stream, params.mask_bound, (params.width, params.degree))
        accepted = _respond(params, key, statement, commitment_bytes, randomness, mask)
        if accepted is not None:
            seed, response = accepted
            packed = codec.pack_uints(response + params.response_bound, params.response_bits)
            return ProofResult(seed + packed, attempt)
    raise RuntimeError("rejection sampling did not terminate")


def prove(
    params: BdlopParams, statement: bytes, commitment: Commitment, randomness: np.ndarray
) -> bytes:
    return prove_with_stats(params, statement, commitment, randomness).proof


def verify(params: BdlopParams, statement: bytes, commitment: Commitment, proof: bytes) -> bool:
    """Verify a proof; malformed or non-canonical input returns ``False``."""
    if not isinstance(statement, bytes) or not isinstance(proof, bytes):
        return False
    if len(proof) != params.proof_bytes:
        return False
    commitment = _canonical_or_none(params, commitment)
    if commitment is None:
        return False
    q = params.modulus
    seed = proof[:CHALLENGE_SEED_BYTES]
    try:
        shifted = codec.unpack_uints(
            proof[CHALLENGE_SEED_BYTES:], params.width * params.degree,
            params.response_bits, 2 * params.response_bound + 1,
        )
    except ValueError:
        return False
    commitment_bytes = commitment.to_bytes(params)
    response = (shifted - params.response_bound).reshape(params.width, params.degree)
    challenge = sampling.challenge_poly(seed, params.degree, params.challenge_weight)
    key = derive_key(params)
    w = (key.apply_b1(response % q) - _challenge_times(challenge, commitment.t1, q)) % q
    return hmac.compare_digest(seed, _challenge_seed(params, statement, commitment_bytes, w))
