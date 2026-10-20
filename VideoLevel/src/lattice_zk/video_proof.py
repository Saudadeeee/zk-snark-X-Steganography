"""Video-bound statement and fixed-size in-band envelope for the BDLOP proof.

The verifier builds :class:`VideoStatement` only from its own pins and from
values it derives from the received H.264 stream.  The envelope carries the
commitment and the proof; it never carries the payload, the randomness, or
anything the verifier is expected to trust.
"""

from __future__ import annotations

import hashlib
import hmac
import struct
from dataclasses import dataclass

import numpy as np

from . import bdlop, codec, opening_proof
from .params import BdlopParams

STATEMENT_VERSION = 1
ENVELOPE_MAGIC = b"ZKLB"
REGISTERED_ENVELOPE_MAGIC = b"ZKLR"
ENVELOPE_VERSION = 1
_STATEMENT_DOMAIN = b"zkstego/lattice-zk/video-statement/v1\0"
_VIDEO_COMMITMENT_DOMAIN = b"zkstego/video-zk/video-commitment/v1\0"
_ENVELOPE_HEADER = struct.Struct(">4sB32s32s")
_DIGEST_FIELDS = (
    "relation_id", "parameter_id", "registry_root", "session_challenge",
    "codec_policy_id", "carrier_profile_id", "positions_hash", "video_commitment",
)


@dataclass(frozen=True)
class VerifierPins:
    """Values a verifier fixes out of band, never read from the video."""

    relation_id: bytes
    registry_root: bytes
    registry_epoch: int
    codec_policy_id: bytes
    carrier_profile_id: bytes

    def __post_init__(self) -> None:
        for name in ("relation_id", "registry_root", "codec_policy_id", "carrier_profile_id"):
            _require_digest(name, getattr(self, name))
        _require_u64("registry_epoch", self.registry_epoch)


def _require_digest(name: str, value: object) -> None:
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError(f"{name} must be exactly 32 bytes")


