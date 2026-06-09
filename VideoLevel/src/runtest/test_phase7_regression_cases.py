"""
test_phase7_regression_cases.py - Regression fixtures for known weak cases.

Focuses on:
  1. verified all-intra operating-point verification
  2. near-threshold quality guard retention
  3. sidecar-assisted near-blind verification on an existing SEC1 artifact
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.runtest._helpers import section, run_test, summarise, SKIP, get_circuits_dir
from src.verifier import verify
from src.verifier_blind import verify_near_blind


ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = ROOT / "benchmark" / "results"
OUTPUT_DIR = ROOT / "data" / "output"
ENCODED_DIR = ROOT / "data" / "encoded"
CIRCUITS_DIR = get_circuits_dir()

SECRET_KEY = bytes(range(32))
CHAOS_KEY = b"sec1_benchmark_chaos_v1"
REAL_PROOF_MESSAGE = b"ZK-bench-v1.0!"


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
    stego = OUTPUT_DIR / "sec1_stego_akiyo_q22_g1.h264"
    original = ENCODED_DIR / "akiyo_cif_q22_g1.h264"
    pos_path = OUTPUT_DIR / "sec1_stego_akiyo_q22_g1.h264.positions.json"
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


def t_near_blind_existing_sec1_sidecar():
    stego = OUTPUT_DIR / "sec1_stego_akiyo_q22_g1.h264"
    manifest = OUTPUT_DIR / "sec1_stego_akiyo_q22_g1.h264.manifest.json"
    pos_path = OUTPUT_DIR / "sec1_stego_akiyo_q22_g1.h264.positions.json"
    if not stego.exists() or not manifest.exists() or not pos_path.exists():
        SKIP("near_blind_existing_sec1_sidecar", "required SEC1 sidecar artifact missing")
        return
    if not _sec1_artifact_verified(stego):
        SKIP("near_blind_existing_sec1_sidecar", "SEC1 artifact is not verified")
        return

    result = verify_near_blind(
        stego_video_path=str(stego),
        circuits_dir=CIRCUITS_DIR,
        secret_key=SECRET_KEY,
        message_length=len(REAL_PROOF_MESSAGE),
        chaos_key=CHAOS_KEY,
        use_analysis_cache=True,
    )
    assert result.valid, "existing SEC1 sidecar-assisted near-blind artifact should verify"
    assert result.message == REAL_PROOF_MESSAGE, "near-blind verified message mismatch"


def main():
    section("Phase 7 - Regression Cases")
    results = [
        run_test("verified_all_intra_operating_point", t_verified_all_intra_operating_point),
        run_test("near_threshold_quality_guard_retention", t_near_threshold_quality_guard_retention),
        run_test("near_blind_existing_sec1_sidecar", t_near_blind_existing_sec1_sidecar),
    ]
    sys.exit(summarise(results, "Phase 7"))


if __name__ == "__main__":
    main()
