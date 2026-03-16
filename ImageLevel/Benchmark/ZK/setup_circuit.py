"""
ZK Benchmarks — §4: Circuit Compilation & Trusted Setup
=========================================================
Compiles the Circom circuit and runs the Groth16 trusted setup.
This must be run BEFORE zk_timing.py and correctness_tests.py.

Steps:
  1. Verify Node.js + circom + snarkjs are available
  2. Compile circuits/source/chaos_zk_stego.circom -> .r1cs + .wasm
  3. Run groth16 setup (r1cs + ptau -> .zkey)
  4. Export verification_key.json

Run:
    cd ImageLevel
    python Benchmark/ZK/setup_circuit.py
"""

import sys
import subprocess
import shutil
import time
from pathlib import Path

BENCH_DIR   = Path(__file__).resolve().parent.parent
PROJECT_DIR = BENCH_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(BENCH_DIR))

CIRCUIT_SRC  = PROJECT_DIR / "circuits" / "source" / "chaos_zk_stego.circom"
BUILD_DIR    = PROJECT_DIR / "circuits" / "compiled" / "build"
ARTEFACTS    = PROJECT_DIR / "artifacts" / "keys"
CIRCOM_EXE   = PROJECT_DIR / "bin" / "circom.exe"
CIRCUIT_NAME = "chaos_zk_stego"


def _run(cmd: list, cwd: Path, label: str, timeout: int = 600) -> float:
    """Run a command, print output, return elapsed seconds. Raises on failure."""
    print(f"\n[{label}]")
    print(f"  CMD: {' '.join(str(c) for c in cmd)}")
    t0 = time.perf_counter()
    result = subprocess.run(
        [str(c) for c in cmd], cwd=str(cwd),
        capture_output=True, text=True, timeout=timeout
    )
    elapsed = time.perf_counter() - t0
    if result.stdout.strip():
        print(f"  STDOUT: {result.stdout.strip()[:400]}")
    if result.stderr.strip():
        print(f"  STDERR: {result.stderr.strip()[:400]}")
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed (exit {result.returncode})")
    print(f"  [OK]  Done in {elapsed:.1f}s")
    return elapsed


def run(force: bool = False) -> dict:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    zkey = BUILD_DIR / f"{CIRCUIT_NAME}.zkey"
    vkey = BUILD_DIR / f"{CIRCUIT_NAME}_verification_key.json"
    r1cs = BUILD_DIR / f"{CIRCUIT_NAME}.r1cs"
    wasm = BUILD_DIR / f"{CIRCUIT_NAME}_js" / f"{CIRCUIT_NAME}.wasm"

    timings = {}

    # ── 0. Prerequisites ──────────────────────────────────────────────────────
    print("Checking prerequisites ...")
    for tool in ("node", "npx"):
        path = shutil.which(tool) or shutil.which(f"{tool}.cmd")
        if path:
            print(f"  [OK]  {tool}: {path}")
        else:
            raise EnvironmentError(
                f"{tool} not found. Install Node.js from https://nodejs.org"
            )

    if not CIRCOM_EXE.exists():
        raise FileNotFoundError(
            f"circom.exe not found at {CIRCOM_EXE}\n"
            "Download from https://docs.circom.io/getting-started/installation/"
        )
    print(f"  [OK]  circom: {CIRCOM_EXE}")

    if not CIRCUIT_SRC.exists():
        raise FileNotFoundError(f"Circuit source not found: {CIRCUIT_SRC}")

    # Choose ptau
    ptau = ARTEFACTS / "pot16_final.ptau"
    if not ptau.exists():
        ptau = ARTEFACTS / "pot12_final.ptau"
    if not ptau.exists():
        raise FileNotFoundError(
            f"No .ptau file found in {ARTEFACTS}\n"
            "Download pot16_final.ptau or pot12_final.ptau"
        )
    print(f"  [OK]  ptau: {ptau.name}")

    # ── 1. Compile circuit ────────────────────────────────────────────────────
    if not r1cs.exists() or not wasm.exists() or force:
        print("\nCompiling Circom circuit ...")
        timings["compile"] = _run(
            [CIRCOM_EXE, str(CIRCUIT_SRC),
             "--r1cs", "--wasm", "--sym",
             "--output", str(BUILD_DIR)],
            cwd=BUILD_DIR, label="circom compile",
            timeout=300,
        )
    else:
        print(f"  [OK]  Skipping compile (artifacts exist, use --force to recompile)")
        timings["compile"] = 0.0

    # Count constraints from .r1cs info
    print("\nConstraint count ...")
    try:
        npx = shutil.which("npx.cmd") or shutil.which("npx")
        result = subprocess.run(
            [npx, "snarkjs", "r1cs", "info", str(r1cs)],
            cwd=str(BUILD_DIR), capture_output=True, text=True, timeout=60
        )
        out = result.stdout + result.stderr
        print(f"  {out[:600]}")
    except Exception as e:
        print(f"  (could not run r1cs info: {e})")

    # ── 2. Trusted setup (groth16 setup) ──────────────────────────────────────
    if not zkey.exists() or force:
        print("\nRunning Groth16 trusted setup ...")
        npx = shutil.which("npx.cmd") or shutil.which("npx")
        timings["setup"] = _run(
            [npx, "snarkjs", "groth16", "setup",
             str(r1cs), str(ptau), str(zkey)],
            cwd=BUILD_DIR, label="groth16 setup",
            timeout=600,
        )
    else:
        print(f"  [OK]  Skipping setup (zkey exists, use force=True to redo)")
        timings["setup"] = 0.0

    # ── 3. Export verification key ────────────────────────────────────────────
    if not vkey.exists() or force:
        npx = shutil.which("npx.cmd") or shutil.which("npx")
        timings["export_vk"] = _run(
            [npx, "snarkjs", "zkey", "export", "verificationkey",
             str(zkey), str(vkey)],
            cwd=BUILD_DIR, label="export verificationkey",
            timeout=60,
        )
    else:
        print(f"  [OK]  Skipping vkey export (file exists)")
        timings["export_vk"] = 0.0

    # ── 4. Copy vkey to verifier_package ─────────────────────────────────────
    vp_vkey = PROJECT_DIR / "verifier_package" / "circuits" / "compiled" / "build" / "verification_key.json"
    if vkey.exists():
        vp_vkey.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(vkey, vp_vkey)
        print(f"  [OK]  Copied vkey -> {vp_vkey}")

    print("\n" + "="*50)
    print("Setup complete!")
    for k, v in timings.items():
        print(f"  {k:15s}: {v:.1f}s")

    return timings


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Compile circuit and run trusted setup")
    parser.add_argument("--force", action="store_true", help="Force recompile even if artifacts exist")
    args = parser.parse_args()
    run(force=args.force)
