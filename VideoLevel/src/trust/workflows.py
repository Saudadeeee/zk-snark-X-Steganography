"""Ready-to-use trust workflows for future applications.

These helpers wrap the lower-level provenance, fingerprint, watermark, and
attestation primitives into higher-level application flows. They are meant to
be called directly by the system, not just by diagnostics.
"""

from __future__ import annotations

import copy
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from src.manifest import StegoManifest
from src.provenance import (
    C2PAAuditSidecar,
    build_c2pa_anchor,
    load_audit_sidecar,
    save_audit_sidecar,
    attach_anchor_to_manifest,
    verify_c2pa_anchor,
)

from .attestation import AttestationBundle, AttestationSidecar, MockTEESigner, SignedAttestation, load_attestation_sidecar, save_attestation_sidecar
from .fingerprint import FingerprintPreprocessPolicy, FingerprintRecord, FingerprintRegistry, RegistryMatch, VideoFingerprint, compute_video_fingerprint
from .provenance import ProvenanceRoot, build_provenance_root, verify_provenance_root
from .watermark_receipt import (
    CalibratedThresholdDetector,
    DetectorAlignmentScore,
    DetectorCalibration,
    DetectorReceipt,
    KeyedTemplateDetector,
)


def _manifest_dict(manifest: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(manifest, dict):
        return dict(manifest)
    with open(manifest, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    if not isinstance(loaded, dict):
        raise ValueError("manifest must be a JSON object")
    return loaded


def _tamper_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    tampered = copy.deepcopy(manifest)
    if "claim_generator" in tampered and isinstance(tampered["claim_generator"], str):
        tampered["claim_generator"] = f"{tampered['claim_generator']}-tampered"
        return tampered
    assertions = tampered.get("assertions")
    if isinstance(assertions, list) and assertions:
        first = assertions[0]
        if isinstance(first, dict) and "value" in first:
            first["value"] = f"{first['value']}-tampered"
            return tampered
    tampered["_tampered_marker"] = True
    return tampered


@dataclass(frozen=True)
class ProvenanceWorkflowResult:
    root: ProvenanceRoot
    sidecar: C2PAAuditSidecar
    verified: bool
    embedded_payload_valid: bool
    embedded_payload_tamper_detected: bool
    manifest_tamper_detected: bool
    attached_manifest: StegoManifest | None = None
    sidecar_roundtrip_valid: bool | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "root": self.root.to_dict(),
            "sidecar": self.sidecar.to_dict(),
            "verified": self.verified,
            "embedded_payload_valid": self.embedded_payload_valid,
            "embedded_payload_tamper_detected": self.embedded_payload_tamper_detected,
            "manifest_tamper_detected": self.manifest_tamper_detected,
            "attached_manifest": self.attached_manifest.to_json() if self.attached_manifest else None,
            "sidecar_roundtrip_valid": self.sidecar_roundtrip_valid,
        }


@dataclass(frozen=True)
class FingerprintWorkflowResult:
    policy: FingerprintPreprocessPolicy
    fingerprint: VideoFingerprint
    registry: FingerprintRegistry
    match: RegistryMatch

    def to_dict(self) -> dict[str, object]:
        return {
            "policy": self.policy.to_dict(),
            "fingerprint": self.fingerprint.to_dict(),
            "registry_commitment": self.registry.commitment(),
            "match": {
                "matched": self.match.matched,
                "record_id": self.match.record_id,
                "distance": self.match.distance,
                "threshold": self.match.threshold,
                "registry_commitment": self.match.registry_commitment,
            },
        }


@dataclass(frozen=True)
class WatermarkWorkflowResult:
    detector: KeyedTemplateDetector
    calibration: DetectorCalibration | None
    fixed_receipt: DetectorReceipt
    resynchronized_receipt: DetectorReceipt
    resynchronized_alignment: DetectorAlignmentScore
    claim_scope: tuple[str, ...]
    out_of_scope: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "detector": self.detector.public_config(),
            "detector_commitment": self.detector.commitment,
            "calibration": self.calibration.to_dict() if self.calibration else None,
            "fixed_receipt": self.fixed_receipt.to_dict(),
            "resynchronized_receipt": self.resynchronized_receipt.to_dict(),
            "resynchronized_alignment": self.resynchronized_alignment.to_dict(),
            "claim_scope": list(self.claim_scope),
            "out_of_scope": list(self.out_of_scope),
        }


