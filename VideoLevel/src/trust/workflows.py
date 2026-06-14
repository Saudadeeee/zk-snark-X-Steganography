"""Ready-to-use trust workflows for future applications.

These helpers wrap the lower-level provenance, fingerprint, watermark, and
attestation primitives into higher-level application flows. They are meant to
be called directly by the system, not just by diagnostics.
"""

from __future__ import annotations

import copy
import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from src.manifest import StegoManifest
from src.provenance import (
    C2PAAuditSidecar,
    ProvenanceRegistry,
    build_c2pa_anchor,
    load_audit_sidecar,
    save_audit_sidecar,
    attach_anchor_to_manifest,
    verify_c2pa_anchor,
)

from .attestation import (
    AttestationBundle,
    AttestationSidecar,
    AttestationVerificationPolicy,
    AttestationVerificationReport,
    Ed25519AttestationSigner,
    MockTEESigner,
    SignedAttestation,
    verify_attestation_bundle,
    load_attestation_sidecar,
    save_attestation_sidecar,
)
from .fingerprint import (
    FingerprintLookupPolicy,
    FingerprintLookupReceipt,
    FingerprintPreprocessPolicy,
    FingerprintRecord,
    FingerprintRegistry,
    RegistryMatch,
    VideoFingerprint,
    compute_video_fingerprint,
)
from .provenance import ProvenanceRoot, build_provenance_root, verify_provenance_root
from .workflow_contracts import WORKFLOW_OUTPUT_SCHEMAS
from .watermark_receipt import (
    CalibratedThresholdDetector,
    DetectorAlignmentScore,
    DetectorCalibration,
    DetectorReceipt,
    KeyedTemplateDetector,
    WatermarkReceiptPolicy,
    WatermarkVerificationReport,
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
    registry_roundtrip_valid: bool | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": WORKFLOW_OUTPUT_SCHEMAS["provenance"],
            "workflow": "provenance",
            "root": self.root.to_dict(),
            "sidecar": self.sidecar.to_dict(),
            "verified": self.verified,
            "embedded_payload_valid": self.embedded_payload_valid,
            "embedded_payload_tamper_detected": self.embedded_payload_tamper_detected,
            "manifest_tamper_detected": self.manifest_tamper_detected,
            "attached_manifest": self.attached_manifest.to_dict() if self.attached_manifest else None,
            "sidecar_roundtrip_valid": self.sidecar_roundtrip_valid,
            "registry_roundtrip_valid": self.registry_roundtrip_valid,
        }


@dataclass(frozen=True)
class FingerprintWorkflowResult:
    policy: FingerprintPreprocessPolicy
    lookup_policy: FingerprintLookupPolicy
    fingerprint: VideoFingerprint
    registry: FingerprintRegistry
    match: RegistryMatch
    receipt: FingerprintLookupReceipt

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": WORKFLOW_OUTPUT_SCHEMAS["fingerprint"],
            "workflow": "fingerprint",
            "policy": self.policy.to_dict(),
            "lookup_policy": self.lookup_policy.to_dict(),
            "fingerprint": self.fingerprint.to_dict(),
            "registry_commitment": self.registry.commitment(),
            "match": self.match.to_dict(),
            "receipt": self.receipt.to_dict(),
        }


@dataclass(frozen=True)
class WatermarkWorkflowResult:
    detector: KeyedTemplateDetector
    receipt_policy: WatermarkReceiptPolicy
    calibration: DetectorCalibration | None
    fixed_receipt: DetectorReceipt
    resynchronized_receipt: DetectorReceipt
    resynchronized_alignment: DetectorAlignmentScore
    verification_report: WatermarkVerificationReport
    claim_scope: tuple[str, ...]
    out_of_scope: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": WORKFLOW_OUTPUT_SCHEMAS["watermark"],
            "workflow": "watermark",
            "detector": self.detector.public_config(),
            "detector_commitment": self.detector.commitment,
            "receipt_policy": self.receipt_policy.to_dict(),
            "calibration": self.calibration.to_dict() if self.calibration else None,
            "fixed_receipt": self.fixed_receipt.to_dict(),
            "resynchronized_receipt": self.resynchronized_receipt.to_dict(),
            "resynchronized_alignment": self.resynchronized_alignment.to_dict(),
            "verification_report": self.verification_report.to_dict(),
            "claim_scope": list(self.claim_scope),
            "out_of_scope": list(self.out_of_scope),
        }


