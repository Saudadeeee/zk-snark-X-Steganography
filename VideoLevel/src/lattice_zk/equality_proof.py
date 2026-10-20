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
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct

import numpy as np

from . import codec, ring, sampling
from .bdlop import Commitment, derive_key
from .opening_proof import MAX_ATTEMPTS, ProofResult, _challenge_times, hedged_mask_key
from .params import CHALLENGE_SEED_BYTES, BdlopParams

_CHALLENGE_DOMAIN = b"zkstego/lattice-zk/bdlop-equal/v1/fiat-shamir\0"
_MASK_DOMAIN = b"zkstego/lattice-zk/bdlop-equal/v1/mask\0"


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


def prove_with_stats(
    params: BdlopParams, statement: bytes,
    first: Commitment, first_randomness: np.ndarray,
    second: Commitment, second_randomness: np.ndarray,
    *, mask_seed: bytes | None = None,
) -> ProofResult:
    """Prove both commitments hide one message, bound to ``statement``."""
    if not isinstance(statement, bytes):
        raise TypeError("statement must be bytes")
    shape = (params.width, params.degree)
    for randomness in (first_randomness, second_randomness):
        if randomness.shape != shape or int(np.abs(randomness).max()) > 1:
            raise ValueError("commitment randomness must be a ternary (k, N) vector")
    key, q = derive_key(params), params.modulus
    for commitment, randomness in ((first, first_randomness), (second, second_randomness)):
        if not np.array_equal(key.apply_b1(randomness % q), commitment.t1):
            raise ValueError("randomness does not open the commitment")
    gap = key.apply_b2((first_randomness - second_randomness) % q)
    if not np.array_equal(gap, (first.t2 - second.t2) % q):
        raise ValueError("commitments do not hide the same message")
    commitments = (first.to_bytes(params), second.to_bytes(params))
    entropy = os.urandom(32) if mask_seed is None else mask_seed
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
    q, rows = params.modulus, params.width
    seed = proof[:CHALLENGE_SEED_BYTES]
    try:
        shifted = codec.unpack_uints(
            proof[CHALLENGE_SEED_BYTES:], 2 * rows * params.degree,
            params.response_bits, 2 * params.response_bound + 1,
        )
        commitments = (first.to_bytes(params), second.to_bytes(params))
    except ValueError:
        return False
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
