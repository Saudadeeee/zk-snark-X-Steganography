"""Video-bound statement and fixed-size in-band envelope for the BDLOP proof.

The verifier builds :class:`VideoStatement` only from its own pins and from
values it derives from the received H.264 stream.  The envelope carries the
commitment and the proof; it never carries the payload, the randomness, or
anything the verifier is expected to trust.

A payload is disclosed later with :func:`create_disclosure`: the holder reveals
the payload and an equality proof that the carried commitment hides it, bound
to a recipient-chosen nonce.  The commitment randomness never leaves the
holder, so the recipient cannot prove anything about the commitment afterwards.

An in-band envelope may carry one *attachment*: a payload range proof
(:mod:`payload_range_proof`) showing that the commitment hides
``encode_payload(p)`` for a payload ``p`` of a public, verifier-pinned length.
The attachment is bound to the same video statement, so it cannot be moved to
another video or session.  The pinned length is public by design; holders hide
the true length by padding to a length class (:func:`pad_payload`).
"""

from __future__ import annotations

import hashlib
import hmac
import struct
from dataclasses import dataclass

import numpy as np

from . import bdlop, codec, equality_proof, opening_proof, payload_range_proof
from .params import BdlopParams
from .payload_range_proof import PayloadRangeParams

STATEMENT_VERSION = 1
ENVELOPE_MAGIC = b"ZKLB"
REGISTERED_ENVELOPE_MAGIC = b"ZKLR"
ENVELOPE_VERSION = 1
# Version 2 = version 1 followed by one attachment: ``type || u16 length || proof``.
ATTACHED_ENVELOPE_VERSION = 2
ATTACHMENT_PAYLOAD_RANGE = 1
_ATTACHMENT_HEADER = struct.Struct(">BH")
_RANGE_ATTACHMENT_DOMAIN = b"zkstego/lattice-zk/envelope-attachment/payload-range/v1\0"
PAD_MARKER = 0x80
_STATEMENT_DOMAIN = b"zkstego/lattice-zk/video-statement/v1\0"
_VIDEO_COMMITMENT_DOMAIN = b"zkstego/video-zk/video-commitment/v1\0"
_ENVELOPE_HEADER = struct.Struct(">4sB32s32s")
DISCLOSURE_MAGIC = b"ZKLD"
DISCLOSURE_VERSION = 1
DISCLOSURE_NONCE_BYTES = 32
_DISCLOSURE_DOMAIN = b"zkstego/lattice-zk/disclosure/v1\0"
_DISCLOSURE_HEADER = struct.Struct(">4sB32sH")
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


def require_verifier_parameters(params: object, *, allow_toy_parameters: bool = False) -> BdlopParams:
    """Refuse a parameter set below production strength unless a test opts in (Q12).

    Production strength is a challenge space of at least 2^256
    (:meth:`BdlopParams.require_production_strength`).  Every application-level
    verifier calls this before it looks at any proof, so a hand-built
    :class:`VerifierPins` with the ``TOY`` set no longer accepts toy proofs.
    The proof primitives (``opening_proof.verify`` and friends) stay
    parameter-agnostic building blocks.  Raises ``ValueError`` (verifier
    misconfiguration), never returns ``False``.
    """
    if not isinstance(params, BdlopParams):
        raise TypeError("params must be a BdlopParams set")
    if not isinstance(allow_toy_parameters, bool):
        raise TypeError("allow_toy_parameters must be a bool")
    if not allow_toy_parameters:
        try:
            params.require_production_strength()
        except ValueError as error:
            raise ValueError(
                f"parameter set {params.name!r} is below production strength ({error}); "
                "verifiers refuse it unless allow_toy_parameters=True"
            ) from None
    return params


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
    """Prover-private opening; never hand it over.

    Whoever holds ``randomness`` can prove knowledge of the opening for new
    statements, i.e. make accepted videos with this commitment.  Reveal the
    payload with :func:`create_disclosure` instead.
    """

    payload: bytes
    randomness: np.ndarray


@dataclass(frozen=True)
class Envelope:
    parameter_id: bytes
    session_challenge: bytes
    commitment: bdlop.Commitment
    proof: bytes
    # Payload range proof when the envelope carries that attachment.
    attachment_proof: bytes | None = None