@dataclass(frozen=True)
class AttestationWorkflowResult:
    bundle: AttestationBundle
    signed_attestation: SignedAttestation
    sidecar: AttestationSidecar
    signature_valid: bool
    verifier_public_key: str | None = None
    verification_policy: AttestationVerificationPolicy | None = None
    verification_report: AttestationVerificationReport | None = None
    sidecar_roundtrip_valid: bool | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": WORKFLOW_OUTPUT_SCHEMAS["attestation"],
            "workflow": "attestation",
            "bundle": self.bundle.to_dict(),
            "signed_attestation": self.signed_attestation.to_dict(),
            "sidecar": self.sidecar.to_dict(),
            "signature_valid": self.signature_valid,
            "verifier_public_key": self.verifier_public_key,
            "verification_policy": self.verification_policy.to_dict() if self.verification_policy else None,
            "verification_report": self.verification_report.to_dict() if self.verification_report else None,
            "sidecar_roundtrip_valid": self.sidecar_roundtrip_valid,
        }


def provenance_workflow(
    manifest: str | Path | dict[str, Any],
    *,
    registry_uri: str,
    media_path: str | Path | None = None,
    stego_manifest: StegoManifest | None = None,
    sidecar_path: str | Path | None = None,
    registry_path: str | Path | None = None,
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
    registry_roundtrip_valid: bool | None = None
    if registry_path is not None:
        registry = ProvenanceRegistry()
        registry.publish(manifest_dict, registry_uri=registry_uri, media_path=media_path)
        registry.save(registry_path)
        loaded_registry = ProvenanceRegistry.load(registry_path)
        registry_roundtrip_valid = loaded_registry.verify_anchor(
            sidecar,
            media_path=media_path,
            embedded_payload=embedded_payload,
        )

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
        registry_roundtrip_valid=registry_roundtrip_valid,
    )


