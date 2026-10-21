"""Embed a BDLOP proof envelope in H.264 CAVLC carriers and verify it blind.

The verifier needs the stego video, its pinned configuration (parameter set,
signed relation registry, carrier contract, sync key) and its own session
state.  It uses no sidecar, cover video, or prover-supplied position list.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import struct
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from ..transport import gop_policy as gop_policies
from ..transport import video_canonicalization as canonicalization
from ..transport.adaptive_chunks import AdaptiveChunkPlan
from ..registry.zkp_registry import BDLOP_OPEN_ZKP_SUITE, RelationRecord, SignedZkpRelationRegistry
from ..registry.zkp_sessions import SessionChallengeStore
from . import bdlop, video_proof
from .params import BdlopParams
from .video_proof import PayloadOpening, VerifierPins

_DOMAIN = b"zkstego/lattice-zk/video-pipeline/v1/"
# Codec policies name the canonical-digest scope a statement binds (D5).  The
# v1 string and its identifier are unchanged, so existing videos, registries
# and statements keep verifying; v2 is opt-in per carrier profile.
CODEC_POLICY_V1 = "h264-baseline-cavlc/canonical-h264-carrier-normalized-sha256-v1"
CODEC_POLICY_V2 = (
    "h264-baseline-cavlc/canonical-h264-carrier-normalized-sha256-v2"
    "/full-rbsp/tagged-raw-segments/segmentation=" + canonicalization.SEGMENTATION_RULE_V2
)
CODEC_POLICY = CODEC_POLICY_V1
CODEC_POLICIES = {
    CODEC_POLICY_V1: canonicalization.DIGEST_V1,
    CODEC_POLICY_V2: canonicalization.DIGEST_V2,
}
CONSTRAINT_MODULE = "bdlop-open-v1: knowledge of a relaxed opening of the in-band commitment"
REGISTERED_CONSTRAINT_MODULE = (
    "bdlop-open-v1: knowledge of a relaxed opening of the registered commitment"
)
DEFAULT_FRAMES_PER_SEGMENT = 100
DEFAULT_CHUNK_BYTES = 1_250
MAX_HOLDER_ID_BYTES = 256

ProgressCallback = Callable[[dict[str, Any]], None]


class Transport(Protocol):
    """Blind carrier channel; ``src.transport.blind_sync_streaming`` is the real one."""

    def derive_chunked_video_context(self, video_path, chunks, sync_key, contract, **options): ...

    def embed_chunked_video_payload(self, cover, output, payload, sync_key, contract, **options): ...

    def extract_chunked_video_payload(self, video_path, sync_key, contract, **options): ...


class AdaptiveTransport(Protocol):
    """Capacity-adaptive channel; ``src.transport.blind_sync_adaptive`` is the real one."""

    def derive_adaptive_video_context(self, video_path, payload, sync_key, contract, *, plan,
                                      **options): ...

    def embed_adaptive_video_payload(self, cover, output, payload, sync_key, contract, *, plan,
                                     expected_layout=None, **options): ...

    def extract_adaptive_video_payload(self, video_path, sync_key, contract, *, plan,
                                       payload_bytes=None, **options): ...


@dataclass(frozen=True)
class CarrierProfile:
    """Verifier-pinned transport configuration that fixes carrier placement."""

    contract: Any
    frames_per_segment: int = DEFAULT_FRAMES_PER_SEGMENT
    chunk_bytes: int = DEFAULT_CHUNK_BYTES
    # True: the commitment is pinned by the registry and the video carries only the proof.
    registered: bool = False
    # Slice structure the transport accepts (``src.transport.gop_policy``). GOP > 1
    # streams need ``IDR_CARRIERS_INTER_RAW``; the default stays all-intra.
    gop_policy: str = gop_policies.ALL_INTRA
    # Canonical-digest scope (D5); ``CODEC_POLICY_V2`` binds the full RBSP of
    # carrier NAL units, tags raw segments and pins the segmentation rule.
    codec_policy: str = CODEC_POLICY_V1
    # Opt-in capacity-adaptive ZKBC v2 transport (docs/ADAPTIVE_CHUNKING.md).
    # ``None`` keeps the fixed ``chunk_bytes`` ZKBC v1 transport and its ids.
    chunk_plan: AdaptiveChunkPlan | None = None

    def __post_init__(self) -> None:
        gop_policies.require_policy(self.gop_policy)
        require_codec_policy(self.codec_policy)
        if self.chunk_plan is not None:
            if not isinstance(self.chunk_plan, AdaptiveChunkPlan):
                raise ValueError("chunk_plan must be an AdaptiveChunkPlan")
            if self.chunk_bytes != DEFAULT_CHUNK_BYTES:
                raise ValueError("an adaptive chunk plan replaces chunk_bytes; leave it at the default")

    @property
    def digest_policy(self) -> str:
        return CODEC_POLICIES[self.codec_policy]

    def profile_id(self, params: BdlopParams) -> bytes:
        description: dict[str, Any] = {
            "contract": dataclasses.asdict(self.contract),
            "frames_per_segment": self.frames_per_segment,
            "chunk_bytes": self.chunk_bytes,
            "envelope_bytes": video_proof.envelope_size(params, registered=self.registered),
            "registered": self.registered,
        }
        # Omitted for the default so all-intra profiles keep their identifiers;
        # any other policy gives a different profile, policy hash and statement.
        if self.gop_policy != gop_policies.ALL_INTRA:
            description["gop_policy"] = self.gop_policy
        # Same rule for the codec policy: v1 profiles keep their identifiers.
        if self.codec_policy != CODEC_POLICY_V1:
            description["codec_policy"] = self.codec_policy
        # Likewise only adaptive profiles carry a plan, which replaces the
        # fixed chunk size: different plan parameters, different profile.
        if self.chunk_plan is not None:
            del description["chunk_bytes"]
            description["chunk_plan"] = self.chunk_plan.descriptor()
        encoded = json.dumps(description, sort_keys=True, separators=(",", ":")).encode("ascii")
        return hashlib.sha256(_DOMAIN + b"carrier-profile\0" + encoded).digest()

    def options(self) -> dict[str, Any]:
        options: dict[str, Any] = {"frames_per_segment": self.frames_per_segment}
        if self.gop_policy != gop_policies.ALL_INTRA:
            options["gop_policy"] = self.gop_policy
        if self.codec_policy != CODEC_POLICY_V1:
            options["digest_policy"] = self.digest_policy
        return options


@dataclass(frozen=True)
class Credential:
    """Holder's registered commitment and its private opening randomness."""

    commitment: bdlop.Commitment
    randomness: Any


