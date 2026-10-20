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
from .bdlop import Commitment, CommitmentKey, derive_key
from .params import CHALLENGE_SEED_BYTES, BdlopParams

_CHALLENGE_DOMAIN = b"zkstego/lattice-zk/bdlop-open/v1/fiat-shamir\0"
_MASK_DOMAIN = b"zkstego/lattice-zk/bdlop-open/v1/mask\0"
MAX_ATTEMPTS = 512


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


def hedged_mask_key(entropy: bytes, statement: bytes, *witness_context: bytes | np.ndarray) -> bytes:
    """Bind mask randomness to the statement and witness, as hedged ML-DSA does.

    Reusing one mask for two challenges would reveal the witness, so the mask
    stream never depends on the entropy alone.
    """
    digest = hashlib.sha3_256(entropy + struct.pack(">Q", len(statement)) + statement)
    for item in witness_context:
        encoded = item if isinstance(item, bytes) else item.astype(">i8").tobytes()
        digest.update(struct.pack(">Q", len(encoded)) + encoded)
    return digest.digest()


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
    if randomness.shape != (params.width, params.degree) or int(np.abs(randomness).max()) > 1:
        raise ValueError("commitment randomness must be a ternary (k, N) vector")
    key = derive_key(params)
    if not np.array_equal(key.apply_b1(randomness % params.modulus), commitment.t1):
        raise ValueError("randomness does not open the commitment")
    commitment_bytes = commitment.to_bytes(params)
    entropy = os.urandom(32) if mask_seed is None else mask_seed
    mask_key = hedged_mask_key(entropy, statement, commitment_bytes, randomness)
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
    q = params.modulus
    seed = proof[:CHALLENGE_SEED_BYTES]
    try:
        shifted = codec.unpack_uints(
            proof[CHALLENGE_SEED_BYTES:], params.width * params.degree,
            params.response_bits, 2 * params.response_bound + 1,
        )
        commitment_bytes = commitment.to_bytes(params)
    except ValueError:
        return False
    response = (shifted - params.response_bound).reshape(params.width, params.degree)
    challenge = sampling.challenge_poly(seed, params.degree, params.challenge_weight)
    key = derive_key(params)
    w = (key.apply_b1(response % q) - _challenge_times(challenge, commitment.t1, q)) % q
    return hmac.compare_digest(seed, _challenge_seed(params, statement, commitment_bytes, w))
