"""Zero-knowledge linkage of commitments carried by verified videos.

A linkage proof shows that two commitments hide the same payload without
revealing it.  Two uses:

* two stego videos (in-band envelopes) come from one holder of one payload;
* an in-band video commitment hides exactly a registry-pinned credential,
  which attaches the credential holder's identity to that video afterwards.

The proof is produced offline by whoever holds both openings and is bound to
both commitments and to a caller-supplied context (for example the two video
statement identifiers), so it cannot be moved to another pair of videos.
"""

from __future__ import annotations

import hashlib
import struct

import numpy as np

from . import equality_proof, video_proof
from .bdlop import Commitment
from .params import BdlopParams

_DOMAIN = b"zkstego/lattice-zk/linkage/v1\0"


def linkage_statement(params: BdlopParams, context: tuple[bytes, ...]) -> bytes:
    """Length-prefixed encoding of the public context a linkage is bound to."""
    encoded = _DOMAIN + params.parameter_id + struct.pack(">I", len(context))
    for item in context:
        if not isinstance(item, bytes):
            raise TypeError("linkage context items must be bytes")
        encoded += struct.pack(">Q", len(item)) + item
    return hashlib.sha3_256(encoded).digest()


def envelope_commitment(params: BdlopParams, envelope: bytes) -> Commitment:
    """Commitment carried by an in-band envelope extracted from a video."""
    return video_proof.decode_envelope(params, envelope).commitment


def prove_linkage(
    params: BdlopParams, context: tuple[bytes, ...],
    first: Commitment, first_randomness: np.ndarray,
    second: Commitment, second_randomness: np.ndarray,
) -> bytes:
    """Prove both commitments hide one payload; raises if they do not."""
    return equality_proof.prove(
        params, linkage_statement(params, context),
        first, first_randomness, second, second_randomness,
    )


def verify_linkage(
    params: BdlopParams, context: tuple[bytes, ...],
    first: Commitment, second: Commitment, proof: bytes,
) -> bool:
    try:
        statement = linkage_statement(params, context)
    except TypeError:
        return False
    return equality_proof.verify(params, statement, first, second, proof)