@dataclass(frozen=True)
class PayloadRangeAttachment:
    """Verifier-pinned attachment: the payload has exactly ``payload_length`` bytes."""

    params: PayloadRangeParams
    payload_length: int

    def __post_init__(self) -> None:
        if not isinstance(self.params, PayloadRangeParams):
            raise TypeError("attachment params must be a PayloadRangeParams set")
        if not isinstance(self.payload_length, int) or isinstance(self.payload_length, bool):
            raise TypeError("payload_length must be an int")
        if not 0 <= self.payload_length <= self.params.max_payload_bytes:
            raise ValueError("payload_length is outside the range the proof supports")

    def requires_base(self, params: BdlopParams) -> None:
        if self.params.base.parameter_id != params.parameter_id:
            raise ValueError("payload range parameters are not built on this parameter set")

    @property
    def proof_bytes(self) -> int:
        return self.params.proof_bytes(self.payload_length)

    @property
    def size(self) -> int:
        return _ATTACHMENT_HEADER.size + self.proof_bytes

    def descriptor(self) -> dict[str, object]:
        """Pinned description hashed into a carrier profile id."""
        return {
            "type": "payload-range",
            "parameter_id": self.params.parameter_id.hex(),
            "payload_length": self.payload_length,
        }


def payload_range_params_for(params: BdlopParams) -> PayloadRangeParams:
    """The payload range parameter set built on ``params``."""
    for candidate in (
        payload_range_proof.PAYLOAD_RANGE_128_V2, payload_range_proof.PAYLOAD_RANGE_128_V1,
        payload_range_proof.PAYLOAD_RANGE_TOY,
    ):
        if candidate.base.parameter_id == params.parameter_id:
            return candidate
    raise ValueError(f"no payload range parameter set is built on {params.name!r}")


def payload_range_attachment(params: BdlopParams, payload_length: int) -> PayloadRangeAttachment:
    return PayloadRangeAttachment(payload_range_params_for(params), payload_length)


def pad_payload(payload: bytes, length: int) -> bytes:
    """Pad to a length class: ``payload || 0x80 || 0x00...``; needs one spare byte."""
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    if not isinstance(length, int) or isinstance(length, bool) or length < 1:
        raise ValueError("length must be a positive int")
    if len(payload) >= length:
        raise ValueError("payload must be shorter than the length class (one byte for the marker)")
    return payload + bytes([PAD_MARKER]) + bytes(length - len(payload) - 1)


def unpad_payload(padded: bytes) -> bytes:
    """Inverse of :func:`pad_payload`; rejects anything that is not its output."""
    if not isinstance(padded, bytes):
        raise TypeError("padded payload must be bytes")
    stripped = padded.rstrip(b"\x00")
    if not stripped or stripped[-1] != PAD_MARKER:
        raise ValueError("payload padding is malformed")
    return stripped[:-1]


def video_commitment(canonical_video_sha256: bytes) -> bytes:
    """Domain-separate the carrier-normalized H.264 digest."""
    if not isinstance(canonical_video_sha256, bytes) or len(canonical_video_sha256) != 32:
        raise ValueError("canonical video digest must be exactly 32 bytes")
    return hashlib.sha256(_VIDEO_COMMITMENT_DOMAIN + canonical_video_sha256).digest()


def envelope_size(
    params: BdlopParams, *, registered: bool = False,
    attachment: PayloadRangeAttachment | None = None,
) -> int:
    """Wire size; a registered commitment is pinned, not carried in the video."""
    carried = 0 if registered else params.commitment_bytes
    size = _ENVELOPE_HEADER.size + carried + params.proof_bytes
    if attachment is not None:
        if registered:
            raise ValueError("a registered envelope carries no attachment")
        attachment.requires_base(params)
        size += attachment.size
    return size


def _envelope_version(attachment: PayloadRangeAttachment | None) -> int:
    return ENVELOPE_VERSION if attachment is None else ATTACHED_ENVELOPE_VERSION


def _range_statement(statement: VideoStatement) -> bytes:
    """Statement the attached range proof is bound to: the video statement itself."""
    return _RANGE_ATTACHMENT_DOMAIN + statement.to_bytes()


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


def encode_envelope(
    params: BdlopParams, envelope: Envelope, attachment: PayloadRangeAttachment | None = None,
) -> bytes:
    if not isinstance(envelope, Envelope):
        raise TypeError("envelope must be an Envelope")
    if not isinstance(envelope.proof, bytes) or len(envelope.proof) != params.proof_bytes:
        raise ValueError("proof has the wrong length for this parameter set")
    _require_digest("session_challenge", envelope.session_challenge)
    if envelope.parameter_id != params.parameter_id:
        raise ValueError("envelope header fields do not match this parameter set")
    if (attachment is None) != (envelope.attachment_proof is None):
        raise ValueError("envelope and attachment specification disagree")
    header = _ENVELOPE_HEADER.pack(
        ENVELOPE_MAGIC, _envelope_version(attachment), envelope.parameter_id, envelope.session_challenge
    )
    data = header + envelope.commitment.to_bytes(params) + envelope.proof
    if attachment is not None:
        attachment.requires_base(params)
        proof = envelope.attachment_proof
        if not isinstance(proof, bytes) or len(proof) != attachment.proof_bytes:
            raise ValueError("attached range proof has the wrong length for this attachment")
        data += _ATTACHMENT_HEADER.pack(ATTACHMENT_PAYLOAD_RANGE, attachment.payload_length) + proof
    return data


