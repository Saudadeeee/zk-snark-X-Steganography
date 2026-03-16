"""
ZK Benchmarks — §4.1: Proof Correctness Tests
===============================================
5 pass/fail tests verifying the Groth16 proof system is sound:

  1. Valid proof verifies correctly                       -> PASS
  2. Wrong publicImageHash in public signals              -> FAIL
  3. Tampered proof.json (flip one coefficient)           -> FAIL
  4. Proof from image A verified with image B's vkey      -> FAIL
  5. Extract with wrong chaos_key (hash mismatch)         -> fast FAIL before metadata revealed

Prerequisites:
  Run Benchmark/ZK/setup_circuit.py first.

Run:
    cd ImageLevel
    python Benchmark/ZK/correctness_tests.py
"""

import sys
import copy
import time
from pathlib import Path

BENCH_DIR   = Path(__file__).resolve().parent.parent
PROJECT_DIR = BENCH_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(BENCH_DIR))

from common import (
    list_dicom_files, load_dicom_cover,
    save_json, results_dir, CHAOS_KEY,
)

RDIR = results_dir("ZK")
BUILD = PROJECT_DIR / "circuits" / "compiled" / "build"


def _check_artifacts() -> bool:
    wasm = BUILD / "chaos_zk_stego_js" / "chaos_zk_stego.wasm"
    zkey = BUILD / "chaos_zk_stego.zkey"
    vkey = BUILD / "chaos_zk_stego_verification_key.json"
    missing = [f for f in (wasm, zkey, vkey) if not f.exists()]
    if missing:
        print("ERROR: ZK artifacts missing. Run Benchmark/ZK/setup_circuit.py first.")
        for f in missing:
            print(f"  Missing: {f}")
        return False
    return True


