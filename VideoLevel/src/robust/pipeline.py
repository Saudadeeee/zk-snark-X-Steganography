"""Embed a BDLOP proof envelope robustly in decoded luma and verify it blind.

Mirrors ``src.lattice_zk.video_pipeline`` (same parameter sets, signed
relation registry, verifier pins, one-use session store and envelope code)
with a different carrier channel and integrity notion:

* the envelope rides in QIM carriers of the decoded picture (``watermark``)
  under a convolutional code (``ecc``), so it survives re-compression at the
  same resolution with any codec;
* the statement's video commitment is the digest of a carried coarse content
  fingerprint (``features``): 64x64 luma cell means of every frame plus
  128x128-luma-equivalent U/V cell means of every sixth frame; the verifier
  recomputes the fingerprint from what it received and accepts within pinned
  tolerances.

This is *semi-fragile* authentication, not exact integrity: edits that keep
every fingerprint cell within tolerance and keep the watermark decodable are
accepted.  Colour is bound only coarsely (sampled frames, 128x128 cells,
8-level steps): a recolouring confined to unsampled frames or to a small part
of a cell passes.  ``docs/ROBUST_MODE.md`` gives the threat model, the
calibration and the measurements.

Everything derived from the received video fails closed: ``verify_robust_proof``
turns any exception raised while decoding or parsing it, including
``MemoryError`` and an ffmpeg timeout, into ``valid=False``; only verifier
misconfiguration raises.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import struct
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..lattice_zk import bdlop, video_proof
from ..lattice_zk.params import BdlopParams
from ..lattice_zk.video_pipeline import Credential, holder_id_digest
from ..lattice_zk.video_proof import PayloadOpening, VerifierPins
from ..registry.zkp_registry import (
    BDLOP_OPEN_ZKP_SUITE,
    RelationRecord,
    SignedZkpRelationRegistry,
)
from ..registry.zkp_sessions import SessionChallengeStore
from . import decode as video_io
from . import ecc, features, watermark

_DOMAIN = b"zkstego/robust/pipeline/v1/"
# The policy string names the fingerprint blob version: v2 added the sampled
# chroma section, so v1 (luma-only) pins and profiles can never match v2 ones.
ROBUST_POLICY = (
    "robust/decoded-yuv420p8-luma/qim-dct16-low-ac/temporal-groups/conv-k7-crc32"
    "/fingerprint-cell-mean-v2-luma-chroma"
)
CONSTRAINT_MODULE = "bdlop-open-v1 robust: knowledge of a relaxed opening of the in-band commitment"
REGISTERED_CONSTRAINT_MODULE = (
    "bdlop-open-v1 robust: knowledge of a relaxed opening of the registered commitment"
)
MESSAGE_MAGIC = b"ZKRM"
MESSAGE_VERSION = 1
_MESSAGE_HEADER = struct.Struct(">4sBII")
CRC_BYTES = 4
# QIM steps measured on 300-frame CIF clips (docs/ROBUST_MODE.md): the
# registered envelope decodes after x264/x265 CRF 23 and a Main-profile CABAC
# re-encode at step 64 (rate-1/3 code); the larger in-band envelope only fits
# a rate-1/2 code and needs step 80 for static content.
REGISTERED_STEP = 64.0
IN_BAND_STEP = 80.0
# Watermark damage map: 32x32 windows (2x2 carrier blocks) of one frame whose
# bit errors are improbable under that frame's own error rate.
_DAMAGE_WINDOW = 2
_DAMAGE_P_VALUE = 1e-9

ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class RobustProfile:
    """Verifier-pinned configuration of the robust channel and its tolerances."""

    registered: bool = False
    step: float = 64.0
    coefficients: tuple[tuple[int, int], ...] = watermark.DEFAULT_COEFFICIENTS
    block: int = watermark.DEFAULT_BLOCK
    group: int = 3
    fingerprint: features.FingerprintSpec = field(default_factory=features.FingerprintSpec)
    tolerance: features.Tolerance = field(default_factory=features.Tolerance)
    # A frame whose bits disagree this much with the decoded codeword is not
    # the frame that was embedded at that index (dropped, swapped, inserted).
    max_frame_ber: float = 0.42

    def __post_init__(self) -> None:
        if not 0 < self.max_frame_ber < 0.5:
            raise ValueError("max_frame_ber must be in (0, 0.5)")
        if self.group < 1:
            raise ValueError("temporal group must be positive")
        if self.fingerprint.block % self.block:
            raise ValueError("fingerprint cells must be unions of carrier blocks")
        # Validates block size, step and coefficient positions.
        watermark.WatermarkLayout(1, self.block, self.block, self.step, self.coefficients, self.block, 1)

    @classmethod
    def recommended(cls, *, registered: bool) -> RobustProfile:
        return cls(registered=registered, step=REGISTERED_STEP if registered else IN_BAND_STEP)

    def layout(self, frames: int, height: int, width: int) -> watermark.WatermarkLayout:
        return watermark.WatermarkLayout(
            frames, height, width, self.step, self.coefficients, self.block, min(self.group, frames)
        )

    def descriptor(self, params: BdlopParams) -> dict[str, Any]:
        return {
            "policy": ROBUST_POLICY,
            "registered": self.registered,
            "envelope_bytes": video_proof.envelope_size(params, registered=self.registered),
            "step": self.step,
            "coefficients": [list(pair) for pair in self.coefficients],
            "block": self.block,
            "group": self.group,
            "fingerprint": self.fingerprint.descriptor(),
            "tolerance": self.tolerance.descriptor(),
            "max_frame_ber": self.max_frame_ber,
        }

    def profile_id(self, params: BdlopParams) -> bytes:
        encoded = json.dumps(self.descriptor(params), sort_keys=True, separators=(",", ":")).encode("ascii")
        return hashlib.sha256(_DOMAIN + b"profile\0" + encoded).digest()


@dataclass(frozen=True)
class ChannelPlan:
    """Message geometry both sides derive from the pins and the clip geometry."""

    layout: watermark.WatermarkLayout
    envelope_bytes: int
    fingerprint_bytes: int
    rate: int

    @property
    def message_bytes(self) -> int:
        return _MESSAGE_HEADER.size + self.envelope_bytes + self.fingerprint_bytes + CRC_BYTES

    @property
    def coded_bits(self) -> int:
        return ecc.coded_length(8 * self.message_bytes, self.rate)

    @property
    def repetitions(self) -> float:
        return self.layout.capacity / self.coded_bits

    def positions_hash(self) -> bytes:
        encoded = self.layout.encoded() + struct.pack(">BII", self.rate, self.message_bytes, self.coded_bits)
        return hashlib.sha256(_DOMAIN + b"layout\0" + encoded).digest()


@dataclass(frozen=True)
class RobustEmbedResult:
    statement_id: bytes
    opening: PayloadOpening | None
    envelope_bytes: int
    fingerprint_bytes: int
    message_bytes: int
    coded_bits: int
    capacity_bits: int
    rate: int
    repetitions: float
    watermark_psnr: float


@dataclass(frozen=True)
class RobustVerifyResult:
    valid: bool
    reason: str
    statement_id: bytes | None = None
    raw_ber: float | None = None
    max_frame_ber: float | None = None
    # Frame indices whose watermark disagrees with the decoded codeword.
    bad_frames: tuple[int, ...] = ()
    # (frame, row, col, delta) luma fingerprint cells at or above the drift level.
    flagged_cells: tuple[tuple[int, int, int, int], ...] = ()
    max_cell_delta: int | None = None
    # (frame, plane, row, col, delta) sampled chroma cells at or above the
    # chroma drift level; plane 0 is U, 1 is V.
    flagged_chroma_cells: tuple[tuple[int, int, int, int, int], ...] = ()
    max_chroma_delta: int | None = None
    # (frame, row, col) of 32x32 windows whose watermark is locally destroyed
    # (informational localization; it does not decide validity).
    damaged_windows: tuple[tuple[int, int, int], ...] = ()
    envelope: bytes | None = None


def codec_policy_id() -> bytes:
    return hashlib.sha256(_DOMAIN + b"codec-policy\0" + ROBUST_POLICY.encode("ascii")).digest()


def policy_hash(params: BdlopParams, profile: RobustProfile) -> str:
    return hashlib.sha256(
        _DOMAIN + b"policy\0" + codec_policy_id() + profile.profile_id(params)
    ).hexdigest()


def relation_descriptor(
    params: BdlopParams, profile: RobustProfile, credential: bdlop.Commitment | None = None,
    *, holder_id: str | None = None,
) -> dict[str, str]:
    """Registry descriptor; same fields and key binding as the fragile mode."""
    if profile.registered != (credential is not None):
        raise ValueError("a credential commitment is required exactly for registered profiles")
    if holder_id is not None and credential is None:
        raise ValueError("a holder id can only be bound to a registered credential")
    key = bdlop.derive_key(params)
    key_bytes = key.b1_tail.astype(">u8").tobytes() + key.b2_tail.astype(">u8").tobytes()
    module = CONSTRAINT_MODULE
    if credential is not None:
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
    params: BdlopParams, profile: RobustProfile, credential: bdlop.Commitment | None = None,
    *, holder_id: str | None = None,
) -> bytes:
    descriptor = relation_descriptor(params, profile, credential, holder_id=holder_id)
    return bytes.fromhex(RelationRecord.from_descriptor(descriptor).relation_id)


def pins_from_registry(
    registry: SignedZkpRelationRegistry, issuer_public_key: bytes,
    params: BdlopParams, profile: RobustProfile, *, minimum_epoch: int,
    allow_toy_parameters: bool = False, credential: bdlop.Commitment | None = None,
    holder_id: str | None = None,
) -> VerifierPins:
    """Resolve verifier pins from an issuer-signed registry; fail closed."""
    video_proof.require_verifier_parameters(params, allow_toy_parameters=allow_toy_parameters)
    if not registry.verify(issuer_public_key):
        raise ValueError("relation registry signature did not verify against the issuer key")
    if registry.epoch < minimum_epoch:
        raise ValueError("relation registry is older than the verifier minimum epoch")
    descriptor = relation_descriptor(params, profile, credential, holder_id=holder_id)
    matches = [record for record in registry.relations if record.descriptor() == descriptor]
    if len(matches) != 1:
        raise ValueError("this parameter set, robust profile, credential and holder id are not registered")
    root, epoch = registry.resolve(matches[0].relation_id, BDLOP_OPEN_ZKP_SUITE, descriptor["policy_hash"])
    return VerifierPins(
        relation_id=bytes.fromhex(matches[0].relation_id),
        registry_root=bytes.fromhex(root),
        registry_epoch=epoch,
        codec_policy_id=codec_policy_id(),
        carrier_profile_id=profile.profile_id(params),
    )


def session_binding(params: BdlopParams, pins: VerifierPins) -> bytes:
    return hashlib.sha256(
        _DOMAIN + b"session-binding\0" + params.parameter_id + pins.relation_id
        + pins.registry_root + pins.registry_epoch.to_bytes(8, "big")
        + pins.codec_policy_id + pins.carrier_profile_id
    ).digest()


def public_sync_key(params: BdlopParams, profile: RobustProfile) -> bytes:
    """Carrier key from public configuration: anyone with the pins can verify."""
    return hashlib.sha256(
        _DOMAIN + b"public-carrier-key\0" + params.parameter_id + profile.profile_id(params)
    ).digest()


def fingerprint_digest(blob: bytes) -> bytes:
    return hashlib.sha256(_DOMAIN + b"fingerprint\0" + blob).digest()


def channel_plan(
    params: BdlopParams, profile: RobustProfile, frames: int, height: int, width: int,
) -> ChannelPlan:
    """Pick the strongest code rate whose codeword fits the clip; else refuse."""
    layout = profile.layout(frames, height, width)
    envelope_bytes = video_proof.envelope_size(params, registered=profile.registered)
    fingerprint_bytes = profile.fingerprint.blob_bytes(frames, height, width)
    for rate in (3, 2):
        plan = ChannelPlan(layout, envelope_bytes, fingerprint_bytes, rate)
        if plan.coded_bits <= layout.capacity:
            return plan
    plan = ChannelPlan(layout, envelope_bytes, fingerprint_bytes, 2)
    raise ValueError(
        f"clip carries {layout.capacity} slots but the envelope needs {plan.coded_bits} coded bits; "
        "use a longer or larger clip"
    )


def _statement(
    params: BdlopParams, pins: VerifierPins, challenge: bytes, plan: ChannelPlan, blob: bytes,
) -> video_proof.VideoStatement:
    return video_proof.build_statement(
        params, pins, challenge,
        carrier_count=plan.layout.capacity,
        positions_hash=plan.positions_hash(),
        canonical_video_sha256=fingerprint_digest(blob),
    )


def _message(envelope: bytes, blob: bytes) -> bytes:
    header = _MESSAGE_HEADER.pack(MESSAGE_MAGIC, MESSAGE_VERSION, len(envelope), len(blob))
    return ecc.with_crc(header + envelope + blob)


def _parse_message(data: bytes, plan: ChannelPlan) -> tuple[bytes, bytes]:
    body = ecc.strip_crc(data)
    magic, version, envelope_bytes, fingerprint_bytes = _MESSAGE_HEADER.unpack_from(body)
    if magic != MESSAGE_MAGIC or version != MESSAGE_VERSION:
        raise ValueError("message magic or version is unsupported")
    if (envelope_bytes, fingerprint_bytes) != (plan.envelope_bytes, plan.fingerprint_bytes):
        raise ValueError("message section lengths differ from the pinned plan")
    split = _MESSAGE_HEADER.size + envelope_bytes
    return body[_MESSAGE_HEADER.size:split], body[split:]


def _binomial_upper_tail(successes: np.ndarray, trials: int, rate: np.ndarray) -> np.ndarray:
    """``P[X >= successes]`` for ``X ~ Binomial(trials, rate[frame])``, exactly.

    ``successes`` has shape ``(frames, rows, cols)``; ``rate`` one entry per
    frame.  ``trials`` is a few dozen, so the full pmf per frame is cheap and
    no scipy dependency is needed on the verify path.
    """
    k = np.arange(trials + 1)
    combinations = np.array([math.comb(trials, int(i)) for i in k], dtype=np.float64)
    p = rate.reshape(-1, 1)
    pmf = combinations * p ** k * (1.0 - p) ** (trials - k)
    upper = np.cumsum(pmf[:, ::-1], axis=1)[:, ::-1]  # upper[f, k] = P[X >= k]
    frame = np.arange(len(rate)).reshape(-1, 1, 1)
    return upper[frame, successes]


def _damaged_windows(errors: np.ndarray, layout: watermark.WatermarkLayout) -> tuple[tuple[int, int, int], ...]:
    """Windows whose error count has a binomial tail below ``_DAMAGE_P_VALUE``."""
    count = len(layout.coefficients)
    rows, cols = layout.block_rows // _DAMAGE_WINDOW, layout.block_cols // _DAMAGE_WINDOW
    if rows == 0 or cols == 0:
        return ()
    per_block = errors.reshape(layout.frames, layout.block_rows, layout.block_cols, count).sum(axis=3)
    trimmed = per_block[:, : rows * _DAMAGE_WINDOW, : cols * _DAMAGE_WINDOW]
    windows = trimmed.reshape(layout.frames, rows, _DAMAGE_WINDOW, cols, _DAMAGE_WINDOW).sum(axis=(2, 4))
    trials = _DAMAGE_WINDOW * _DAMAGE_WINDOW * count
    rate = np.clip(errors.mean(axis=1), 0.01, 0.49)
    tail = _binomial_upper_tail(windows.astype(np.int64), trials, rate)
    return tuple((int(f), int(r), int(c)) for f, r, c in np.argwhere(tail < _DAMAGE_P_VALUE))


def _psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = float(np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2))
    return float("inf") if mse == 0 else 10.0 * np.log10(255.0 ** 2 / mse)


def embed_robust_proof(
    cover_path: str | Path, output_path: str | Path, payload: bytes | None, *,
    params: BdlopParams, pins: VerifierPins, profile: RobustProfile,
    session_challenge: bytes, sync_key: bytes, credential: Credential | None = None,
    encoder: video_io.EncoderSettings | None = None,
    progress_callback: ProgressCallback | None = None,
) -> RobustEmbedResult:
    """Prove, then embed the envelope and the cover fingerprint robustly.

    ``output_path`` must not exist yet and must differ from the cover; both
    are checked before the proof is computed.
    """
    if profile.registered != (credential is not None) or profile.registered == (payload is not None):
        raise ValueError("supply a payload for robust in-band profiles or a credential for registered ones")
    report = progress_callback or (lambda _event: None)
    if video_io.require_fresh_output(output_path) == Path(cover_path).resolve():
        raise ValueError("output path must differ from the cover")
    cover = video_io.decode(cover_path)
    plan = channel_plan(params, profile, cover.frames, cover.height, cover.width)
    blob = features.compute(cover.y, profile.fingerprint, cover.u, cover.v).to_bytes()
    if len(blob) != plan.fingerprint_bytes:
        raise RuntimeError("fingerprint size differs from the channel plan")
    report({"stage": "plan", "capacity": plan.layout.capacity, "coded_bits": plan.coded_bits, "rate": plan.rate})
    statement = _statement(params, pins, session_challenge, plan, blob)
    if credential is None:
        envelope, opening = video_proof.create_envelope(params, statement, payload)
    else:
        opening = None
        envelope = video_proof.create_registered_envelope(
            params, statement, credential.commitment, credential.randomness
        )
    if len(envelope) != plan.envelope_bytes:
        raise RuntimeError("envelope size differs from the channel plan")
    report({"stage": "proved"})
    codeword = ecc.conv_encode(ecc.bytes_to_bits(_message(envelope, blob)), plan.rate)
    slot_bits = watermark.spread(codeword, watermark.permutation(sync_key, plan.layout))
    marked = watermark.embed(cover.y, slot_bits, sync_key, plan.layout)
    video_io.encode(
        video_io.DecodedVideo(marked, cover.u, cover.v, cover.frame_rate), output_path,
        encoder or video_io.EncoderSettings(crf=12),
    )
    report({"stage": "encoded"})
    return RobustEmbedResult(
        statement_id=statement.statement_id,
        opening=opening,
        envelope_bytes=len(envelope),
        fingerprint_bytes=len(blob),
        message_bytes=plan.message_bytes,
        coded_bits=plan.coded_bits,
        capacity_bits=plan.layout.capacity,
        rate=plan.rate,
        repetitions=plan.repetitions,
        watermark_psnr=_psnr(cover.y, marked),
    )


def _require_verifier_configuration(
    params: BdlopParams, pins: VerifierPins, profile: RobustProfile,
    session_store: SessionChallengeStore | None, expected_session: bytes | None,
    credential: bdlop.Commitment | None, holder_id: str | None, allow_toy_parameters: bool,
) -> None:
    video_proof.require_verifier_parameters(params, allow_toy_parameters=allow_toy_parameters)
    if (session_store is None) == (expected_session is None):
        raise ValueError("supply exactly one of session_store or expected_session")
    if expected_session is not None and (not isinstance(expected_session, bytes) or len(expected_session) != 32):
        raise ValueError("expected_session must be exactly 32 bytes")
    if profile.registered != (credential is not None):
        raise ValueError("a pinned credential is required exactly for registered profiles")
    if credential is not None and not (isinstance(credential, bdlop.Commitment) and credential.is_canonical(params)):
        raise ValueError("the pinned credential is not a canonical commitment for this parameter set")
    if not isinstance(pins, VerifierPins):
        raise ValueError("pins must be VerifierPins")
    if not hmac.compare_digest(pins.codec_policy_id, codec_policy_id()):
        raise ValueError("pinned codec policy is not the robust policy")
    if not hmac.compare_digest(pins.carrier_profile_id, profile.profile_id(params)):
        raise ValueError("pinned carrier profile does not match this robust profile")
    expected = relation_id(params, profile, credential, holder_id=holder_id)
    if not hmac.compare_digest(expected, pins.relation_id):
        raise ValueError("pinned relation id does not match this parameter set, profile, credential and holder id")


@dataclass(frozen=True)
class _Recovered:
    """What the untrusted video yielded before the proof itself is checked."""

    plan: ChannelPlan
    envelope: bytes
    blob: bytes
    in_band_session: bytes
    stats: dict[str, Any]


def _recover_message(
    received: video_io.DecodedVideo, plan: ChannelPlan, sync_key: bytes, profile: RobustProfile,
) -> tuple[bytes, bytes, dict[str, Any]] | RobustVerifyResult:
    """Blind-decode the message and measure the per-frame channel against it."""
    order = watermark.permutation(sync_key, plan.layout)
    frame_soft = watermark.frame_soft_values(received.y, sync_key, plan.layout)
    combined = watermark.gather(watermark.slot_soft_values(frame_soft, plan.layout), order, plan.coded_bits)
    try:
        message_bits = ecc.viterbi_decode(combined, plan.rate)
        envelope, blob = _parse_message(ecc.bits_to_bytes(message_bits), plan)
    except (ValueError, struct.error) as error:
        return RobustVerifyResult(False, f"watermark not recoverable: {error}")
    # Raw channel quality against the corrected codeword, per frame.
    codeword = ecc.conv_encode(message_bits, plan.rate)
    expected = watermark.frame_expected_bits(watermark.spread(codeword, order), plan.layout)
    errors = (frame_soft > 0) != expected.astype(bool)
    per_frame = errors.mean(axis=1)
    bad_frames = tuple(int(index) for index in np.flatnonzero(per_frame > profile.max_frame_ber))
    stats = {
        "raw_ber": float(per_frame.mean()), "max_frame_ber": float(per_frame.max()), "bad_frames": bad_frames,
        "damaged_windows": _damaged_windows(errors, plan.layout),
    }
    if bad_frames:
        return RobustVerifyResult(
            False, f"{len(bad_frames)} frame(s) do not carry their watermark (dropped, swapped or replaced)",
            **stats,
        )
    return envelope, blob, stats


def _check_fingerprint(
    received: video_io.DecodedVideo, blob: bytes, profile: RobustProfile, stats: dict[str, Any],
) -> RobustVerifyResult | None:
    """Compare the carried fingerprint with the received picture; None when it passes."""
    try:
        carried = features.Fingerprint.from_bytes(blob)
    except ValueError as error:
        return RobustVerifyResult(False, f"fingerprint rejected: {error}", **stats)
    if carried.spec != profile.fingerprint:
        return RobustVerifyResult(False, "carried fingerprint specification differs from the pin", **stats)
    recomputed = features.compute(received.y, profile.fingerprint, received.u, received.v)
    comparison = features.compare(carried, recomputed, profile.tolerance)
    stats.update(
        flagged_cells=comparison.flagged, max_cell_delta=comparison.max_delta,
        flagged_chroma_cells=comparison.flagged_chroma, max_chroma_delta=comparison.max_chroma_delta,
    )
    if not comparison.accepted:
        return RobustVerifyResult(False, comparison.reason, **stats)
    return None


def _recover(
    video_path: str | Path, params: BdlopParams, profile: RobustProfile, sync_key: bytes,
    max_luma_samples: int,
) -> _Recovered | RobustVerifyResult:
    """Everything derived from the untrusted file, up to the parsed envelope."""
    received = video_io.decode(video_path, max_luma_samples=max_luma_samples)
    plan = channel_plan(params, profile, received.frames, received.height, received.width)
    recovered = _recover_message(received, plan, sync_key, profile)
    if isinstance(recovered, RobustVerifyResult):
        return recovered
    envelope, blob, stats = recovered
    rejection = _check_fingerprint(received, blob, profile, stats)
    if rejection is not None:
        return rejection
    try:
        in_band_session = video_proof.envelope_session(params, envelope, registered=profile.registered)
    except (TypeError, ValueError, struct.error) as error:
        return RobustVerifyResult(False, f"envelope rejected: {error}", **stats)
    return _Recovered(plan, envelope, blob, in_band_session, stats)


def _recover_fail_closed(
    video_path: str | Path, params: BdlopParams, profile: RobustProfile, sync_key: bytes,
    max_luma_samples: int,
) -> _Recovered | RobustVerifyResult:
    """``_recover`` with every exception from the untrusted input turned into a rejection."""
    try:
        return _recover(video_path, params, profile, sync_key, max_luma_samples)
    except MemoryError:
        return RobustVerifyResult(False, "video rejected: decoding or analysis exceeded available memory")
    except subprocess.TimeoutExpired as error:
        return RobustVerifyResult(False, f"video rejected: ffmpeg exceeded the {error.timeout:.0f} s limit")
    except Exception as error:  # noqa: BLE001 - untrusted input must never raise out of verify
        return RobustVerifyResult(False, f"video rejected: {type(error).__name__}: {error}")


def verify_robust_proof(
    video_path: str | Path, *,
    params: BdlopParams, pins: VerifierPins, profile: RobustProfile, sync_key: bytes,
    session_store: SessionChallengeStore | None = None, expected_session: bytes | None = None,
    credential: bdlop.Commitment | None = None, holder_id: str | None = None,
    allow_toy_parameters: bool = False, max_luma_samples: int = video_io.MAX_LUMA_SAMPLES,
) -> RobustVerifyResult:
    """Blind-decode the envelope and fingerprint, check content, then the proof.

    Verifier misconfiguration raises ``ValueError`` before the video is read.
    Anything derived from the video only yields ``valid=False``: that covers
    ffmpeg failures and timeouts, a clip over the ``max_luma_samples`` decode
    budget, ``MemoryError`` and any parsing exception from a malformed carried
    message or envelope.  Session-store I/O errors still propagate.
    """
    _require_verifier_configuration(
        params, pins, profile, session_store, expected_session, credential, holder_id, allow_toy_parameters
    )
    recovered = _recover_fail_closed(video_path, params, profile, sync_key, max_luma_samples)
    if isinstance(recovered, RobustVerifyResult):
        return recovered
    plan, envelope, blob, stats = recovered.plan, recovered.envelope, recovered.blob, recovered.stats
    session = recovered.in_band_session if expected_session is None else expected_session
    statement = _statement(params, pins, session, plan, blob)

    def check(challenge: bytes) -> bool:
        candidate = _statement(params, pins, challenge, plan, blob)
        try:
            if credential is None:
                return video_proof.verify_envelope(
                    params, candidate, envelope, allow_toy_parameters=allow_toy_parameters
                )
            return video_proof.verify_registered_envelope(
                params, candidate, credential, envelope, allow_toy_parameters=allow_toy_parameters
            )
        except Exception:  # noqa: BLE001 - a malformed envelope is a rejection, not a crash
            return False

    if session_store is None:
        accepted = check(expected_session)
    else:
        accepted = session_store.verify_and_consume(
            recovered.in_band_session, context_binding=session_binding(params, pins),
            verify=lambda challenge, _binding: check(challenge),
        )
    if not accepted:
        return RobustVerifyResult(False, "proof, statement binding, or session challenge rejected", **stats)
    return RobustVerifyResult(True, "ok", statement.statement_id, envelope=envelope, **stats)


__all__ = [
    "ROBUST_POLICY",
    "ChannelPlan",
    "Credential",
    "RobustEmbedResult",
    "RobustProfile",
    "RobustVerifyResult",
    "channel_plan",
    "codec_policy_id",
    "embed_robust_proof",
    "fingerprint_digest",
    "pins_from_registry",
    "policy_hash",
    "public_sync_key",
    "relation_descriptor",
    "relation_id",
    "session_binding",
    "verify_robust_proof",
]