def decode_envelope(
    params: BdlopParams, data: bytes, attachment: PayloadRangeAttachment | None = None,
) -> Envelope:
    """Parse a fixed-size envelope; reject every deviation from the layout.

    ``attachment`` is the verifier-pinned attachment specification: an
    envelope with a different version, attachment type or payload length is
    rejected, so nothing about the attachment is read from the video.
    """
    if not isinstance(data, bytes) or len(data) != envelope_size(params, attachment=attachment):
        raise ValueError("envelope has the wrong length for this parameter set")
    magic, version, parameter_id, session_challenge = _ENVELOPE_HEADER.unpack_from(data)
    if magic != ENVELOPE_MAGIC or version != _envelope_version(attachment):
        raise ValueError("envelope magic or version is unsupported")
    if not hmac.compare_digest(parameter_id, params.parameter_id):
        raise ValueError("envelope parameter set differs from the verifier pin")
    split = _ENVELOPE_HEADER.size + params.commitment_bytes
    commitment = bdlop.Commitment.from_bytes(params, data[_ENVELOPE_HEADER.size:split])
    end = split + params.proof_bytes
    if attachment is None:
        return Envelope(parameter_id, session_challenge, commitment, data[split:end])
    kind, length = _ATTACHMENT_HEADER.unpack_from(data, end)
    if kind != ATTACHMENT_PAYLOAD_RANGE or length != attachment.payload_length:
        raise ValueError("envelope attachment differs from the verifier pin")
    proof = data[end + _ATTACHMENT_HEADER.size:]
    return Envelope(parameter_id, session_challenge, commitment, data[split:end], proof)


def _require_statement(params: BdlopParams, statement: object) -> VideoStatement:
    if not isinstance(statement, VideoStatement):
        raise TypeError("statement must be a VideoStatement")
    if statement.parameter_id != params.parameter_id:
        raise ValueError("statement is bound to a different parameter set")
    return statement


def _statement_matches(params: BdlopParams, statement: object) -> bool:
    return isinstance(statement, VideoStatement) and statement.parameter_id == params.parameter_id


def placeholder_envelope(
    params: BdlopParams, *, registered: bool = False,
    attachment: PayloadRangeAttachment | None = None,
) -> bytes:
    """Same-length stand-in used to fix the carrier layout before proving."""
    return bytes(envelope_size(params, registered=registered, attachment=attachment))


def create_envelope(
    params: BdlopParams, statement: VideoStatement, payload: bytes,
    *, attachment: PayloadRangeAttachment | None = None,
) -> tuple[bytes, PayloadOpening]:
    """Commit to ``payload`` and prove knowledge of its opening for ``statement``.

    With ``attachment`` the payload must have exactly the pinned length and the
    envelope also carries a range proof bound to the same statement.
    """
    _require_statement(params, statement)
    if attachment is not None:
        attachment.requires_base(params)
        if not isinstance(payload, bytes) or len(payload) != attachment.payload_length:
            raise ValueError("payload length differs from the pinned attachment length")
    message = codec.encode_payload(params, payload)
    randomness = bdlop.sample_randomness(params)
    commitment = bdlop.commit(params, message, randomness)
    proof = opening_proof.prove(params, statement.to_bytes(), commitment, randomness)
    range_proof = None
    if attachment is not None:
        range_proof = payload_range_proof.prove(
            attachment.params, _range_statement(statement), commitment, payload, randomness
        )
    envelope = Envelope(params.parameter_id, statement.session_challenge, commitment, proof, range_proof)
    return encode_envelope(params, envelope, attachment), PayloadOpening(payload, randomness)


