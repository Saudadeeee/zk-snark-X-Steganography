"""Future trust architecture interface tests.

These tests cover experimental future-branch modules only. They are not part of
the frozen paper-grade runtime phases unless explicitly added later.
"""

import os
import json
import subprocess
import sys
import tempfile
from pathlib import Path

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
    CalibratedThresholdDetector,
    FingerprintRecord,
    FingerprintRegistry,
    FingerprintPreprocessPolicy,
    KeyedTemplateDetector,
    MockTEESigner,
    TinyThresholdDetector,
    ZKMLInterfaceSpec,
    attestation_workflow,
    build_provenance_root,
    compute_framehash,
    compute_video_fingerprint,
    extract_tiny_video_features,
    fingerprint_workflow,
    load_attestation_sidecar,
    provenance_workflow,
    sample_frame_indices,
    save_attestation_sidecar,
    verify_provenance_root,
    watermark_workflow,
)
from src.manifest import StegoManifest, VideoMetadata
from benchmark.trust_corpus import build_external_file_entry, validate_trust_corpus_manifest


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


def t_calibrated_detector_selects_threshold():
    detector = CalibratedThresholdDetector([1.0, 1.0])
    calibration = detector.calibrate(
        positive_features=[[0.7, 0.7], [0.8, 0.6]],
        negative_features=[[0.1, 0.2], [0.2, 0.2]],
    )
    assert calibration.accuracy == 1.0
    assert calibration.true_accept_rate == 1.0
    assert calibration.false_accept_rate == 0.0


def t_keyed_template_detector_separates_embedded_clip():
    base = np.stack(
        [
            np.tile(np.linspace(32 + i * 6, 220 + i * 6, 32, dtype=np.float32), (32, 1))
            for i in range(4)
        ]
    )
    detector = KeyedTemplateDetector(b"unit-test-key", frame_shape=(32, 32), grid_size=8)
    embedded = detector.embed(base, strength=9.0)
    calibration = detector.calibrate(positive_clips=[embedded], negative_clips=[base])
    receipt = detector.receipt(embedded, threshold=calibration.threshold)
    assert detector.score(embedded) > detector.score(base)
    assert receipt.valid
    assert calibration.true_accept_rate == 1.0
    assert calibration.false_accept_rate == 0.0
    assert b"unit-test-key".hex() not in detector.commitment


def t_keyed_template_detector_resynchronizes_cropped_clip():
    base = np.stack(
        [
            np.tile(np.linspace(32 + i * 8, 220 + i * 8, 64, dtype=np.float32), (64, 1))
            for i in range(8)
        ]
    )
    detector = KeyedTemplateDetector(b"upgrade-v2-watermark-key", frame_shape=(64, 64), grid_size=8)
    embedded = detector.embed(base, strength=8.0)
    cropped = embedded[:, 8:56, 8:56]
    y_idx = (np.arange(64) * cropped.shape[1] / 64).astype(int)
    x_idx = (np.arange(64) * cropped.shape[2] / 64).astype(int)
    cropped_resized = cropped[:, y_idx[:, None], x_idx[None, :]]
    aligned = detector.score_resynchronized(cropped_resized, crop_margins=(0, 4, 8, 12))
    assert aligned.score >= detector.score(cropped_resized)
    assert aligned.alignment != "center_crop_resize_margin_0"
    assert aligned.candidate_count == 4


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


