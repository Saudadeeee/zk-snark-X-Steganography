"""Future trust architecture interface tests.

These tests cover experimental future-branch modules only. They are not part of
the frozen paper-grade runtime phases unless explicitly added later.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.provenance import (
    attach_anchor_to_manifest,
    build_c2pa_anchor,
    load_audit_sidecar,
    save_audit_sidecar,
    verify_c2pa_anchor,
)
from src.runtest._helpers import run_test, section, summarise
from src.trust import (
    AttestationBundle,
    AttestationSidecar,
    FingerprintRecord,
    FingerprintRegistry,
    FingerprintPreprocessPolicy,
    MockTEESigner,
    TinyThresholdDetector,
    ZKMLInterfaceSpec,
    build_provenance_root,
    compute_framehash,
    compute_video_fingerprint,
    extract_tiny_video_features,
    load_attestation_sidecar,
    sample_frame_indices,
    save_attestation_sidecar,
    verify_provenance_root,
)
from src.manifest import StegoManifest, VideoMetadata


def t_provenance_root_detects_tamper():
    manifest = {"assertions": [{"label": "policy", "value": "anchor-v1"}]}
    root = build_provenance_root(manifest)
    assert verify_provenance_root(root, manifest), "root should verify original manifest"
    tampered = {"assertions": [{"label": "policy", "value": "anchor-v2"}]}
    assert not verify_provenance_root(root, tampered), "root should reject tampered manifest"


def t_c2pa_bridge_audit_sidecar_roundtrip():
    manifest = {"claim_generator": "unit-test", "assertions": [{"label": "root", "value": "ok"}]}
    sidecar = build_c2pa_anchor(manifest, registry_uri="registry://unit-test/manifest")
    assert len(sidecar.anchor.payload_bytes) == 32, "embedded root payload should be 32 bytes"
    assert verify_c2pa_anchor(sidecar, manifest, embedded_payload=sidecar.anchor.payload_bytes)
    assert not verify_c2pa_anchor(sidecar, manifest, embedded_payload=b"\x00" * 32)

    path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "output", "_test_c2pa_audit.json")
    try:
        save_audit_sidecar(sidecar, path)
        loaded = load_audit_sidecar(path)
        assert verify_c2pa_anchor(loaded, manifest), "loaded audit sidecar should verify"
    finally:
        if os.path.exists(path):
            os.remove(path)


def t_manifest_provenance_fields_roundtrip():
    manifest = StegoManifest(
        video=VideoMetadata(
            file_path="input.h264",
            file_hash="abc123",
            provenance_uri="registry://unit-test/manifest",
            provenance_root_hash="11" * 32,
        )
    )
    encoded = manifest.to_json()
    decoded = StegoManifest.from_json(encoded)
    assert decoded.video.provenance_uri == "registry://unit-test/manifest"
    assert decoded.video.provenance_root_hash == "11" * 32


def t_c2pa_anchor_attaches_to_manifest():
    manifest = StegoManifest(video=VideoMetadata(file_path="input.h264", file_hash="abc123"))
    sidecar = build_c2pa_anchor({"claim_generator": "unit-test"}, registry_uri="registry://unit-test/manifest")
    attached = attach_anchor_to_manifest(manifest, sidecar)
    assert attached.video.provenance_uri == "registry://unit-test/manifest"
    assert attached.video.provenance_root_hash == sidecar.anchor.root.manifest_root_hash


def t_fingerprint_registry_threshold_match():
    frame = np.arange(64 * 64, dtype=np.float32).reshape(64, 64)
    fingerprint = compute_framehash(frame)
    registry = FingerprintRegistry([FingerprintRecord("clip-1", fingerprint)])
    match = registry.lookup(fingerprint, threshold=0)
    assert match.matched, "exact fingerprint should match"
    assert match.record_id == "clip-1", "registry returned wrong record"


def t_video_fingerprint_policy_is_deterministic():
    frames = np.stack([np.full((32, 32), i, dtype=np.float32) for i in range(6)])
    policy = FingerprintPreprocessPolicy(sample_count=3, hash_size=8)
    first = compute_video_fingerprint(frames, policy=policy)
    second = compute_video_fingerprint(frames, policy=policy)
    assert first.fingerprint_hex == second.fingerprint_hex
    assert first.sample_indices == sample_frame_indices(6, 3)
    assert first.bit_count == 64


def t_watermark_receipt_threshold():
    detector = TinyThresholdDetector([0.5, 0.5])
    receipt = detector.receipt([1.0, 1.0], threshold=0.9)
    assert receipt.valid, "detector score should cross threshold"
    assert receipt.detector_commitment, "receipt should include detector commitment"


def t_tiny_video_features_are_circuit_sized():
    frames = np.stack([np.full((16, 16), i * 10, dtype=np.float32) for i in range(4)])
    features = extract_tiny_video_features(frames)
    assert len(features) == 4
    assert all(value >= 0.0 for value in features)


def t_mock_tee_attestation_signature():
    bundle = AttestationBundle(
        video_hash="aa" * 32,
        model_config_hash="bb" * 32,
        model_binary_hash="cc" * 32,
        policy_id="policy-v1",
        timestamp="2026-06-08T00:00:00Z",
    )
    signer = MockTEESigner(b"test-key")
    signed = signer.sign(bundle)
    assert signer.verify(signed), "mock TEE signature should verify"
    wrong = MockTEESigner(b"wrong-key")
    assert not wrong.verify(signed), "wrong key must not verify attestation"


def t_attestation_sidecar_roundtrip():
    bundle = AttestationBundle(
        video_hash="aa" * 32,
        model_config_hash="bb" * 32,
        model_binary_hash="cc" * 32,
        policy_id="policy-v1",
        timestamp="2026-06-08T00:00:00Z",
    )
    signer = MockTEESigner(b"test-key")
    sidecar = AttestationSidecar(
        signed_attestation=signer.sign(bundle),
        provenance_root_hash="dd" * 32,
    )
    path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "output", "_test_attestation.json")
    try:
        save_attestation_sidecar(sidecar, path)
        loaded = load_attestation_sidecar(path)
        assert loaded.provenance_root_hash == "dd" * 32
        assert signer.verify(loaded.signed_attestation), "loaded attestation should verify"
    finally:
        if os.path.exists(path):
            os.remove(path)


def t_zkml_interface_is_explicit_stub():
    spec = ZKMLInterfaceSpec(
        circuit_name="future_detector",
        public_outputs=("accepted",),
        private_inputs=("weights", "features"),
    )
    assert spec.validate_interface_only(), "ZKML spec should be interface-only"
    assert spec.status == "interface_only", "ZKML must not imply implementation"


def main():
    section("Future Trust Architecture Interfaces")
    results = [
        run_test("provenance_root_detects_tamper", t_provenance_root_detects_tamper),
        run_test("c2pa_bridge_audit_sidecar_roundtrip", t_c2pa_bridge_audit_sidecar_roundtrip),
        run_test("manifest_provenance_fields_roundtrip", t_manifest_provenance_fields_roundtrip),
        run_test("c2pa_anchor_attaches_to_manifest", t_c2pa_anchor_attaches_to_manifest),
        run_test("fingerprint_registry_threshold_match", t_fingerprint_registry_threshold_match),
        run_test("video_fingerprint_policy_is_deterministic", t_video_fingerprint_policy_is_deterministic),
        run_test("watermark_receipt_threshold", t_watermark_receipt_threshold),
        run_test("tiny_video_features_are_circuit_sized", t_tiny_video_features_are_circuit_sized),
        run_test("mock_tee_attestation_signature", t_mock_tee_attestation_signature),
        run_test("attestation_sidecar_roundtrip", t_attestation_sidecar_roundtrip),
        run_test("zkml_interface_is_explicit_stub", t_zkml_interface_is_explicit_stub),
    ]
    sys.exit(summarise(results, "Future Trust Architecture"))


if __name__ == "__main__":
    main()