def verify_envelope(
    params: BdlopParams, statement: VideoStatement, data: bytes,
    *, allow_toy_parameters: bool = False, attachment: PayloadRangeAttachment | None = None,
) -> bool:
    """Verify an extracted envelope against a verifier-built statement.

    With ``attachment`` the envelope must also carry a range proof for the
    pinned payload length that verifies against the same statement.  Raises
    ``ValueError`` for a non-production parameter set unless
    ``allow_toy_parameters`` is set; malformed input returns ``False``.
    """
    require_verifier_parameters(params, allow_toy_parameters=allow_toy_parameters)
    try:
        envelope = decode_envelope(params, data, attachment)
    except ValueError:
        return False
    if not _statement_matches(params, statement):
        return False
    if not hmac.compare_digest(envelope.session_challenge, statement.session_challenge):
        return False
    if not opening_proof.verify(params, statement.to_bytes(), envelope.commitment, envelope.proof):
        return False
    if attachment is None:
        return True
    return payload_range_proof.verify(
        attachment.params, _range_statement(statement), envelope.commitment,
        attachment.payload_length, envelope.attachment_proof,
    )


def self_check_opening(
    params: BdlopParams, data: bytes, opening: PayloadOpening,
    attachment: PayloadRangeAttachment | None = None,
) -> bool:
    """Holder-side check that ``opening`` opens the commitment in an envelope.

    This needs the randomness, so it is not a disclosure protocol: a party that
    receives ``opening`` can afterwards prove knowledge of the opening for new
    statements.  Use it only on the holder's own data; disclose with
    :func:`create_disclosure`.
    """
    if not isinstance(opening, PayloadOpening):
        return False
    try:
        envelope = decode_envelope(params, data, attachment)
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


def envelope_session(
    params: BdlopParams, data: bytes, *, registered: bool = False,
    attachment: PayloadRangeAttachment | None = None,
) -> bytes:
    """Read the untrusted in-band session field after checking the framing."""
    expected_size = envelope_size(params, registered=registered, attachment=attachment)
    if not isinstance(data, bytes) or len(data) != expected_size:
        raise ValueError("envelope has the wrong length for this parameter set")
    magic, version, parameter_id, session_challenge = _ENVELOPE_HEADER.unpack_from(data)
    expected_magic = REGISTERED_ENVELOPE_MAGIC if registered else ENVELOPE_MAGIC
    if magic != expected_magic or version != _envelope_version(attachment):
        raise ValueError("envelope magic or version is unsupported")
    if not hmac.compare_digest(parameter_id, params.parameter_id):
        raise ValueError("envelope parameter set differs from the verifier pin")
    return session_challenge


def verify_registered_envelope(
    params: BdlopParams, statement: VideoStatement, commitment: bdlop.Commitment, data: bytes,
    *, allow_toy_parameters: bool = False,
) -> bool:
    """Verify a proof-only envelope against the verifier's pinned commitment.

    Raises ``ValueError`` for a non-production parameter set unless
    ``allow_toy_parameters`` is set; malformed input returns ``False``.
    """
    require_verifier_parameters(params, allow_toy_parameters=allow_toy_parameters)
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


# -- zero-knowledge payload disclosure ------------------------------------ #

@dataclass(frozen=True)
class Disclosure:
    """Revealed payload plus an equality proof; contains no randomness."""

    payload: bytes
    proof: bytes


def disclosure_context(params: BdlopParams, statement_id: bytes, nonce: bytes) -> bytes:
    """Domain-separated, length-prefixed context a disclosure proof is bound to.

    ``statement_id`` names what is disclosed (the verified video statement for
    an envelope, or e.g. the relation id for a registered credential);
    ``nonce`` is chosen by the recipient, so an old disclosure cannot be
    replayed to them.
    """
    _require_digest("statement_id", statement_id)
    if not isinstance(nonce, bytes) or len(nonce) != DISCLOSURE_NONCE_BYTES:
        raise ValueError(f"disclosure nonce must be exactly {DISCLOSURE_NONCE_BYTES} bytes")
    encoded = _DISCLOSURE_DOMAIN + params.parameter_id
    for item in (statement_id, nonce):
        encoded += struct.pack(">Q", len(item)) + item
    return encoded


def _public_commitment(params: BdlopParams, payload: bytes) -> tuple[bdlop.Commitment, np.ndarray]:
    """``Com(encode(payload); 0) = (0, encode(payload))`` and its zero opening."""
    zero = np.zeros((params.width, params.degree), dtype=np.int64)
    return bdlop.commit(params, codec.encode_payload(params, payload), zero), zero