@dataclass(frozen=True)
class AttestationWorkflowResult:
    bundle: AttestationBundle
    signed_attestation: SignedAttestation
    sidecar: AttestationSidecar
    signature_valid: bool
    sidecar_roundtrip_valid: bool | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "bundle": self.bundle.to_dict(),
            "signed_attestation": self.signed_attestation.to_dict(),
            "sidecar": self.sidecar.to_dict(),
            "signature_valid": self.signature_valid,
            "sidecar_roundtrip_valid": self.sidecar_roundtrip_valid,
        }


def provenance_workflow(
    manifest: str | Path | dict[str, Any],
    *,
    registry_uri: str,
    media_path: str | Path | None = None,
    stego_manifest: StegoManifest | None = None,
    sidecar_path: str | Path | None = None,
) -> ProvenanceWorkflowResult:
    """Build, verify, and optionally attach a C2PA-style provenance root."""
    manifest_dict = _manifest_dict(manifest)
    root = build_provenance_root(manifest_dict, manifest_uri=registry_uri, media_path=media_path)
    sidecar = build_c2pa_anchor(manifest_dict, registry_uri=registry_uri, media_path=media_path)

    sidecar_roundtrip_valid: bool | None = None
    if sidecar_path is not None:
        save_audit_sidecar(sidecar, sidecar_path)
        loaded_sidecar = load_audit_sidecar(sidecar_path)
        sidecar_roundtrip_valid = verify_c2pa_anchor(loaded_sidecar, manifest_dict, media_path=media_path)

    attached_manifest = None
    if stego_manifest is not None:
        attached_manifest = attach_anchor_to_manifest(copy.deepcopy(stego_manifest), sidecar)

    embedded_payload = sidecar.anchor.payload_bytes
    verified = verify_c2pa_anchor(sidecar, manifest_dict, media_path=media_path, embedded_payload=embedded_payload)
    embedded_payload_tamper_detected = not verify_c2pa_anchor(
        sidecar,
        manifest_dict,
        embedded_payload=b"\x00" * 32,
    )
    manifest_tamper_detected = not verify_c2pa_anchor(sidecar, _tamper_manifest(manifest_dict), media_path=media_path)

    return ProvenanceWorkflowResult(
        root=root,
        sidecar=sidecar,
        verified=verified,
        embedded_payload_valid=verified,
        embedded_payload_tamper_detected=embedded_payload_tamper_detected,
        manifest_tamper_detected=manifest_tamper_detected,
        attached_manifest=attached_manifest,
        sidecar_roundtrip_valid=sidecar_roundtrip_valid,
    )


def fingerprint_workflow(
    frames: Sequence[np.ndarray] | np.ndarray,
    records: Iterable[FingerprintRecord],
    *,
    policy: FingerprintPreprocessPolicy | None = None,
    threshold: int = 8,
) -> FingerprintWorkflowResult:
    """Compute a video fingerprint and match it against a private registry."""
    policy = policy or FingerprintPreprocessPolicy()
    registry = FingerprintRegistry(records)
    fingerprint = compute_video_fingerprint(frames, policy=policy)
    match = registry.lookup(fingerprint.fingerprint_hex, bit_count=fingerprint.bit_count, threshold=threshold)
    return FingerprintWorkflowResult(policy=policy, fingerprint=fingerprint, registry=registry, match=match)


