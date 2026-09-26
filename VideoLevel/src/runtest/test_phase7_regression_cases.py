"""
test_phase7_regression_cases.py - Regression fixtures for known weak cases.

Focuses on:
  1. verified legacy Groth16 all-intra operating-point verification
  2. near-threshold quality guard retention
  3. rejection of an unauthenticated legacy manifest by the current near-blind verifier
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.runtest._helpers import section, run_test, summarise, SKIP, get_circuits_dir
from src.verifier import verify
from src.verifier_blind import verify_near_blind
from src.manifest import MANIFEST_VERSION, StegoManifest


ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = ROOT / "benchmark" / "results"
OUTPUT_DIR = ROOT / "data" / "output"
ENCODED_DIR = ROOT / "data" / "encoded"
CIRCUITS_DIR = get_circuits_dir()

SECRET_KEY = bytes(range(32))
CHAOS_KEY = b"sec1_benchmark_chaos_v1"
REAL_PROOF_MESSAGE = b"ZK-bench-v1.0!"
LEGACY_STEGO = OUTPUT_DIR / "sec1_stego_deadline_q22_g1_600f.h264"
LEGACY_ORIGINAL = ENCODED_DIR / "deadline_cif_q22_g1_600f.h264"
LEGACY_POSITIONS = Path(f"{LEGACY_STEGO}.positions.json")
LEGACY_MANIFEST = Path(f"{LEGACY_STEGO}.manifest.json")


def _load_positions(path: Path) -> list[tuple[int, int, int]]:
    return [tuple(int(v) for v in row) for row in json.loads(path.read_text(encoding="utf-8"))]


def _sec1_artifact_verified(stego: Path) -> bool:
    meta_path = Path(f"{stego}.meta.json")
    if not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return meta.get("verify_valid") is True and meta.get("verify_message_match") is True


def t_verified_all_intra_operating_point():
    stego = LEGACY_STEGO
    original = LEGACY_ORIGINAL
    pos_path = LEGACY_POSITIONS
    if not stego.exists() or not original.exists() or not pos_path.exists():
        SKIP("verified_all_intra_operating_point", "required SEC1 artifact missing")
        return
    if not _sec1_artifact_verified(stego):
        SKIP("verified_all_intra_operating_point", "SEC1 artifact is not verified")
        return

    positions = _load_positions(pos_path)
    result = verify(
        stego_video_path=str(stego),
        original_video_path=str(original),
        circuits_dir=CIRCUITS_DIR,
        secret_key=SECRET_KEY,
        message_length=len(REAL_PROOF_MESSAGE),
        chaos_key=CHAOS_KEY,
        proof_backend="groth16",
        precomputed_positions=positions,
        precomputed_payload_bits=len(positions),
        use_analysis_cache=True,
    )
    assert result.valid, "verified SEC1 artifact should re-verify"
    assert result.message == REAL_PROOF_MESSAGE, "verified SEC1 message mismatch"


def t_near_threshold_quality_guard_retention():
    sec1_json = RESULTS_DIR / "sec1_quality_data.json"
    if not sec1_json.exists():
        SKIP("near_threshold_quality_guard_retention", "sec1_quality_data.json missing")
        return

    payload = json.loads(sec1_json.read_text(encoding="utf-8"))
    data = payload.get("data", payload)
    seq = "akiyo_q22_g1"
    if seq not in data:
        SKIP("near_threshold_quality_guard_retention", f"{seq} not present in sec1 results")
        return

    row = data[seq]
    assert row.get("payload_target_met") is True, "near-threshold asset must still meet payload target"
    min_psnr = float(row.get("min_modified_frame_psnr", 0.0))
    assert min_psnr >= 40.0, f"near-threshold asset dropped below guard: {min_psnr:.2f} dB"
    assert min_psnr >= 40.0, f"quality-guard fixture is invalid: {min_psnr:.2f} dB"


def t_legacy_near_blind_artifacts_are_not_trusted():
    stego = LEGACY_STEGO
    manifest = LEGACY_MANIFEST
    pos_path = LEGACY_POSITIONS
    if not stego.exists() or not manifest.exists() or not pos_path.exists():
        SKIP("legacy_near_blind_artifacts_are_not_trusted", "required SEC1 sidecar artifact missing")
        return
    if not _sec1_artifact_verified(stego):
        SKIP("legacy_near_blind_artifacts_are_not_trusted", "SEC1 artifact is not verified")
        return
    artifact_manifest = StegoManifest.load(str(manifest))
    assert artifact_manifest.version != MANIFEST_VERSION, (
        "legacy benchmark sidecar unexpectedly claims the authenticated manifest schema"
    )
    try:
        verify_near_blind(
            stego_video_path=str(stego),
            circuits_dir=str(CIRCUITS_DIR),
            secret_key=SECRET_KEY,
            message_length=len(REAL_PROOF_MESSAGE),
            manifest_public_key=bytes(32),
            chaos_key=CHAOS_KEY,
        )
    except RuntimeError as error:
        assert "Manifest signature verification failed" in str(error), (
            f"legacy artifact rejected for an unexpected reason: {error}"
        )
    else:
        raise AssertionError("near-blind verifier accepted an unauthenticated legacy manifest")


def main():
    section("Phase 7 - Regression Cases")
    results = [
        run_test("verified_all_intra_operating_point", t_verified_all_intra_operating_point),
        run_test("near_threshold_quality_guard_retention", t_near_threshold_quality_guard_retention),
        run_test("legacy_near_blind_artifacts_are_not_trusted", t_legacy_near_blind_artifacts_are_not_trusted),
    ]
    sys.exit(summarise(results, "Phase 7"))


if __name__ == "__main__":
    main()