def _require_u64(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < 1 << 64:
        raise ValueError(f"{name} must be an unsigned 64-bit integer")


@dataclass(frozen=True)
class VideoStatement:
    relation_id: bytes
    parameter_id: bytes
    registry_root: bytes
    registry_epoch: int
    session_challenge: bytes
    codec_policy_id: bytes
    carrier_profile_id: bytes
    carrier_count: int
    positions_hash: bytes
    video_commitment: bytes

    def __post_init__(self) -> None:
        for name in _DIGEST_FIELDS:
            _require_digest(name, getattr(self, name))
        for name in ("registry_epoch", "carrier_count"):
            _require_u64(name, getattr(self, name))

    def to_bytes(self) -> bytes:
        """Fixed-width canonical encoding absorbed by the Fiat-Shamir hash."""
        return (
            struct.pack(">H", STATEMENT_VERSION)
            + self.relation_id + self.parameter_id + self.registry_root
            + struct.pack(">Q", self.registry_epoch)
            + self.session_challenge + self.codec_policy_id + self.carrier_profile_id
            + struct.pack(">Q", self.carrier_count)
            + self.positions_hash + self.video_commitment
        )

    @property
    def statement_id(self) -> bytes:
        return hashlib.sha3_256(_STATEMENT_DOMAIN + self.to_bytes()).digest()


@dataclass(frozen=True)
class PayloadOpening:
    """Prover-private opening; disclose only to a party entitled to the payload."""

    payload: bytes
    randomness: np.ndarray


@dataclass(frozen=True)
class Envelope:
    parameter_id: bytes
    session_challenge: bytes
    commitment: bdlop.Commitment
    proof: bytes


def video_commitment(canonical_video_sha256: bytes) -> bytes:
    """Domain-separate the carrier-normalized H.264 digest."""
    if not isinstance(canonical_video_sha256, bytes) or len(canonical_video_sha256) != 32:
        raise ValueError("canonical video digest must be exactly 32 bytes")
    return hashlib.sha256(_VIDEO_COMMITMENT_DOMAIN + canonical_video_sha256).digest()


def envelope_size(params: BdlopParams, *, registered: bool = False) -> int:
    """Wire size; a registered commitment is pinned, not carried in the video."""
    carried = 0 if registered else params.commitment_bytes
    return _ENVELOPE_HEADER.size + carried + params.proof_bytes


def build_statement(
    params: BdlopParams, pins: VerifierPins, session_challenge: bytes,
    *, carrier_count: int, positions_hash: bytes, canonical_video_sha256: bytes,
) -> VideoStatement:
    return VideoStatement(
        relation_id=pins.relation_id,
        parameter_id=params.parameter_id,
        registry_root=pins.registry_root,
        registry_epoch=pins.registry_epoch,
        session_challenge=session_challenge,
        codec_policy_id=pins.codec_policy_id,
        carrier_profile_id=pins.carrier_profile_id,
        carrier_count=carrier_count,
        positions_hash=positions_hash,
        video_commitment=video_commitment(canonical_video_sha256),
    )


def encode_envelope(params: BdlopParams, envelope: Envelope) -> bytes:
    if not isinstance(envelope, Envelope):
        raise TypeError("envelope must be an Envelope")
    if not isinstance(envelope.proof, bytes) or len(envelope.proof) != params.proof_bytes:
        raise ValueError("proof has the wrong length for this parameter set")
    _require_digest("session_challenge", envelope.session_challenge)
    if envelope.parameter_id != params.parameter_id:
        raise ValueError("envelope header fields do not match this parameter set")
    header = _ENVELOPE_HEADER.pack(
        ENVELOPE_MAGIC, ENVELOPE_VERSION, envelope.parameter_id, envelope.session_challenge
    )
    return header + envelope.commitment.to_bytes(params) + envelope.proof


def decode_envelope(params: BdlopParams, data: bytes) -> Envelope:
    """Parse a fixed-size envelope; reject every deviation from the layout."""
    if not isinstance(data, bytes) or len(data) != envelope_size(params):
        raise ValueError("envelope has the wrong length for this parameter set")
    magic, version, parameter_id, session_challenge = _ENVELOPE_HEADER.unpack_from(data)
    if magic != ENVELOPE_MAGIC or version != ENVELOPE_VERSION:
        raise ValueError("envelope magic or version is unsupported")
    if not hmac.compare_digest(parameter_id, params.parameter_id):
        raise ValueError("envelope parameter set differs from the verifier pin")
    split = _ENVELOPE_HEADER.size + params.commitment_bytes
    commitment = bdlop.Commitment.from_bytes(params, data[_ENVELOPE_HEADER.size:split])
    return Envelope(parameter_id, session_challenge, commitment, data[split:])


def _require_statement(params: BdlopParams, statement: object) -> VideoStatement:
    if not isinstance(statement, VideoStatement):
        raise TypeError("statement must be a VideoStatement")
    if statement.parameter_id != params.parameter_id:
        raise ValueError("statement is bound to a different parameter set")
    return statement


def _statement_matches(params: BdlopParams, statement: object) -> bool:
    return isinstance(statement, VideoStatement) and statement.parameter_id == params.parameter_id


def placeholder_envelope(params: BdlopParams, *, registered: bool = False) -> bytes:
    """Same-length stand-in used to fix the carrier layout before proving."""
    return bytes(envelope_size(params, registered=registered))


def create_envelope(
    params: BdlopParams, statement: VideoStatement, payload: bytes
) -> tuple[bytes, PayloadOpening]:
    """Commit to ``payload`` and prove knowledge of its opening for ``statement``."""
    _require_statement(params, statement)
    message = codec.encode_payload(params, payload)
    randomness = bdlop.sample_randomness(params)
    commitment = bdlop.commit(params, message, randomness)
    proof = opening_proof.prove(params, statement.to_bytes(), commitment, randomness)
    envelope = Envelope(params.parameter_id, statement.session_challenge, commitment, proof)
    return encode_envelope(params, envelope), PayloadOpening(payload, randomness)


def verify_envelope(params: BdlopParams, statement: VideoStatement, data: bytes) -> bool:
    """Verify an extracted envelope against a verifier-built statement."""
    try:
        envelope = decode_envelope(params, data)
    except ValueError:
        return False
    if not _statement_matches(params, statement):
        return False
    if not hmac.compare_digest(envelope.session_challenge, statement.session_challenge):
        return False
    return opening_proof.verify(params, statement.to_bytes(), envelope.commitment, envelope.proof)


def verify_disclosure(params: BdlopParams, data: bytes, opening: PayloadOpening) -> bool:
    """Check a later disclosure of the committed payload against an envelope."""
    if not isinstance(opening, PayloadOpening):
        return False
    try:
        envelope = decode_envelope(params, data)
        message = codec.encode_payload(params, opening.payload)
    except ValueError:
        return False
    return bdlop.verify_opening(params, envelope.commitment, message, opening.randomness)


def create_registered_envelope(
    params: BdlopParams, statement: VideoStatement,
    commitment: bdlop.Commitment, randomness: np.ndarray,
) -> bytes:
    """Prove knowledge of the opening of a registry-pinned commitment.

    The envelope carries only the proof.  Because the commitment is fixed by
    the issuer-signed registry, the proof also authenticates its holder.
    """
    _require_statement(params, statement)
    proof = opening_proof.prove(params, statement.to_bytes(), commitment, randomness)
    header = _ENVELOPE_HEADER.pack(
        REGISTERED_ENVELOPE_MAGIC, ENVELOPE_VERSION, params.parameter_id, statement.session_challenge
    )
    return header + proof


def envelope_session(params: BdlopParams, data: bytes, *, registered: bool = False) -> bytes:
    """Read the untrusted in-band session field after checking the framing."""
    if not isinstance(data, bytes) or len(data) != envelope_size(params, registered=registered):
        raise ValueError("envelope has the wrong length for this parameter set")
    magic, version, parameter_id, session_challenge = _ENVELOPE_HEADER.unpack_from(data)
    expected_magic = REGISTERED_ENVELOPE_MAGIC if registered else ENVELOPE_MAGIC
    if magic != expected_magic or version != ENVELOPE_VERSION:
        raise ValueError("envelope magic or version is unsupported")
    if not hmac.compare_digest(parameter_id, params.parameter_id):
        raise ValueError("envelope parameter set differs from the verifier pin")
    return session_challenge


def verify_registered_envelope(
    params: BdlopParams, statement: VideoStatement, commitment: bdlop.Commitment, data: bytes
) -> bool:
    """Verify a proof-only envelope against the verifier's pinned commitment."""
    try:
        session_challenge = envelope_session(params, data, registered=True)
    except ValueError:
        return False
    if not _statement_matches(params, statement):
        return False
    if not hmac.compare_digest(session_challenge, statement.session_challenge):
        return False
    proof = data[_ENVELOPE_HEADER.size:]
    return opening_proof.verify(params, statement.to_bytes(), commitment, proof)