@dataclass(frozen=True)
class EmbedResult:
    statement_id: bytes
    opening: PayloadOpening | None
    envelope_bytes: int
    carriers_used: int
    segments_used: int
    # Adaptive profiles only: per-segment capacities and (segment, bytes) chunks.
    segment_capacity_bits: tuple[int, ...] = ()
    chunk_layout: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class VerifyResult:
    valid: bool
    reason: str
    statement_id: bytes | None = None
    carriers_used: int = 0
    # Verified in-band envelope; lets a caller check later linkage or disclosure.
    envelope: bytes | None = None


def require_codec_policy(codec_policy: str) -> str:
    if codec_policy not in CODEC_POLICIES:
        raise ValueError(f"unknown codec policy {codec_policy!r}; expected one of {tuple(CODEC_POLICIES)}")
    return codec_policy


def codec_policy_id(codec_policy: str = CODEC_POLICY_V1) -> bytes:
    """Identifier of a codec policy; the default is the unchanged v1 identifier."""
    require_codec_policy(codec_policy)
    return hashlib.sha256(_DOMAIN + b"codec-policy\0" + codec_policy.encode("ascii")).digest()


def policy_hash(params: BdlopParams, profile: CarrierProfile) -> str:
    """Registry policy digest: codec policy plus carrier profile."""
    return hashlib.sha256(
        _DOMAIN + b"policy\0" + codec_policy_id(profile.codec_policy) + profile.profile_id(params)
    ).hexdigest()


