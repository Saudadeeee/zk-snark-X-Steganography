"""Embed a BDLOP proof envelope in H.264 CAVLC carriers and verify it blind.

The verifier needs the stego video, its pinned configuration (parameter set,
signed relation registry, carrier contract, sync key) and its own session
state.  It uses no sidecar, cover video, or prover-supplied position list.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from ..zkp_registry import BDLOP_OPEN_ZKP_SUITE, SignedZkpRelationRegistry
from ..zkp_sessions import SessionChallengeStore
from . import bdlop, video_proof
from .params import BdlopParams
from .video_proof import PayloadOpening, VerifierPins

_DOMAIN = b"zkstego/lattice-zk/video-pipeline/v1/"
CODEC_POLICY = "h264-baseline-cavlc/canonical-h264-carrier-normalized-sha256-v1"
CONSTRAINT_MODULE = "bdlop-open-v1: knowledge of a relaxed opening of the in-band commitment"
REGISTERED_CONSTRAINT_MODULE = (
    "bdlop-open-v1: knowledge of a relaxed opening of the registered commitment"
)
DEFAULT_FRAMES_PER_SEGMENT = 100
DEFAULT_CHUNK_BYTES = 1_250

ProgressCallback = Callable[[dict[str, Any]], None]


class Transport(Protocol):
    """Blind carrier channel; ``src.blind_sync_streaming`` is the real one."""

    def derive_chunked_video_context(self, video_path, chunks, sync_key, contract, **options): ...

    def embed_chunked_video_payload(self, cover, output, payload, sync_key, contract, **options): ...

    def extract_chunked_video_payload(self, video_path, sync_key, contract, **options): ...


@dataclass(frozen=True)
class CarrierProfile:
    """Verifier-pinned transport configuration that fixes carrier placement."""

    contract: Any
    frames_per_segment: int = DEFAULT_FRAMES_PER_SEGMENT
    chunk_bytes: int = DEFAULT_CHUNK_BYTES
    # True: the commitment is pinned by the registry and the video carries only the proof.
    registered: bool = False

    def profile_id(self, params: BdlopParams) -> bytes:
        description = {
            "contract": dataclasses.asdict(self.contract),
            "frames_per_segment": self.frames_per_segment,
            "chunk_bytes": self.chunk_bytes,
            "envelope_bytes": video_proof.envelope_size(params, registered=self.registered),
            "registered": self.registered,
        }
        encoded = json.dumps(description, sort_keys=True, separators=(",", ":")).encode("ascii")
        return hashlib.sha256(_DOMAIN + b"carrier-profile\0" + encoded).digest()

    def options(self) -> dict[str, int]:
        return {"frames_per_segment": self.frames_per_segment}


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


@dataclass(frozen=True)
class VerifyResult:
    valid: bool
    reason: str
    statement_id: bytes | None = None
    carriers_used: int = 0
    # Verified in-band envelope; lets a caller check later linkage or disclosure.
    envelope: bytes | None = None


def codec_policy_id() -> bytes:
    return hashlib.sha256(_DOMAIN + b"codec-policy\0" + CODEC_POLICY.encode("ascii")).digest()


def policy_hash(params: BdlopParams, profile: CarrierProfile) -> str:
    """Registry policy digest: codec policy plus carrier profile."""
    return hashlib.sha256(
        _DOMAIN + b"policy\0" + codec_policy_id() + profile.profile_id(params)
    ).hexdigest()


def relation_descriptor(
    params: BdlopParams, profile: CarrierProfile, credential: bdlop.Commitment | None = None
) -> dict[str, str]:
    """Descriptor an issuer signs into the relation registry for this backend.

    For a registered profile the issuer's signature also covers the holder's
    credential commitment, which is what makes the proof authenticate them.
    """
    if profile.registered != (credential is not None):
        raise ValueError("a credential commitment is required exactly for registered profiles")
    key = bdlop.derive_key(params)
    key_bytes = key.b1_tail.astype(">u8").tobytes() + key.b2_tail.astype(">u8").tobytes()
    module = CONSTRAINT_MODULE
    if credential is not None:
        key_bytes += credential.to_bytes(params)
        module = REGISTERED_CONSTRAINT_MODULE
    return {
        "zkp_suite": BDLOP_OPEN_ZKP_SUITE,
        "constraint_module_hash": hashlib.sha256(module.encode("ascii")).hexdigest(),
        "verifier_key_hash": hashlib.sha256(key_bytes).hexdigest(),
        "parameter_set_hash": params.parameter_id.hex(),
        "policy_hash": policy_hash(params, profile),
    }


def pins_from_registry(
    registry: SignedZkpRelationRegistry, issuer_public_key: bytes,
    params: BdlopParams, profile: CarrierProfile, *, minimum_epoch: int,
    allow_toy_parameters: bool = False, credential: bdlop.Commitment | None = None,
) -> VerifierPins:
    """Resolve verifier pins from an issuer-signed registry; fail closed.

    ``minimum_epoch`` is the verifier's rollback floor.  Parameter sets with a
    challenge space below 2^256 are refused unless a test opts in.
    """
    if not allow_toy_parameters:
        params.require_production_strength()
    if not registry.verify(issuer_public_key):
        raise ValueError("relation registry signature did not verify against the issuer key")
    if registry.epoch < minimum_epoch:
        raise ValueError("relation registry is older than the verifier minimum epoch")
    descriptor = relation_descriptor(params, profile, credential)
    matches = [record for record in registry.relations if record.descriptor() == descriptor]
    if len(matches) != 1:
        raise ValueError("this parameter set and carrier profile are not registered")
    root, epoch = registry.resolve(
        matches[0].relation_id, BDLOP_OPEN_ZKP_SUITE, descriptor["policy_hash"]
    )
    return VerifierPins(
        relation_id=bytes.fromhex(matches[0].relation_id),
        registry_root=bytes.fromhex(root),
        registry_epoch=epoch,
        codec_policy_id=codec_policy_id(),
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
    from .. import blind_sync_streaming

    return blind_sync_streaming  # type: ignore[return-value]


def _chunks(payload: bytes, profile: CarrierProfile) -> list[bytes]:
    from ..blind_payload_chunks import pack_payload_chunks

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
    channel = transport or _default_transport()
    options = {**profile.options(), "progress_callback": progress_callback}
    placeholder = _chunks(
        video_proof.placeholder_envelope(params, registered=profile.registered), profile
    )
    context = channel.derive_chunked_video_context(
        cover_path, placeholder, sync_key, profile.contract, **options
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


def verify_video_proof(
    video_path: str | Path, *,
    params: BdlopParams, pins: VerifierPins, profile: CarrierProfile, sync_key: bytes,
    session_store: SessionChallengeStore | None = None, expected_session: bytes | None = None,
    credential: bdlop.Commitment | None = None,
    transport: Transport | None = None, progress_callback: ProgressCallback | None = None,
) -> VerifyResult:
    """Blind-extract the envelope and verify it against a verifier-built statement.

    Exactly one of ``session_store`` (one-use, replay-protected) or
    ``expected_session`` (stateless; no replay protection) must be supplied.
    """
    if (session_store is None) == (expected_session is None):
        raise ValueError("supply exactly one of session_store or expected_session")
    if profile.registered != (credential is not None):
        raise ValueError("a pinned credential is required exactly for registered profiles")
    channel = transport or _default_transport()
    try:
        extracted = channel.extract_chunked_video_payload(
            video_path, sync_key, profile.contract,
            **profile.options(), progress_callback=progress_callback,
        )
        in_band_session = video_proof.envelope_session(
            params, extracted.payload, registered=profile.registered
        )
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        return VerifyResult(False, f"extraction or envelope rejected: {type(error).__name__}: {error}")

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
            return video_proof.verify_envelope(params, statement, extracted.payload)
        return video_proof.verify_registered_envelope(
            params, statement, credential, extracted.payload
        )

    if session_store is None:
        statement = statement_for(expected_session)
        accepted = check(expected_session)
    else:
        statement = statement_for(in_band_session)
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
