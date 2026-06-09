"""
test_phase6_near_blind_manifest.py - Phase 6: Near-blind verification and manifest integrity.

Tests:
  1. manifest_hmac_roundtrip      - sign/verify works and tamper is detected
  2. near_blind_verify_pipeline   - embed with sidecars and verify without original video
"""

import os
import sys
import json
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.runtest._helpers import (
    section,
    run_test,
    summarise,
    SKIP,
    get_video,
    get_output,
    get_circuits_dir,
    node_available,
)

from src.embedder import embed
from src.exceptions import InsufficientCapacityError
from src.manifest import (
    EmbeddingMetadata,
    PayloadMetadata,
    ProofMetadata,
    StegoManifest,
    VideoMetadata,
)
from src.verifier_blind import verify_near_blind
from benchmark._common import load_sec1_positions
from benchmark.locked_operating_contract import (
    LOCKED_MESSAGE,
    LOCKED_SECRET_KEY,
    LOCKED_CHAOS_KEY,
    load_best_locked_operating_contract,
)


SCAN_JSON = Path(__file__).resolve().parent.parent.parent / "benchmark" / "results" / "patchable_capacity_scan.json"
CIRCUITS_DIR = get_circuits_dir()
SECRET_KEY = LOCKED_SECRET_KEY
SIGNING_KEY = b"manifest-signing-key-v1"
TEST_MSG = LOCKED_MESSAGE
VIDEO_CANDIDATES = [
    get_video("deadline_cif_q22_g1.h264"),
    get_video("coastguard_cif_q22_g1_1000f.h264"),
    get_video("coastguard_cif_q22_g1.h264"),
    get_video("foreman_cif_q22_g1.h264"),
]


def _select_video() -> str:
    required_bits = 1232
    contract = load_best_locked_operating_contract(required_bits=required_bits)
    if contract is not None:
        return contract.video_path

    if SCAN_JSON.exists():
        try:
            cached = json.loads(SCAN_JSON.read_text(encoding="utf-8"))
            scan_data = cached.get("data", cached)
            ranked = []
            for _seq_name, row in scan_data.items():
                video_path = row.get("video_path")
                usable = int(row.get("patchable_usable_bits") or 0)
                if video_path and os.path.isfile(video_path):
                    ranked.append((usable, str(video_path)))
            ranked.sort(reverse=True)
            for usable, video_path in ranked:
                if usable >= required_bits:
                    return video_path
            if ranked:
                return ranked[0][1]
        except Exception:
            pass
    for video in VIDEO_CANDIDATES:
        if os.path.isfile(video):
            return video
    return get_video("foreman_cif_q22_g1.h264")


VIDEO = _select_video()


def _validated_pool_for_video(video: str) -> list[tuple[int, int, int]]:
    contract = load_best_locked_operating_contract(required_bits=1232)
    if contract is None:
        return []
    if os.path.abspath(contract.video_path) != os.path.abspath(video):
        return []
    return load_sec1_positions(contract.sequence_name, validated_pool=True)


def t_manifest_hmac_roundtrip():
    manifest = StegoManifest(
        payload=PayloadMetadata(message_length=4, bits_embedded=32, bits_required=32),
        embedding=EmbeddingMetadata(strategy="t1_sign_flip", positions_count=32),
        video=VideoMetadata(file_path="input.h264", file_hash="abc123"),
        proof=ProofMetadata(proof_system="groth16", proof_size_bytes=129, constraint_count=18680),
    )
    manifest.sign(SIGNING_KEY, signer_id="test-suite")

    assert manifest.signature is not None, "signature should be populated after sign()"
    assert manifest.verify_signature(SIGNING_KEY), "manifest HMAC verification should succeed"
    assert not manifest.verify_signature(b"wrong-key"), "manifest HMAC verification should fail for wrong key"

    manifest.payload.message_length = 5
    assert not manifest.verify_signature(SIGNING_KEY), "manifest tampering must invalidate the signature"


def t_near_blind_verify_pipeline():
    if not node_available():
        SKIP("near_blind_verify_pipeline", "node not found on PATH")
        return

    out = get_output("test_p6_near_blind.h264")
    try:
        candidate_pool = _validated_pool_for_video(VIDEO)
        try:
            embed(
                video_path=VIDEO,
                message=TEST_MSG,
                output_path=out,
                circuits_dir=CIRCUITS_DIR,
                secret_key=SECRET_KEY,
                chaos_key=LOCKED_CHAOS_KEY,
                precomputed_positions=candidate_pool or None,
                trust_precomputed_positions=False,
                use_analysis_cache=True,
            )
        except InsufficientCapacityError:
            SKIP("near_blind_verify_pipeline", "selected asset lacks enough patchable capacity")
            return

        manifest_path = f"{out}.manifest.json"
        manifest = StegoManifest.load(manifest_path)
        manifest.sign(SIGNING_KEY, signer_id="test-suite")
        manifest.save(manifest_path)

        result = verify_near_blind(
            stego_video_path=out,
            circuits_dir=CIRCUITS_DIR,
            secret_key=SECRET_KEY,
            message_length=len(TEST_MSG),
            chaos_key=LOCKED_CHAOS_KEY,
            use_analysis_cache=True,
            manifest_signing_key=SIGNING_KEY,
        )
        assert result.valid, "near-blind verification should succeed on a fresh embed"
        assert result.message == TEST_MSG, f"unexpected extracted message: {result.message!r}"
    finally:
        for path in (
            out,
            f"{out}.positions.json",
            f"{out}.meta.json",
            f"{out}.manifest.json",
        ):
            if os.path.exists(path):
                os.remove(path)


def main():
    section("Phase 6 - Near-blind Verification & Manifest Integrity")
    results = [
        run_test("manifest_hmac_roundtrip", t_manifest_hmac_roundtrip),
        run_test("near_blind_verify_pipeline", t_near_blind_verify_pipeline),
    ]
    sys.exit(summarise(results, "Phase 6"))


if __name__ == "__main__":
    main()