def t_ready_to_use_trust_workflows():
    root_dir = os.path.join(os.path.dirname(__file__), "..", "..")
    out_dir = os.path.join(root_dir, "data", "output")
    manifest = {
        "claim_generator": "workflow-test",
        "assertions": [{"label": "canonical_asset", "value": "asset-1"}],
    }
    stego_manifest = StegoManifest(video=VideoMetadata(file_path="input.h264", file_hash="00" * 32))
    c2pa_path = os.path.join(out_dir, "_test_workflow_c2pa.json")
    registry_path = os.path.join(out_dir, "_test_workflow_registry.json")
    receipt_path = os.path.join(out_dir, "_test_workflow_receipt.json")
    attestation_path = os.path.join(out_dir, "_test_workflow_attestation.json")
    model_config_path = os.path.join(out_dir, "_test_model_config.json")
    model_binary_path = os.path.join(out_dir, "_test_model.bin")
    video_path = os.path.join(out_dir, "_test_video.bin")
    try:
        provenance = provenance_workflow(
            manifest,
            registry_uri="registry://workflow/asset-1",
            stego_manifest=stego_manifest,
            sidecar_path=c2pa_path,
        )
        assert provenance.verified
        assert provenance.embedded_payload_tamper_detected
        assert provenance.manifest_tamper_detected
        assert provenance.attached_manifest.video.provenance_root_hash == provenance.root.manifest_root_hash
        assert provenance.sidecar_roundtrip_valid

        frames = np.stack([np.full((32, 32), i, dtype=np.float32) for i in range(6)])
        policy = FingerprintPreprocessPolicy(sample_count=3, hash_size=8)
        fp = compute_video_fingerprint(frames, policy=policy)
        record = FingerprintRecord("canonical-asset-1", fp.fingerprint_hex, bit_count=fp.bit_count)
        fingerprint = fingerprint_workflow(frames, [record], policy=policy, threshold=0)
        assert fingerprint.match.matched
        assert fingerprint.match.record_id == "canonical-asset-1"
        fingerprint.registry.save(registry_path)
        loaded_registry = FingerprintRegistry.load(registry_path)
        assert loaded_registry.commitment() == fingerprint.registry.commitment()

        base = np.stack(
            [
                np.tile(np.linspace(32 + i * 8, 220 + i * 8, 64, dtype=np.float32), (64, 1))
                for i in range(8)
            ]
        )
        detector = KeyedTemplateDetector(b"upgrade-v2-watermark-key", frame_shape=(64, 64), grid_size=8)
        embedded = detector.embed(base, strength=8.0)
        watermark = watermark_workflow(
            embedded,
            key=b"upgrade-v2-watermark-key",
            frame_shape=(64, 64),
            positive_clips=[embedded],
            negative_clips=[base],
            payload_commitment=provenance.root.manifest_root_hash,
        )
        assert watermark.resynchronized_receipt.valid
        watermark.resynchronized_receipt.save(receipt_path)
        loaded_receipt = watermark.resynchronized_receipt.load(receipt_path)
        assert loaded_receipt.commitment() == watermark.resynchronized_receipt.commitment()

        with open(video_path, "wb") as f:
            f.write(b"video-bytes")
        with open(model_config_path, "w", encoding="utf-8") as f:
            f.write('{"model":"unit"}')
        with open(model_binary_path, "wb") as f:
            f.write(b"model-bytes")
        attestation = attestation_workflow(
            signer=MockTEESigner(b"workflow-key"),
            video_path=video_path,
            model_config_path=model_config_path,
            model_binary_path=model_binary_path,
            policy_id="workflow-policy-v1",
            timestamp="2026-06-09T00:00:00Z",
            provenance_root_hash=provenance.root.manifest_root_hash,
            sidecar_path=attestation_path,
        )
        assert attestation.signature_valid
        assert attestation.sidecar_roundtrip_valid
    finally:
        for path in (
            c2pa_path,
            registry_path,
            receipt_path,
            attestation_path,
            model_config_path,
            model_binary_path,
            video_path,
        ):
            if os.path.exists(path):
                os.remove(path)