def encode_disclosure(params: BdlopParams, disclosure: Disclosure) -> bytes:
    """``"ZKLD" || 0x01 || parameter_id || u16 len || payload || proof``."""
    if not isinstance(disclosure, Disclosure) or not isinstance(disclosure.payload, bytes):
        raise TypeError("disclosure must be a Disclosure with a bytes payload")
    if len(disclosure.payload) > params.max_payload_bytes:
        raise ValueError("payload does not fit the message polynomial")
    proof = disclosure.proof
    if not isinstance(proof, bytes) or len(proof) != equality_proof.proof_bytes(params):
        raise ValueError("disclosure proof has the wrong length for this parameter set")
    header = _DISCLOSURE_HEADER.pack(
        DISCLOSURE_MAGIC, DISCLOSURE_VERSION, params.parameter_id, len(disclosure.payload)
    )
    return header + disclosure.payload + proof


def decode_disclosure(params: BdlopParams, data: bytes) -> Disclosure:
    """Parse a disclosure; reject every deviation from the layout."""
    if not isinstance(data, bytes) or len(data) < _DISCLOSURE_HEADER.size:
        raise ValueError("disclosure is truncated")
    magic, version, parameter_id, length = _DISCLOSURE_HEADER.unpack_from(data)
    if magic != DISCLOSURE_MAGIC or version != DISCLOSURE_VERSION:
        raise ValueError("disclosure magic or version is unsupported")
    if not hmac.compare_digest(parameter_id, params.parameter_id):
        raise ValueError("disclosure parameter set differs from the verifier pin")
    if length > params.max_payload_bytes:
        raise ValueError("disclosed payload does not fit the message polynomial")
    split = _DISCLOSURE_HEADER.size + length
    if len(data) != split + equality_proof.proof_bytes(params):
        raise ValueError("disclosure has the wrong length")
    return Disclosure(data[_DISCLOSURE_HEADER.size:split], data[split:])


def create_commitment_disclosure(
    params: BdlopParams, commitment: bdlop.Commitment, opening: PayloadOpening,
    *, statement_id: bytes, nonce: bytes,
) -> bytes:
    """Reveal the payload of ``commitment`` with a proof; ``opening`` stays private.

    The proof is an equality proof between ``commitment`` and the
    deterministic ``Com(encode(payload); 0)``.  Raises ``ValueError`` if
    ``opening`` does not open ``commitment``.
    """
    if not isinstance(opening, PayloadOpening):
        raise TypeError("opening must be a PayloadOpening")
    context = disclosure_context(params, statement_id, nonce)
    public, zero = _public_commitment(params, opening.payload)
    proof = equality_proof.prove(params, context, commitment, opening.randomness, public, zero)
    return encode_disclosure(params, Disclosure(opening.payload, proof))


def verify_commitment_disclosure(
    params: BdlopParams, commitment: bdlop.Commitment, data: bytes,
    *, statement_id: bytes, nonce: bytes, allow_toy_parameters: bool = False,
) -> bool:
    """Accept iff ``data`` proves that ``commitment`` hides its disclosed payload.

    ``statement_id`` and ``nonce`` are the recipient's own values, never read
    from ``data``.  Read the payload with :func:`decode_disclosure` after
    acceptance.  Malformed input returns ``False``; a non-production
    parameter set raises ``ValueError`` unless ``allow_toy_parameters``.
    """
    require_verifier_parameters(params, allow_toy_parameters=allow_toy_parameters)
    try:
        disclosure = decode_disclosure(params, data)
        context = disclosure_context(params, statement_id, nonce)
        public, _ = _public_commitment(params, disclosure.payload)
    except (TypeError, ValueError):
        return False
    return equality_proof.verify(params, context, commitment, public, disclosure.proof)


def create_disclosure(
    params: BdlopParams, envelope: bytes, opening: PayloadOpening,
    *, statement_id: bytes, nonce: bytes, attachment: PayloadRangeAttachment | None = None,
) -> bytes:
    """Disclose the payload committed in an in-band envelope to one recipient."""
    commitment = decode_envelope(params, envelope, attachment).commitment
    return create_commitment_disclosure(
        params, commitment, opening, statement_id=statement_id, nonce=nonce
    )


def verify_disclosure_proof(
    params: BdlopParams, envelope: bytes, data: bytes, *, statement_id: bytes, nonce: bytes,
    allow_toy_parameters: bool = False, attachment: PayloadRangeAttachment | None = None,
) -> bool:
    """Verify a disclosure against a verified in-band envelope."""
    require_verifier_parameters(params, allow_toy_parameters=allow_toy_parameters)
    try:
        commitment = decode_envelope(params, envelope, attachment).commitment
    except ValueError:
        return False
    return verify_commitment_disclosure(
        params, commitment, data, statement_id=statement_id, nonce=nonce,
        allow_toy_parameters=allow_toy_parameters,
    )
