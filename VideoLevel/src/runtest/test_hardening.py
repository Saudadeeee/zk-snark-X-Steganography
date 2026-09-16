"""Regression tests for security and reproducibility hardening.

These tests intentionally avoid benchmark assets.  They cover the public
contracts that must remain safe in a clean checkout and in CI.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtest._helpers import run_test, section, summarise


def t_analysis_cache_never_deserializes_pickle() -> None:
    import src.core.analysis_cache as cache

    source = inspect.getsource(cache)
    assert "pickle.load" not in source, "persistent cache must not deserialize pickle"


def t_manifest_uses_ed25519_and_binds_sidecars() -> None:
    from src.manifest import (
        EmbeddingMetadata,
        PayloadMetadata,
        ProofMetadata,
        StegoManifest,
        VideoMetadata,
        hash_positions,
    )
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    positions = [(1, 2, 3), (4, 5, 6)]
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    manifest = StegoManifest(
        payload=PayloadMetadata(message_length=3, bits_embedded=64, bits_required=64),
        embedding=EmbeddingMetadata(positions_count=2, positions_hash=hash_positions(positions)),
        video=VideoMetadata(
            file_path="cover.h264",
            file_hash="cover-hash",
            stego_file_hash="stego-hash",
        ),
        proof=ProofMetadata(proof_size_bytes=129, constraint_count=1),
    )

    manifest.sign(private_key)
    assert manifest.signature_algorithm == "ed25519"
    assert manifest.verify_signature(public_key)
    assert manifest.embedding.positions_hash == hash_positions(positions)

    manifest.video.stego_file_hash = "tampered"
    assert not manifest.verify_signature(public_key)
    try:
        hash_positions([(1, 2, 3.5)])
    except ValueError:
        pass
    else:
        raise AssertionError("position hashes must reject non-integer sidecar values")


def t_supported_stream_classifier_rejects_unsupported_codecs() -> None:
    from src.stream_profile import classify_h264_stream_parameters

    baseline = classify_h264_stream_parameters(profile_idc=66, cabac_enabled=False)
    assert baseline.profile == "baseline"
    assert baseline.entropy_mode == "cavlc"
    assert baseline.supported

    for profile_idc, cabac_enabled in ((77, True), (100, True), (66, True)):
        profile = classify_h264_stream_parameters(
            profile_idc=profile_idc,
            cabac_enabled=cabac_enabled,
        )
        assert not profile.supported


def t_circuit_declares_enforced_payload_length_range() -> None:
    circuit = (Path(__file__).resolve().parents[2] / "circuits" / "payload_verify.circom").read_text(encoding="utf-8")
    assert "LessThan(20)" in circuit
    assert "GreaterThan(20)" in circuit
    assert "length_in_range === 1" in circuit


def t_circuit_rejects_out_of_range_payload_lengths() -> None:
    from src.zk_proof import ZKSnarkBridge

    bridge = ZKSnarkBridge(str(ROOT / "circuits"))
    valid_input = bridge._build_circuit_input(b"x", bytes(range(32)))
    for invalid_length in (0, 1_000_000):
        invalid_input = dict(valid_input)
        invalid_input["payload_length"] = invalid_length
        try:
            bridge._compute_witness(invalid_input)
        except RuntimeError:
            continue
        raise AssertionError(f"payload_length={invalid_length} unexpectedly produced a valid witness")


def t_verifier_mode_key_contracts_are_unambiguous() -> None:
    from src.verify_modes import verify_nearblind, verify_strict

    assert "manifest_public_key" not in inspect.signature(verify_strict).parameters
    assert inspect.signature(verify_nearblind).parameters["manifest_public_key"].default is inspect.Parameter.empty


def main() -> None:
    section("Hardening - security and reproducibility contracts")
    results = [
        run_test("analysis_cache_never_deserializes_pickle", t_analysis_cache_never_deserializes_pickle),
        run_test("manifest_uses_ed25519_and_binds_sidecars", t_manifest_uses_ed25519_and_binds_sidecars),
        run_test("supported_stream_classifier_rejects_unsupported_codecs", t_supported_stream_classifier_rejects_unsupported_codecs),
        run_test("circuit_declares_enforced_payload_length_range", t_circuit_declares_enforced_payload_length_range),
        run_test("circuit_rejects_out_of_range_payload_lengths", t_circuit_rejects_out_of_range_payload_lengths),
        run_test("verifier_mode_key_contracts_are_unambiguous", t_verifier_mode_key_contracts_are_unambiguous),
    ]
    raise SystemExit(summarise(results, "Hardening"))


if __name__ == "__main__":
    main()
