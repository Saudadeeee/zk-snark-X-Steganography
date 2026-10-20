"""Proof that two BDLOP commitments open to the same message.

Linear-relation proof of Baum et al. (SCN 2018) specialised to equality.  For
``C_a = Com(m; r_a)`` and ``C_b = Com(m; r_b)`` under one key:

    P: w_a = B1 y_a,  w_b = B1 y_b,  u = <b2, y_a - y_b>
    V: c
    P: z_a = y_a + c r_a,  z_b = y_b + c r_b      (abort unless both in range)
    V: B1 z_a = w_a + c t1_a,   B1 z_b = w_b + c t1_b,
       <b2, z_a - z_b> = u + c (t2_a - t2_b)

Extraction gives relaxed openings of both commitments with one challenge
difference ``f`` and ``f (t2_a - t2_b) = <b2, rbar_a - rbar_b>``, so both
extracted messages coincide.  It adds no communication beyond the two opening
proofs it replaces.

Either witness may be the all-zero vector (it is ternary): with
``C_b = Com(m; 0) = (0, m)`` the proof shows that ``C_a`` hides the public
message ``m`` without revealing ``r_a``, which is how payloads are disclosed
(``video_proof.create_disclosure``).
"""

from __future__ import annotations

import hashlib
import hmac
import math
import struct

import numpy as np

from . import codec, ring, sampling
from .bdlop import Commitment, derive_key, ternary_randomness
from .opening_proof import (
    ProofResult,
    _canonical_or_none,
    _challenge_times,
    hedged_mask_key,
    prover_entropy,
    require_commitment,
)
from .params import CHALLENGE_SEED_BYTES, BdlopParams

_CHALLENGE_DOMAIN = b"zkstego/lattice-zk/bdlop-equal/v1/fiat-shamir\0"
_MASK_DOMAIN = b"zkstego/lattice-zk/bdlop-equal/v1/mask\0"
# Both responses must be accepted, so an attempt succeeds with probability
# p_acc^2 (about 0.046 for the production set).  The opening proof's cap of
# 512 would leave a 2^-35 failure probability; 4096 attempts give about
# 2^-279.  A larger cap leaks nothing: acceptance does not depend on the witness.
MAX_ATTEMPTS = 4096
COMPLETENESS_ERROR_BITS = 128


def abort_probability_log2(params: BdlopParams, attempts: int | None = None) -> float:
    """log2 of the probability that ``attempts`` (default: the cap) all abort.

    Each response is accepted independently with the exact probability
    ``params.acceptance_probability``, whatever the witness.
    """
    attempts = MAX_ATTEMPTS if attempts is None else attempts
    accepted = params.acceptance_probability ** 2
    if accepted >= 1.0:
        return -math.inf
    return attempts * math.log2(1.0 - accepted)


def proof_bytes(params: BdlopParams) -> int:
    return CHALLENGE_SEED_BYTES + (2 * params.width * params.degree * params.response_bits + 7) // 8