def holder_id_digest(holder_id: str) -> bytes:
    """Domain-separated digest of a holder identifier.

    The identifier is a non-empty NFC-normalized string of at most
    ``MAX_HOLDER_ID_BYTES`` UTF-8 bytes; anything else is refused, so one
    identity has exactly one encoding.
    """
    if not isinstance(holder_id, str) or not holder_id:
        raise ValueError("holder id must be a non-empty string")
    if not unicodedata.is_normalized("NFC", holder_id):
        raise ValueError("holder id must be NFC-normalized")
    try:
        encoded = holder_id.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("holder id must be valid Unicode text") from error
    if len(encoded) > MAX_HOLDER_ID_BYTES:
        raise ValueError(f"holder id must be at most {MAX_HOLDER_ID_BYTES} UTF-8 bytes")
    return hashlib.sha256(
        _DOMAIN + b"holder-id\0" + struct.pack(">H", len(encoded)) + encoded
    ).digest()


def relation_descriptor(
    params: BdlopParams, profile: CarrierProfile, credential: bdlop.Commitment | None = None,
    *, holder_id: str | None = None,
) -> dict[str, str]:
    """Descriptor an issuer signs into the relation registry for this backend.

    For a registered profile the issuer's signature also covers the holder's
    credential commitment, which is what makes the proof authenticate them.
    With ``holder_id`` it also covers "this commitment belongs to holder X":
    the identifier's digest is hashed into ``verifier_key_hash`` after the
    commitment, so the registry field set is unchanged and ``holder_id=None``
    gives the same descriptor as before.
    """
    if profile.registered != (credential is not None):
        raise ValueError("a credential commitment is required exactly for registered profiles")
    if holder_id is not None and credential is None:
        raise ValueError("a holder id can only be bound to a registered credential")
    key = bdlop.derive_key(params)
    key_bytes = key.b1_tail.astype(">u8").tobytes() + key.b2_tail.astype(">u8").tobytes()
    module = CONSTRAINT_MODULE
    if credential is not None:
        # Every part has a length fixed by ``params``, so the optional digest
        # at the end keeps the concatenation unambiguous.
        key_bytes += credential.to_bytes(params)
        if holder_id is not None:
            key_bytes += holder_id_digest(holder_id)
        module = REGISTERED_CONSTRAINT_MODULE
    return {
        "zkp_suite": BDLOP_OPEN_ZKP_SUITE,
        "constraint_module_hash": hashlib.sha256(module.encode("ascii")).hexdigest(),
        "verifier_key_hash": hashlib.sha256(key_bytes).hexdigest(),
        "parameter_set_hash": params.parameter_id.hex(),
        "policy_hash": policy_hash(params, profile),
    }


def relation_id(
    params: BdlopParams, profile: CarrierProfile, credential: bdlop.Commitment | None = None,
    *, holder_id: str | None = None,
) -> bytes:
    """Registry relation identifier of :func:`relation_descriptor`."""
    descriptor = relation_descriptor(params, profile, credential, holder_id=holder_id)
    return bytes.fromhex(RelationRecord.from_descriptor(descriptor).relation_id)


def pins_from_registry(
    registry: SignedZkpRelationRegistry, issuer_public_key: bytes,
    params: BdlopParams, profile: CarrierProfile, *, minimum_epoch: int,
    allow_toy_parameters: bool = False, credential: bdlop.Commitment | None = None,
    holder_id: str | None = None,
) -> VerifierPins:
    """Resolve verifier pins from an issuer-signed registry; fail closed.

    ``minimum_epoch`` is the verifier's rollback floor.  Parameter sets with a
    challenge space below 2^256 are refused unless a test opts in.  A
    credential registered with a holder id resolves only with that same id.
    """
    video_proof.require_verifier_parameters(params, allow_toy_parameters=allow_toy_parameters)
    if not registry.verify(issuer_public_key):
        raise ValueError("relation registry signature did not verify against the issuer key")
    if registry.epoch < minimum_epoch:
        raise ValueError("relation registry is older than the verifier minimum epoch")
    descriptor = relation_descriptor(params, profile, credential, holder_id=holder_id)
    matches = [record for record in registry.relations if record.descriptor() == descriptor]
    if len(matches) != 1:
        raise ValueError(
            "this parameter set, carrier profile, credential and holder id are not registered"
        )
    root, epoch = registry.resolve(
        matches[0].relation_id, BDLOP_OPEN_ZKP_SUITE, descriptor["policy_hash"]
    )
    return VerifierPins(
        relation_id=bytes.fromhex(matches[0].relation_id),
        registry_root=bytes.fromhex(root),
        registry_epoch=epoch,
        codec_policy_id=codec_policy_id(profile.codec_policy),
        carrier_profile_id=profile.profile_id(params),
    )