def run(verbose: bool = True) -> dict:
    if not _check_artifacts():
        return {"error": "artifacts_missing"}

    from src.zk_stego.dicom_handler import DicomStego
    from src.zk_stego.utils import SnarkJSRunner

    dcm_files = list_dicom_files()
    dcm_a = dcm_files[0]
    dcm_b = dcm_files[1] if len(dcm_files) > 1 else dcm_files[0]

    results = {}

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _embed_with_proof(dcm_path, out_png):
        ds = DicomStego()
        return ds.embed(str(dcm_path), str(out_png),
                        chaos_key=CHAOS_KEY, generate_zk_proof=True, verbose=False)

    def _verify(proof, public_inputs) -> bool:
        runner = SnarkJSRunner()
        return runner.verify_groth16_proof(proof, public_inputs)

    import tempfile, os

    # ── Test 1: Valid proof verifies ──────────────────────────────────────────
    print("\n[Test 1] Valid proof -> should PASS verification")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp1 = f.name
    try:
        t0 = time.perf_counter()
        r1 = _embed_with_proof(dcm_a, tmp1)
        embed_time = time.perf_counter() - t0

        t0 = time.perf_counter()
        ok1 = _verify(r1["proof"], r1["public_inputs"])
        verify_time = time.perf_counter() - t0

        status = "PASS" if ok1 else "FAIL (unexpected)"
        results["test1_valid_proof"] = {
            "expected": "PASS", "got": "PASS" if ok1 else "FAIL",
            "status": "OK" if ok1 else "FAIL",
            "embed_time_s":  round(embed_time,  3),
            "verify_time_s": round(verify_time, 3),
        }
        print(f"  Result: {status}  (embed={embed_time:.1f}s  verify={verify_time:.3f}s)")
    finally:
        if os.path.exists(tmp1): os.unlink(tmp1)

    # ── Test 2: Tampered publicImageHash ─────────────────────────────────────
    print("\n[Test 2] Wrong publicImageHash -> should FAIL verification")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp2 = f.name
    try:
        r2 = _embed_with_proof(dcm_a, tmp2)
        pub_tampered = list(r2["public_inputs"])
        # public_inputs[1] is publicImageHash[0] — flip one digit
        pub_tampered[1] = str(int(pub_tampered[1]) ^ 0xDEAD)
        ok2 = _verify(r2["proof"], pub_tampered)
        status = "PASS" if not ok2 else "FAIL (unexpected)"
        results["test2_wrong_image_hash"] = {
            "expected": "FAIL", "got": "FAIL" if not ok2 else "PASS",
            "status": "OK" if not ok2 else "FAIL",
        }
        print(f"  Result: verification {'rejected' if not ok2 else 'accepted (UNEXPECTED)'}  -> {status}")
    finally:
        if os.path.exists(tmp2): os.unlink(tmp2)

    # ── Test 3: Tampered proof.json ───────────────────────────────────────────
    print("\n[Test 3] Tampered proof (flip coefficient) -> should FAIL verification")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp3 = f.name
    try:
        r3 = _embed_with_proof(dcm_a, tmp3)
        proof_tampered = copy.deepcopy(r3["proof"])
        # Flip last digit of pi_a[0]
        orig = proof_tampered["pi_a"][0]
        proof_tampered["pi_a"][0] = str(int(orig) + 1) if orig.isdigit() else orig[:-1] + str((int(orig[-1]) + 1) % 10)
        ok3 = _verify(proof_tampered, r3["public_inputs"])
        status = "PASS" if not ok3 else "FAIL (unexpected)"
        results["test3_tampered_proof"] = {
            "expected": "FAIL", "got": "FAIL" if not ok3 else "PASS",
            "status": "OK" if not ok3 else "FAIL",
        }
        print(f"  Result: verification {'rejected' if not ok3 else 'accepted (UNEXPECTED)'}  -> {status}")
    finally:
        if os.path.exists(tmp3): os.unlink(tmp3)

    # ── Test 4: Cross-image proof (proof from A, image B) ────────────────────
    print("\n[Test 4] Proof from image A verified with image B public inputs -> should FAIL")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp4a = f.name
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp4b = f.name
    try:
        r4a = _embed_with_proof(dcm_a, tmp4a)
        r4b = _embed_with_proof(dcm_b, tmp4b)
        # Use proof from image A but public inputs from image B
        ok4 = _verify(r4a["proof"], r4b["public_inputs"])
        status = "PASS" if not ok4 else "FAIL (unexpected)"
        results["test4_cross_image"] = {
            "expected": "FAIL", "got": "FAIL" if not ok4 else "PASS",
            "status": "OK" if not ok4 else "FAIL",
        }
        print(f"  Result: verification {'rejected' if not ok4 else 'accepted (UNEXPECTED)'}  -> {status}")
    finally:
        for f in (tmp4a, tmp4b):
            if os.path.exists(f): os.unlink(f)

    # ── Test 5: Wrong chaos_key (extract) ─────────────────────────────────────
    print("\n[Test 5] Wrong chaos_key on extract -> should reject BEFORE reading metadata")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp5 = f.name
    try:
        r5 = _embed_with_proof(dcm_a, tmp5)
        ds = DicomStego()
        t0 = time.perf_counter()
        ext = ds.extract(tmp5, chaos_key="wrong_key_12345", verbose=False)
        reject_time = time.perf_counter() - t0
        rejected_fast = not ext["success"] and "Wrong chaos_key" in ext.get("error", "")
        status = "PASS" if rejected_fast else "FAIL (unexpected)"
        results["test5_wrong_chaos_key"] = {
            "expected": "FAIL before metadata read",
            "got": "FAIL (fast rejection)" if rejected_fast else "PASS (unexpected)",
            "status": "OK" if rejected_fast else "FAIL",
            "rejection_time_ms": round(reject_time * 1000, 2),
            "error_message": ext.get("error", ""),
        }
        print(f"  Result: {'rejected instantly' if rejected_fast else 'NOT rejected (FAIL)'}  "
              f"(t={reject_time*1000:.1f}ms)  -> {status}")
    finally:
        if os.path.exists(tmp5): os.unlink(tmp5)

    # ── Summary ───────────────────────────────────────────────────────────────
    save_json(results, RDIR / "correctness_tests.json")

    total_ok = sum(1 for v in results.values() if v.get("status") == "OK")
    print(f"\n{'='*50}")
    print(f"CORRECTNESS TESTS: {total_ok}/{len(results)} PASSED")
    for name, val in results.items():
        mark = "[OK]" if val["status"] == "OK" else "[FAIL]"
        print(f"  {mark}  {name}: expected={val['expected']}  got={val['got']}")

    return results


if __name__ == "__main__":
    run(verbose=True)