def watermark_workflow(
    frames: Sequence[np.ndarray] | np.ndarray,
    *,
    key: bytes | str,
    frame_shape: tuple[int, int],
    threshold: float | None = None,
    positive_clips: Sequence[Sequence[np.ndarray] | np.ndarray] | None = None,
    negative_clips: Sequence[Sequence[np.ndarray] | np.ndarray] | None = None,
    grid_size: int = 8,
    crop_margins: Sequence[int] = (0, 4, 8, 12),
    payload_commitment: str | None = None,
) -> WatermarkWorkflowResult:
    """Calibrate and/or evaluate a keyed watermark detector."""
    detector = KeyedTemplateDetector(key, frame_shape=frame_shape, grid_size=grid_size)
    calibration: DetectorCalibration | None = None
    if threshold is None:
        if positive_clips is None or negative_clips is None:
            raise ValueError("either threshold or calibration clips must be provided")
        calibration = detector.calibrate_resynchronized(positive_clips, negative_clips, crop_margins=crop_margins)
        threshold = calibration.threshold

    fixed_receipt = detector.receipt(frames, threshold=threshold, payload_commitment=payload_commitment)
    aligned = detector.score_resynchronized(frames, crop_margins=crop_margins)
    resynchronized_receipt = DetectorReceipt(
        detector_id=detector.detector_id,
        score=aligned.score,
        threshold=threshold,
        valid=aligned.score >= threshold,
        payload_commitment=payload_commitment,
        detector_commitment=detector.commitment,
    )
    return WatermarkWorkflowResult(
        detector=detector,
        calibration=calibration,
        fixed_receipt=fixed_receipt,
        resynchronized_receipt=resynchronized_receipt,
        resynchronized_alignment=aligned,
        claim_scope=(
            "brightness_shift",
            "contrast_scale",
            "mild_noise",
            "down_up_nearest",
            "box_blur",
            "temporal_reverse",
            "frame_drop",
        ),
        out_of_scope=(
            "crop_with_resynchronization",
            "geometric_flip",
            "screen_recording",
            "heavy_reencoding",
        ),
    )


def attestation_workflow(
    *,
    signer: MockTEESigner,
    bundle: AttestationBundle | None = None,
    video_path: str | Path | None = None,
    model_config_path: str | Path | None = None,
    model_binary_path: str | Path | None = None,
    policy_id: str | None = None,
    timestamp: str | None = None,
    hardware_root: str | None = None,
    provenance_root_hash: str | None = None,
    sidecar_path: str | Path | None = None,
) -> AttestationWorkflowResult:
    """Sign an attestation bundle and optionally round-trip its sidecar."""
    if bundle is None:
        if not (video_path and model_config_path and model_binary_path and policy_id and timestamp):
            raise ValueError("bundle or file paths plus policy_id/timestamp must be provided")
        bundle = AttestationBundle.from_files(
            video_path=str(video_path),
            model_config_path=str(model_config_path),
            model_binary_path=str(model_binary_path),
            policy_id=policy_id,
            timestamp=timestamp,
            hardware_root=hardware_root,
        )

    signed = signer.sign(bundle)
    sidecar = AttestationSidecar(signed_attestation=signed, provenance_root_hash=provenance_root_hash)
    signature_valid = signer.verify(signed)
    sidecar_roundtrip_valid: bool | None = None
    if sidecar_path is not None:
        save_attestation_sidecar(sidecar, sidecar_path)
        loaded = load_attestation_sidecar(sidecar_path)
        sidecar_roundtrip_valid = signer.verify(loaded.signed_attestation)
        if provenance_root_hash is not None:
            sidecar_roundtrip_valid = sidecar_roundtrip_valid and loaded.provenance_root_hash == provenance_root_hash

    return AttestationWorkflowResult(
        bundle=bundle,
        signed_attestation=signed,
        sidecar=sidecar,
        signature_valid=signature_valid,
        sidecar_roundtrip_valid=sidecar_roundtrip_valid,
    )