def session_binding(params: BdlopParams, pins: VerifierPins) -> bytes:
    """Digest a session store binds each challenge to."""
    return hashlib.sha256(
        _DOMAIN + b"session-binding\0" + params.parameter_id + pins.relation_id
        + pins.registry_root + pins.registry_epoch.to_bytes(8, "big")
        + pins.codec_policy_id + pins.carrier_profile_id
    ).digest()


def public_sync_key(params: BdlopParams, profile: CarrierProfile) -> bytes:
    """Carrier-ordering key derived only from public, registered configuration.

    Using it makes verification public: anyone holding the registry can find
    the envelope.  It also lets anyone who knows the scheme test a video for an
    envelope, so it gives up undetectability.  Proof soundness and zero
    knowledge do not depend on the ordering key either way.
    """
    return hashlib.sha256(
        _DOMAIN + b"public-carrier-order\0" + params.parameter_id + profile.profile_id(params)
    ).digest()


def _default_transport() -> Transport:
    from ..transport import blind_sync_streaming

    return blind_sync_streaming  # type: ignore[return-value]


def _default_adaptive_transport() -> AdaptiveTransport:
    from ..transport import blind_sync_adaptive

    return blind_sync_adaptive  # type: ignore[return-value]


def _canonical_adaptive_chunks(extracted: Any, plan: AdaptiveChunkPlan) -> tuple[bytes, ...]:
    """Recompute the plan from the extracted capacities; return its unique encoding.

    The capacities must end at the segment that completes the payload, so the
    transport cannot report extra, unbound segments.
    """
    from ..transport.adaptive_chunks import canonical_adaptive_chunks

    capacities = getattr(extracted, "segment_capacity_bits", None)
    if not isinstance(capacities, (tuple, list)) or not all(
        isinstance(value, int) and not isinstance(value, bool) for value in capacities
    ):
        raise ValueError("transport did not report per-segment capacities")
    chunks, layout = canonical_adaptive_chunks(extracted.payload, tuple(capacities), plan)
    if layout[-1].segment_index != len(capacities) - 1:
        raise ValueError("reported capacities extend beyond the adaptive plan")
    reported = getattr(extracted, "layout", None)
    if reported is not None and tuple(reported) != layout:
        raise ValueError("transport layout differs from the recomputed adaptive plan")
    return tuple(chunks)


def _chunks(payload: bytes, profile: CarrierProfile) -> list[bytes]:
    from ..transport.blind_payload_chunks import pack_payload_chunks

    return pack_payload_chunks(payload, chunk_size=profile.chunk_bytes)