def _challenge_seed(
    params: BdlopParams, statement: bytes, commitments: tuple[bytes, bytes],
    announcements: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> bytes:
    transcript = hashlib.shake_256()
    transcript.update(_CHALLENGE_DOMAIN + params.parameter_id)
    transcript.update(struct.pack(">Q", len(statement)) + statement)
    for encoded in commitments:
        transcript.update(encoded)
    for announcement in announcements:
        transcript.update(announcement.astype(">u8").tobytes())
    return transcript.digest(CHALLENGE_SEED_BYTES)


def _in_range(params: BdlopParams, response: np.ndarray) -> bool:
    return int(np.abs(response).max()) <= params.response_bound


def _checked_witness(
    params: BdlopParams, first: Commitment, first_randomness: np.ndarray,
    second: Commitment, second_randomness: np.ndarray,
) -> tuple[tuple[Commitment, Commitment], tuple[np.ndarray, np.ndarray]]:
    """Refuse unless both openings are valid and the message gap is zero.

    Returns the ``int64``-normalized commitments and witnesses.
    """
    witnesses = (ternary_randomness(params, first_randomness), ternary_randomness(params, second_randomness))
    commitments = (require_commitment(params, first), require_commitment(params, second))
    key, q = derive_key(params), params.modulus
    for commitment, randomness in zip(commitments, witnesses):
        if not np.array_equal(key.apply_b1(randomness % q), commitment.t1):
            raise ValueError("randomness does not open the commitment")
    gap = key.apply_b2((witnesses[0] - witnesses[1]) % q)
    if not np.array_equal(gap, (commitments[0].t2 - commitments[1].t2) % q):
        raise ValueError("commitments do not hide the same message")
    return commitments, witnesses


def prove_with_stats(
    params: BdlopParams, statement: bytes,
    first: Commitment, first_randomness: np.ndarray,
    second: Commitment, second_randomness: np.ndarray,
    *, mask_seed: bytes | None = None,
) -> ProofResult:
    """Prove both commitments hide one message, bound to ``statement``."""
    if not isinstance(statement, bytes):
        raise TypeError("statement must be bytes")
    (first, second), (first_randomness, second_randomness) = _checked_witness(
        params, first, first_randomness, second, second_randomness
    )
    shape = (params.width, params.degree)
    key, q = derive_key(params), params.modulus
    commitments = (first.to_bytes(params), second.to_bytes(params))
    entropy = prover_entropy(mask_seed)
    mask_key = hedged_mask_key(
        entropy, statement, *commitments, first_randomness, second_randomness
    )
    for attempt in range(1, MAX_ATTEMPTS + 1):
        stream = sampling.XofStream(_MASK_DOMAIN + mask_key + struct.pack(">I", attempt))
        mask_a = sampling.mask_vector(stream, params.mask_bound, shape)
        mask_b = sampling.mask_vector(stream, params.mask_bound, shape)
        announcements = (
            key.apply_b1(mask_a % q), key.apply_b1(mask_b % q), key.apply_b2((mask_a - mask_b) % q)
        )
        seed = _challenge_seed(params, statement, commitments, announcements)
        challenge = sampling.challenge_poly(seed, params.degree, params.challenge_weight)
        responses = [
            mask + ring.center(shift, q)
            for mask, shift in (
                (mask_a, _challenge_times(challenge, first_randomness, q)),
                (mask_b, _challenge_times(challenge, second_randomness, q)),
            )
        ]
        if all(_in_range(params, response) for response in responses):
            packed = codec.pack_uints(
                np.concatenate(responses) + params.response_bound, params.response_bits
            )
            return ProofResult(seed + packed, attempt)
    raise RuntimeError("rejection sampling did not terminate")


def prove(
    params: BdlopParams, statement: bytes,
    first: Commitment, first_randomness: np.ndarray,
    second: Commitment, second_randomness: np.ndarray,
) -> bytes:
    return prove_with_stats(
        params, statement, first, first_randomness, second, second_randomness
    ).proof


def verify(
    params: BdlopParams, statement: bytes, first: Commitment, second: Commitment, proof: bytes
) -> bool:
    """Verify an equality proof; malformed input returns ``False``."""
    if not isinstance(statement, bytes) or not isinstance(proof, bytes):
        return False
    if len(proof) != proof_bytes(params):
        return False
    first, second = _canonical_or_none(params, first), _canonical_or_none(params, second)
    if first is None or second is None:
        return False
    q, rows = params.modulus, params.width
    seed = proof[:CHALLENGE_SEED_BYTES]
    try:
        shifted = codec.unpack_uints(
            proof[CHALLENGE_SEED_BYTES:], 2 * rows * params.degree,
            params.response_bits, 2 * params.response_bound + 1,
        )
    except ValueError:
        return False
    commitments = (first.to_bytes(params), second.to_bytes(params))
    responses = (shifted - params.response_bound).reshape(2, rows, params.degree) % q
    challenge = sampling.challenge_poly(seed, params.degree, params.challenge_weight)
    key = derive_key(params)
    message_gap = ((first.t2 - second.t2) % q)[np.newaxis, :]
    announcements = (
        (key.apply_b1(responses[0]) - _challenge_times(challenge, first.t1, q)) % q,
        (key.apply_b1(responses[1]) - _challenge_times(challenge, second.t1, q)) % q,
        (key.apply_b2((responses[0] - responses[1]) % q)
         - _challenge_times(challenge, message_gap, q)[0]) % q,
    )
    return hmac.compare_digest(seed, _challenge_seed(params, statement, commitments, announcements))