def t_trust_workflows_cli_entrypoints():
    root_dir = Path(os.path.join(os.path.dirname(__file__), "..", "..")).resolve()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        manifest_path = tmp / "manifest.json"
        provenance_out = tmp / "provenance.json"
        provenance_sidecar = tmp / "provenance_sidecar.json"
        frames_path = tmp / "frames.npy"
        registry_path = tmp / "registry.json"
        fingerprint_out = tmp / "fingerprint.json"
        base_path = tmp / "base.npy"
        embedded_path = tmp / "embedded.npy"
        watermark_out = tmp / "watermark.json"
        video_path = tmp / "video.bin"
        model_config_path = tmp / "model.json"
        model_binary_path = tmp / "model.bin"
        attestation_out = tmp / "attestation.json"
        attestation_sidecar = tmp / "attestation_sidecar.json"

        manifest_path.write_text(
            json.dumps(
                {
                    "claim_generator": "cli-test",
                    "assertions": [{"label": "canonical_asset", "value": "asset-1"}],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        frames = np.stack([np.full((32, 32), i, dtype=np.float32) for i in range(6)])
        np.save(frames_path, frames, allow_pickle=False)
        fp_policy = FingerprintPreprocessPolicy(sample_count=3, hash_size=8)
        fp = compute_video_fingerprint(frames, policy=fp_policy)
        FingerprintRegistry([FingerprintRecord("canonical-asset-1", fp.fingerprint_hex, bit_count=fp.bit_count)]).save(
            registry_path
        )

        base = np.stack(
            [
                np.tile(np.linspace(32 + i * 8, 220 + i * 8, 64, dtype=np.float32), (64, 1))
                for i in range(8)
            ]
        )
        detector = KeyedTemplateDetector(b"upgrade-v2-watermark-key", frame_shape=(64, 64), grid_size=8)
        embedded = detector.embed(base, strength=8.0)
        np.save(base_path, base, allow_pickle=False)
        np.save(embedded_path, embedded, allow_pickle=False)

        video_path.write_bytes(b"video-bytes")
        model_config_path.write_text('{"model":"unit"}', encoding="utf-8")
        model_binary_path.write_bytes(b"model-bytes")

        def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
            completed = subprocess.run(
                [sys.executable, "-m", "src.trust.workflows", *args],
                cwd=root_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            assert completed.returncode == 0, (
                f"CLI failed for {' '.join(args)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
            )
            return completed

        provenance_run = run_cli(
            "provenance",
            "--manifest",
            str(manifest_path),
            "--registry-uri",
            "registry://cli-test/asset-1",
            "--sidecar-out",
            str(provenance_sidecar),
            "--output",
            str(provenance_out),
        )
        provenance_json = json.loads(provenance_out.read_text(encoding="utf-8"))
        assert provenance_json["verified"]
        assert provenance_json["embedded_payload_tamper_detected"]
        assert provenance_json["manifest_tamper_detected"]
        assert provenance_sidecar.exists()
        assert "verified" in provenance_run.stdout

        fingerprint_run = run_cli(
            "fingerprint",
            "--frames",
            str(frames_path),
            "--records",
            str(registry_path),
            "--sample-count",
            "3",
            "--hash-size",
            "8",
            "--threshold",
            "0",
            "--output",
            str(fingerprint_out),
        )
        fingerprint_json = json.loads(fingerprint_out.read_text(encoding="utf-8"))
        assert fingerprint_json["match"]["matched"]
        assert fingerprint_json["match"]["record_id"] == "canonical-asset-1"
        assert "registry_commitment" in fingerprint_run.stdout

        watermark_run = run_cli(
            "watermark",
            "--frames",
            str(embedded_path),
            "--key",
            "upgrade-v2-watermark-key",
            "--frame-shape",
            "64",
            "64",
            "--positive",
            str(embedded_path),
            "--negative",
            str(base_path),
            "--output",
            str(watermark_out),
        )
        watermark_json = json.loads(watermark_out.read_text(encoding="utf-8"))
        assert watermark_json["resynchronized_receipt"]["valid"]
        assert watermark_json["calibration"]["accuracy"] == 1.0
        assert "resynchronized_receipt" in watermark_run.stdout

        attestation_run = run_cli(
            "attestation",
            "--signer-key",
            "workflow-key",
            "--video-path",
            str(video_path),
            "--model-config-path",
            str(model_config_path),
            "--model-binary-path",
            str(model_binary_path),
            "--policy-id",
            "workflow-policy-v1",
            "--timestamp",
            "2026-06-09T00:00:00Z",
            "--provenance-root-hash",
            "dd" * 32,
            "--sidecar-out",
            str(attestation_sidecar),
            "--output",
            str(attestation_out),
        )
        attestation_json = json.loads(attestation_out.read_text(encoding="utf-8"))
        assert attestation_json["signature_valid"]
        assert attestation_json["sidecar_roundtrip_valid"]
        assert attestation_sidecar.exists()
        assert "signature_valid" in attestation_run.stdout


def t_trust_corpus_manifest_validator():
    current_manifest = {
        "schema": "trust-corpus-manifest-v1",
        "status": "local_curated",
        "description": "unit local manifest",
        "claim_scope": "local only",
        "external_public_dataset": False,
        "entries": [
            {
                "group": "registered_local_h264",
                "source": "benchmark._common.SEQUENCES",
                "selection": "all existing registered local H.264 assets",
                "use": ["fingerprint threshold sweep"],
            }
        ],
        "promotion_requirements": ["add external corpus"],
    }
    local_validation = validate_trust_corpus_manifest(current_manifest)
    assert local_validation["schema_valid"]
    assert not local_validation["promotion_ready"]
    assert "external_public_dataset is false" in local_validation["promotion_blockers"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        sample = tmp / "external_sample.h264"
        sample.write_bytes(b"external-video-bytes")
        external_manifest = {
            "schema": "trust-corpus-manifest-v1",
            "status": "external_curated",
            "description": "unit external manifest",
            "claim_scope": "external public corpus",
            "external_public_dataset": True,
            "entries": [
                {
                    "group": "external_public_video",
                    "source": "unit fixture",
                    "source_uri": "https://example.invalid/dataset",
                    "license": "unit-test-license",
                    "files": [
                        {
                            "id": "sample-1",
                            "path": "external_sample.h264",
                            "sha256": __import__("hashlib").sha256(b"external-video-bytes").hexdigest(),
                            "codec": "h264",
                            "container": "raw_h264",
                            "frame_count": 1,
                            "resolution": [16, 16],
                        }
                    ],
                }
            ],
            "promotion_requirements": ["unit complete"],
        }
        external_validation = validate_trust_corpus_manifest(external_manifest, root=tmp)
        assert external_validation["schema_valid"]
        assert external_validation["promotion_ready"]
        assert external_validation["external_file_count"] == 1
        assert external_validation["external_hash_match_count"] == 1

        generated_entry = build_external_file_entry(
            file_id="sample-1",
            path="external_sample.h264",
            source_uri="https://example.invalid/dataset",
            license_name="unit-test-license",
            codec="h264",
            container="raw_h264",
            frame_count=1,
            resolution="16x16",
            source="unit fixture",
            group="external_public_video",
            root=tmp,
        )
        assert generated_entry["files"][0]["sha256"] == external_manifest["entries"][0]["files"][0]["sha256"]
        assert generated_entry["files"][0]["resolution"] == "16x16"


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
        run_test("calibrated_detector_selects_threshold", t_calibrated_detector_selects_threshold),
        run_test("keyed_template_detector_separates_embedded_clip", t_keyed_template_detector_separates_embedded_clip),
        run_test(
            "keyed_template_detector_resynchronizes_cropped_clip",
            t_keyed_template_detector_resynchronizes_cropped_clip,
        ),
        run_test("mock_tee_attestation_signature", t_mock_tee_attestation_signature),
        run_test("attestation_sidecar_roundtrip", t_attestation_sidecar_roundtrip),
        run_test("zkml_interface_is_explicit_stub", t_zkml_interface_is_explicit_stub),
        run_test("ready_to_use_trust_workflows", t_ready_to_use_trust_workflows),
        run_test("trust_workflows_cli_entrypoints", t_trust_workflows_cli_entrypoints),
        run_test("trust_corpus_manifest_validator", t_trust_corpus_manifest_validator),
    ]
    sys.exit(summarise(results, "Future Trust Architecture"))


if __name__ == "__main__":
    main()