def embed_video_proof(
    cover_path: str | Path, output_path: str | Path, payload: bytes | None, *,
    params: BdlopParams, pins: VerifierPins, profile: CarrierProfile,
    session_challenge: bytes, sync_key: bytes, credential: Credential | None = None,
    transport: Transport | None = None, progress_callback: ProgressCallback | None = None,
) -> EmbedResult:
    """Prove knowledge of the committed payload and embed the envelope in-band.

    Carrier positions are fixed from a same-length placeholder first, so the
    statement can bind them without depending on the proof bits.  An in-band
    profile commits to ``payload``; a registered profile proves ``credential``.
    """
    if profile.registered != (credential is not None) or profile.registered == (payload is not None):
        raise ValueError("supply a payload for in-band profiles or a credential for registered ones")
    plan = profile.chunk_plan
    if plan is None:
        channel = transport or _default_transport()
    else:
        channel = transport or _default_adaptive_transport()
    options = {**profile.options(), "progress_callback": progress_callback}
    placeholder_envelope = video_proof.placeholder_envelope(params, registered=profile.registered)
    if plan is None:
        placeholder = _chunks(placeholder_envelope, profile)
        context = channel.derive_chunked_video_context(
            cover_path, placeholder, sync_key, profile.contract, **options
        )
    else:
        # Positions depend only on the envelope length, which is fixed by params.
        context = channel.derive_adaptive_video_context(
            cover_path, placeholder_envelope, sync_key, profile.contract, plan=plan, **options
        )
    statement = video_proof.build_statement(
        params, pins, session_challenge,
        carrier_count=len(context.global_positions),
        positions_hash=bytes.fromhex(context.positions_hash),
        canonical_video_sha256=bytes.fromhex(context.canonical_video_sha256),
    )
    if credential is None:
        envelope, opening = video_proof.create_envelope(params, statement, payload)
    else:
        opening = None
        envelope = video_proof.create_registered_envelope(
            params, statement, credential.commitment, credential.randomness
        )
    if plan is not None:
        if len(envelope) != len(placeholder_envelope):
            raise RuntimeError("envelope changed the predetermined carrier layout")
        layout = tuple(context.layout)
        embedded = channel.embed_adaptive_video_payload(
            cover_path, output_path, envelope, sync_key, profile.contract,
            plan=plan, expected_layout=layout, **options,
        )
        return EmbedResult(
            statement_id=statement.statement_id,
            opening=opening,
            envelope_bytes=len(envelope),
            carriers_used=embedded.carriers_used,
            segments_used=embedded.segments_used,
            segment_capacity_bits=tuple(context.segment_capacity_bits),
            chunk_layout=tuple((slot.segment_index, slot.size) for slot in layout),
        )
    if [len(chunk) for chunk in _chunks(envelope, profile)] != [len(chunk) for chunk in placeholder]:
        raise RuntimeError("envelope changed the predetermined carrier layout")
    embedded = channel.embed_chunked_video_payload(
        cover_path, output_path, envelope, sync_key, profile.contract,
        chunk_size=profile.chunk_bytes, **options,
    )
    return EmbedResult(
        statement_id=statement.statement_id,
        opening=opening,
        envelope_bytes=len(envelope),
        carriers_used=embedded.carriers_used,
        segments_used=embedded.segments_used,
    )


def _require_verifier_configuration(
    params: BdlopParams, pins: VerifierPins, profile: CarrierProfile,
    session_store: SessionChallengeStore | None, expected_session: bytes | None,
    credential: bdlop.Commitment | None, holder_id: str | None,
    allow_toy_parameters: bool = False,
) -> None:
    """Reject verifier misconfiguration loudly; video content never reaches here."""
    # Q12: production strength is enforced here too, not only in pins_from_registry.
    video_proof.require_verifier_parameters(params, allow_toy_parameters=allow_toy_parameters)
    if (session_store is None) == (expected_session is None):
        raise ValueError("supply exactly one of session_store or expected_session")
    if expected_session is not None and (
        not isinstance(expected_session, bytes) or len(expected_session) != 32
    ):
        raise ValueError("expected_session must be exactly 32 bytes")
    if profile.registered != (credential is not None):
        raise ValueError("a pinned credential is required exactly for registered profiles")
    if credential is not None and not (
        isinstance(credential, bdlop.Commitment) and credential.is_canonical(params)
    ):
        raise ValueError("the pinned credential is not a canonical commitment for this parameter set")
    if not isinstance(pins, VerifierPins):
        raise ValueError("pins must be VerifierPins")
    # The statement binds pins.codec_policy_id; it must name the codec policy
    # whose digest scope this profile makes the transport compute.
    if not hmac.compare_digest(pins.codec_policy_id, codec_policy_id(profile.codec_policy)):
        raise ValueError("pinned codec policy does not match the carrier profile's codec policy")
    # The pins must name the relation of exactly this credential (and holder);
    # otherwise an unregistered credential would be verified under them.
    expected = relation_id(params, profile, credential, holder_id=holder_id)
    if not hmac.compare_digest(expected, pins.relation_id):
        raise ValueError(
            "pinned relation id does not match this parameter set, profile, credential and holder id"
        )