def fingerprint_workflow(
    frames: Sequence[np.ndarray] | np.ndarray,
    records: Iterable[FingerprintRecord],
    *,
    policy: FingerprintPreprocessPolicy | None = None,
    threshold: int = 8,
    lookup_policy: FingerprintLookupPolicy | None = None,
) -> FingerprintWorkflowResult:
    """Compute a video fingerprint and match it against a private registry."""
    policy = policy or FingerprintPreprocessPolicy()
    lookup_policy = lookup_policy or FingerprintLookupPolicy(threshold=threshold)
    registry = FingerprintRegistry(records, default_policy=lookup_policy)
    fingerprint = compute_video_fingerprint(frames, policy=policy)
    receipt = registry.lookup_with_receipt(
        fingerprint.fingerprint_hex,
        bit_count=fingerprint.bit_count,
        policy=lookup_policy,
    )
    return FingerprintWorkflowResult(
        policy=policy,
        lookup_policy=lookup_policy,
        fingerprint=fingerprint,
        registry=registry,
        match=receipt.match,
        receipt=receipt,
    )


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
    threshold_source = "provided"
    if threshold is None:
        if positive_clips is None or negative_clips is None:
            raise ValueError("either threshold or calibration clips must be provided")
        calibration = detector.calibrate_resynchronized(positive_clips, negative_clips, crop_margins=crop_margins)
        threshold = calibration.threshold
        threshold_source = "calibrated"

    fixed_policy = WatermarkReceiptPolicy(
        scoring_mode="fixed",
        threshold_source=threshold_source,
        crop_margins=tuple(int(value) for value in crop_margins),
    )
    receipt_policy = WatermarkReceiptPolicy(
        scoring_mode="resynchronized",
        threshold_source=threshold_source,
        crop_margins=tuple(int(value) for value in crop_margins),
    )
    fixed_receipt = detector.receipt(
        frames,
        threshold=threshold,
        payload_commitment=payload_commitment,
        policy=fixed_policy,
    )
    resynchronized_receipt = detector.receipt_resynchronized(
        frames,
        threshold=threshold,
        payload_commitment=payload_commitment,
        crop_margins=crop_margins,
        policy=receipt_policy,
    )
    aligned = resynchronized_receipt.alignment or detector.score_resynchronized(frames, crop_margins=crop_margins)
    verification_report = detector.verify_receipt(
        frames,
        resynchronized_receipt,
        policy=receipt_policy,
        payload_commitment=payload_commitment,
    )
    return WatermarkWorkflowResult(
        detector=detector,
        receipt_policy=receipt_policy,
        calibration=calibration,
        fixed_receipt=fixed_receipt,
        resynchronized_receipt=resynchronized_receipt,
        resynchronized_alignment=aligned,
        verification_report=verification_report,
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
    signer: Any,
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
    verification_policy = AttestationVerificationPolicy(
        expected_signer_id=signed.signer_id,
        expected_scheme=signed.scheme,
        hardware_root=hardware_root,
        require_hardware_root=False,
        allow_software_only=True,
    )
    verification_report = verify_attestation_bundle(
        signer,
        signed,
        policy=verification_policy,
        sidecar=sidecar,
    )
    signature_valid = verification_report.signature_valid
    verifier_public_key = getattr(signer, "public_key_hex", None)
    sidecar_roundtrip_valid: bool | None = None
    if sidecar_path is not None:
        save_attestation_sidecar(sidecar, sidecar_path)
        loaded = load_attestation_sidecar(sidecar_path)
        sidecar_roundtrip_valid = verify_attestation_bundle(
            signer,
            loaded.signed_attestation,
            policy=verification_policy,
            sidecar=loaded,
        ).verified
        if provenance_root_hash is not None:
            sidecar_roundtrip_valid = sidecar_roundtrip_valid and loaded.provenance_root_hash == provenance_root_hash

    return AttestationWorkflowResult(
        bundle=bundle,
        signed_attestation=signed,
        sidecar=sidecar,
        signature_valid=signature_valid,
        verifier_public_key=verifier_public_key,
        verification_policy=verification_policy,
        verification_report=verification_report,
        sidecar_roundtrip_valid=sidecar_roundtrip_valid,
    )


def _load_json_file(path: str | Path) -> Any:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data


def _load_frames(path: str | Path) -> np.ndarray:
    loaded = np.load(path, allow_pickle=False)
    if loaded.ndim not in (3, 4):
        raise ValueError("frames .npy file must have shape T,H,W or T,H,W,C")
    return loaded


def _load_bytes(path: str | Path) -> bytes:
    return Path(path).read_bytes()


def _write_json(path: str | Path, data: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")


def _provenance_cli(args: argparse.Namespace) -> dict[str, Any]:
    manifest = _load_json_file(args.manifest)
    stego_manifest = StegoManifest.load(args.stego_manifest) if args.stego_manifest else None
    result = provenance_workflow(
        manifest,
        registry_uri=args.registry_uri,
        media_path=args.media_path,
        stego_manifest=stego_manifest,
        sidecar_path=args.sidecar_out,
        registry_path=args.registry_out,
    )
    output = result.to_dict()
    if args.output:
        _write_json(args.output, output)
    print(json.dumps(output, indent=2, ensure_ascii=True))
    return output


def _fingerprint_cli(args: argparse.Namespace) -> dict[str, Any]:
    frames = _load_frames(args.frames)
    records_data = _load_json_file(args.records)
    if isinstance(records_data, dict):
        registry = FingerprintRegistry.from_dict(records_data)
    elif isinstance(records_data, list):
        registry = FingerprintRegistry(FingerprintRecord.from_dict(record) for record in records_data)
    else:
        raise ValueError("fingerprint records must be a registry JSON object or a record list")
    policy = FingerprintPreprocessPolicy(
        sample_count=args.sample_count,
        hash_size=args.hash_size,
    )
    result = fingerprint_workflow(
        frames,
        registry.records,
        policy=policy,
        lookup_policy=FingerprintLookupPolicy(threshold=args.threshold),
    )
    output = result.to_dict()
    if args.output:
        _write_json(args.output, output)
    print(json.dumps(output, indent=2, ensure_ascii=True))
    return output


def _watermark_cli(args: argparse.Namespace) -> dict[str, Any]:
    frames = _load_frames(args.frames)
    positive_clips = [_load_frames(path) for path in args.positive] if args.positive else None
    negative_clips = [_load_frames(path) for path in args.negative] if args.negative else None
    if not args.key and not args.key_file:
        raise ValueError("either --key or --key-file must be provided")
    if args.threshold is None and (not positive_clips or not negative_clips):
        raise ValueError("calibration requires both --positive and --negative clips when --threshold is omitted")
    result = watermark_workflow(
        frames,
        key=_load_bytes(args.key_file) if args.key_file else args.key.encode("utf-8"),
        frame_shape=tuple(args.frame_shape),
        threshold=args.threshold,
        positive_clips=positive_clips,
        negative_clips=negative_clips,
        grid_size=args.grid_size,
        crop_margins=tuple(args.crop_margins),
        payload_commitment=args.payload_commitment,
    )
    output = result.to_dict()
    if args.output:
        _write_json(args.output, output)
    print(json.dumps(output, indent=2, ensure_ascii=True))
    return output


def _attestation_cli(args: argparse.Namespace) -> dict[str, Any]:
    if not args.signer_key and not args.signer_key_file:
        raise ValueError("either --signer-key or --signer-key-file must be provided")
    signer_key = _load_bytes(args.signer_key_file) if args.signer_key_file else args.signer_key.encode("utf-8")
    signer_id = args.signer_id or ("ed25519-v1" if args.signer_scheme == "ed25519" else "mock-tee-v1")
    if args.signer_scheme == "mock-hmac":
        signer = MockTEESigner(signer_key, signer_id=signer_id)
    elif args.signer_scheme == "ed25519":
        try:
            key_text = signer_key.decode("ascii").strip()
            if len(key_text) == 64:
                try:
                    signer = Ed25519AttestationSigner(key_text, signer_id=signer_id)
                except ValueError:
                    signer = Ed25519AttestationSigner.from_seed(signer_key, signer_id=signer_id)
            else:
                signer = Ed25519AttestationSigner.from_seed(signer_key, signer_id=signer_id)
        except UnicodeDecodeError:
            signer = Ed25519AttestationSigner.from_seed(signer_key, signer_id=signer_id)
    else:
        raise ValueError(f"unsupported signer scheme: {args.signer_scheme}")
    bundle = None
    if args.bundle:
        bundle_data = _load_json_file(args.bundle)
        bundle = AttestationBundle(
            video_hash=str(bundle_data["video_hash"]),
            model_config_hash=str(bundle_data["model_config_hash"]),
            model_binary_hash=str(bundle_data["model_binary_hash"]),
            policy_id=str(bundle_data["policy_id"]),
            timestamp=str(bundle_data["timestamp"]),
            hardware_root=bundle_data.get("hardware_root"),
        )
    result = attestation_workflow(
        signer=signer,
        bundle=bundle,
        video_path=args.video_path,
        model_config_path=args.model_config_path,
        model_binary_path=args.model_binary_path,
        policy_id=args.policy_id,
        timestamp=args.timestamp,
        hardware_root=args.hardware_root,
        provenance_root_hash=args.provenance_root_hash,
        sidecar_path=args.sidecar_out,
    )
    output = result.to_dict()
    if args.output:
        _write_json(args.output, output)
    print(json.dumps(output, indent=2, ensure_ascii=True))
    return output


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run ready-to-use trust workflows")
    subparsers = parser.add_subparsers(dest="command", required=True)

    provenance = subparsers.add_parser("provenance", help="Run provenance anchor workflow")
    provenance.add_argument("--manifest", required=True, help="Path to manifest JSON")
    provenance.add_argument("--registry-uri", required=True, help="Registry URI for the manifest")
    provenance.add_argument("--media-path", help="Optional media path used in the root hash")
    provenance.add_argument("--stego-manifest", help="Optional stego manifest to attach the anchor to")
    provenance.add_argument("--sidecar-out", help="Optional path to save the audit sidecar JSON")
    provenance.add_argument("--registry-out", help="Optional path to save a local provenance registry JSON")
    provenance.add_argument("--output", help="Optional path to save workflow output JSON")
    provenance.set_defaults(func=_provenance_cli)

    fingerprint = subparsers.add_parser("fingerprint", help="Run fingerprint registry workflow")
    fingerprint.add_argument("--frames", required=True, help="Path to .npy luma frames")
    fingerprint.add_argument("--records", required=True, help="Path to registry records JSON array")
    fingerprint.add_argument("--sample-count", type=int, default=4)
    fingerprint.add_argument("--hash-size", type=int, default=8)
    fingerprint.add_argument("--threshold", type=int, default=8)
    fingerprint.add_argument("--output", help="Optional path to save workflow output JSON")
    fingerprint.set_defaults(func=_fingerprint_cli)

    watermark = subparsers.add_parser("watermark", help="Run watermark receipt workflow")
    watermark.add_argument("--frames", required=True, help="Path to .npy luma frames")
    watermark.add_argument("--key", help="ASCII key for the detector")
    watermark.add_argument("--key-file", help="Binary key file for the detector")
    watermark.add_argument("--frame-shape", nargs=2, type=int, required=True, metavar=("H", "W"))
    watermark.add_argument("--threshold", type=float)
    watermark.add_argument("--positive", nargs="*", default=[], help="Positive .npy clips for calibration")
    watermark.add_argument("--negative", nargs="*", default=[], help="Negative .npy clips for calibration")
    watermark.add_argument("--grid-size", type=int, default=8)
    watermark.add_argument("--crop-margins", nargs="*", type=int, default=[0, 4, 8, 12])
    watermark.add_argument("--payload-commitment", help="Optional payload commitment")
    watermark.add_argument("--output", help="Optional path to save workflow output JSON")
    watermark.set_defaults(func=_watermark_cli)

    attestation = subparsers.add_parser("attestation", help="Run attestation workflow")
    attestation.add_argument("--signer-scheme", choices=["mock-hmac", "ed25519"], default="mock-hmac")
    attestation.add_argument("--signer-key", help="ASCII signer key")
    attestation.add_argument("--signer-key-file", help="Binary signer key file")
    attestation.add_argument("--signer-id")
    attestation.add_argument("--bundle", help="Optional bundle JSON with hash fields")
    attestation.add_argument("--video-path", help="Path to video file")
    attestation.add_argument("--model-config-path", help="Path to model config file")
    attestation.add_argument("--model-binary-path", help="Path to model binary file")
    attestation.add_argument("--policy-id", help="Policy identifier")
    attestation.add_argument("--timestamp", help="ISO-8601 timestamp")
    attestation.add_argument("--hardware-root", help="Optional hardware root string")
    attestation.add_argument("--provenance-root-hash", help="Optional provenance root hash")
    attestation.add_argument("--sidecar-out", help="Optional path to save the attestation sidecar JSON")
    attestation.add_argument("--output", help="Optional path to save workflow output JSON")
    attestation.set_defaults(func=_attestation_cli)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