def verify_video_proof(
    video_path: str | Path, *,
    params: BdlopParams, pins: VerifierPins, profile: CarrierProfile, sync_key: bytes,
    session_store: SessionChallengeStore | None = None, expected_session: bytes | None = None,
    credential: bdlop.Commitment | None = None, holder_id: str | None = None,
    transport: Transport | None = None, progress_callback: ProgressCallback | None = None,
    allow_toy_parameters: bool = False,
) -> VerifyResult:
    """Blind-extract the envelope and verify it against a verifier-built statement.

    Exactly one of ``session_store`` (one-use, replay-protected) or
    ``expected_session`` (stateless; no replay protection) must be supplied.

    Raises ``ValueError`` on verifier misconfiguration, before reading the
    video: in particular when ``pins.relation_id`` is not the relation of
    ``(params, profile, credential, holder_id)``, e.g. pins resolved for one
    credential used with another, or in-band pins used for a registered
    profile and vice versa, and for a parameter set below production strength
    (challenge space < 2^256) unless ``allow_toy_parameters=True``.  Video
    content only ever yields ``valid=False``.
    """
    _require_verifier_configuration(
        params, pins, profile, session_store, expected_session, credential, holder_id,
        allow_toy_parameters,
    )
    plan = profile.chunk_plan
    try:
        if plan is None:
            channel = transport or _default_transport()
            extracted = channel.extract_chunked_video_payload(
                video_path, sync_key, profile.contract,
                **profile.options(), progress_callback=progress_callback,
            )
        else:
            channel = transport or _default_adaptive_transport()
            extracted = channel.extract_adaptive_video_payload(
                video_path, sync_key, profile.contract, plan=plan,
                payload_bytes=video_proof.envelope_size(params, registered=profile.registered),
                **profile.options(), progress_callback=progress_callback,
            )
        in_band_session = video_proof.envelope_session(
            params, extracted.payload, registered=profile.registered
        )
        if plan is None:
            canonical_chunks = tuple(_chunks(extracted.payload, profile))
        else:
            canonical_chunks = _canonical_adaptive_chunks(extracted, plan)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        return VerifyResult(False, f"extraction or envelope rejected: {type(error).__name__}: {error}")
    # The carriers must be the unique encoding of the envelope under the pinned
    # chunk size; otherwise free header fields (e.g. chunk_size of a single
    # chunk) would let carriers change while the proof still verifies.
    extracted_chunks = getattr(extracted, "chunks", None)
    if not isinstance(extracted_chunks, (tuple, list)) or tuple(extracted_chunks) != canonical_chunks:
        return VerifyResult(False, "carrier framing is not the canonical chunking of the envelope")

    def statement_for(challenge: bytes) -> video_proof.VideoStatement:
        return video_proof.build_statement(
            params, pins, challenge,
            carrier_count=len(extracted.global_positions),
            positions_hash=bytes.fromhex(extracted.positions_hash),
            canonical_video_sha256=bytes.fromhex(extracted.canonical_video_sha256),
        )

    def check(challenge: bytes) -> bool:
        statement = statement_for(challenge)
        if credential is None:
            return video_proof.verify_envelope(
                params, statement, extracted.payload, allow_toy_parameters=allow_toy_parameters
            )
        return video_proof.verify_registered_envelope(
            params, statement, credential, extracted.payload,
            allow_toy_parameters=allow_toy_parameters,
        )

    try:
        # Transport-derived digests are hex strings; malformed ones reject.
        statement = statement_for(in_band_session if expected_session is None else expected_session)
    except (TypeError, ValueError) as error:
        return VerifyResult(False, f"statement rejected: {type(error).__name__}: {error}")
    if session_store is None:
        accepted = check(expected_session)
    else:
        accepted = session_store.verify_and_consume(
            in_band_session,
            context_binding=session_binding(params, pins),
            verify=lambda challenge, _binding: check(challenge),
        )
    if not accepted:
        return VerifyResult(False, "proof, statement binding, or session challenge rejected")
    return VerifyResult(
        True, "ok", statement.statement_id, extracted.carriers_used, extracted.payload
    )
