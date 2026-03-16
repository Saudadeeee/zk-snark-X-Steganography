"""
ZK Benchmarks — §4: ZK Timing
================================
Measures each ZK phase independently (10 runs mean +/- std):
  - Witness generation time
  - Groth16 proving time
  - Groth16 verification time
  - Total embed time (with proof)
  - Total embed time (without proof)

Charts:
  results/zk_timing_bar.png     — horizontal bar chart of phase timings
  results/zk_timing_line.png    — line chart: 10 individual runs (prove + verify)
  results/zk_timing.json        — raw data

Prerequisites:
  Run Benchmark/ZK/setup_circuit.py first.

Run:
    cd ImageLevel
    python Benchmark/ZK/zk_timing.py
"""

import sys
import time
import tempfile
import os
from pathlib import Path

BENCH_DIR   = Path(__file__).resolve().parent.parent
PROJECT_DIR = BENCH_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(BENCH_DIR))

import numpy as np
import matplotlib.pyplot as plt
from common import (
    list_dicom_files, save_json, results_dir, CHAOS_KEY,
    METHOD_COLORS,
)

RDIR  = results_dir("ZK")
BUILD = PROJECT_DIR / "circuits" / "compiled" / "build"
N_RUNS = 10


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


def _time_embed(dcm_path: str, with_proof: bool) -> float:
    from src.zk_stego.dicom_handler import DicomStego
    ds = DicomStego()
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name
    try:
        t0 = time.perf_counter()
        ds.embed(str(dcm_path), tmp, chaos_key=CHAOS_KEY,
                 generate_zk_proof=with_proof, verbose=False)
        return time.perf_counter() - t0
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def run(n_runs: int = N_RUNS, verbose: bool = True) -> dict:
    if not _check_artifacts():
        return {"error": "artifacts_missing"}

    dcm_files = list_dicom_files()
    dcm = str(dcm_files[0])  # Use first file for timing

    if verbose:
        print(f"ZK Timing: {n_runs} runs on {Path(dcm).name}\n")

    # ── Witness + Proof separately (via raw SnarkJSRunner) ───────────────────
    from src.zk_stego.prover import Prover
    from src.zk_stego.utils import SnarkJSRunner
    from src.zk_stego.dicom_handler import DicomHandler
    from src.zk_stego.utils import generate_chaos_key_from_secret
    import numpy as _np

    cover, meta_json, info = DicomHandler.load(dcm)
    prover = Prover()
    runner = SnarkJSRunner()

    # Build one proof for repeated verify timing
    sample_proof = None
    sample_public = None

    witness_times = []
    prove_times   = []
    verify_times  = []

    for i in range(n_runs):
        if verbose:
            print(f"  Run {i+1}/{n_runs} ...", end=" ", flush=True)

        # Extract chaos params (fast — just hashing)
        chaos_params = prover._extract_chaos_parameters(
            cover, meta_json[:4], CHAOS_KEY,
            info["cols"] // 2, info["rows"] // 2,
        )
        witness_input = prover._create_witness_input(chaos_params)

        # Time: witness generation
        t0 = time.perf_counter()
        wtns = runner.generate_witness(witness_input)
        tw = time.perf_counter() - t0
        witness_times.append(tw)

        if wtns is None:
            print("  ERROR: witness generation failed!")
            continue

        # Time: proof generation
        t0 = time.perf_counter()
        proof_result = runner.generate_groth16_proof(wtns)
        tp = time.perf_counter() - t0
        prove_times.append(tp)

        if proof_result:
            sample_proof, sample_public = proof_result

        if verbose:
            print(f"witness={tw:.2f}s  prove={tp:.2f}s")

    # Time: verification (many runs — it's fast)
    if sample_proof and sample_public:
        for i in range(n_runs):
            t0 = time.perf_counter()
            runner.verify_groth16_proof(sample_proof, sample_public)
            verify_times.append(time.perf_counter() - t0)
        if verbose:
            print(f"  Verify: mean={_np.mean(verify_times):.3f}s +/- {_np.std(verify_times):.3f}s")

    # Full pipeline timings
    embed_with_proof_times    = []
    embed_without_proof_times = []

    print("\nFull pipeline timing ...")
    for i in range(min(3, n_runs)):  # 3 runs for full pipeline (slower)
        if verbose:
            print(f"  Full-proof run {i+1}/3 ...", end=" ", flush=True)
        t = _time_embed(dcm, with_proof=True)
        embed_with_proof_times.append(t)
        if verbose:
            print(f"{t:.1f}s")

    print("No-proof pipeline timing ...")
    for i in range(n_runs):
        t = _time_embed(dcm, with_proof=False)
        embed_without_proof_times.append(t)

    def _stats(vals):
        if not vals:
            return {"mean": None, "std": None, "min": None, "max": None, "all": []}
        return {
            "mean": round(float(_np.mean(vals)), 4),
            "std":  round(float(_np.std(vals)),  4),
            "min":  round(float(_np.min(vals)),  4),
            "max":  round(float(_np.max(vals)),  4),
            "all":  [round(v, 4) for v in vals],
        }

    summary = {
        "n_runs": n_runs,
        "witness_gen_s":        _stats(witness_times),
        "prove_s":              _stats(prove_times),
        "verify_s":             _stats(verify_times),
        "embed_with_proof_s":   _stats(embed_with_proof_times),
        "embed_no_proof_s":     _stats(embed_without_proof_times),
    }
    save_json(summary, RDIR / "zk_timing.json")

    # ── Bar chart: average phase timings ─────────────────────────────────────
    phases = ["Witness Gen", "Prove (Groth16)", "Verify", "Embed+Proof (total)", "Embed only (no ZK)"]
    means  = [
        summary["witness_gen_s"]["mean"]   or 0,
        summary["prove_s"]["mean"]         or 0,
        summary["verify_s"]["mean"]        or 0,
        summary["embed_with_proof_s"]["mean"] or 0,
        summary["embed_no_proof_s"]["mean"]   or 0,
    ]
    stds = [
        summary["witness_gen_s"]["std"]   or 0,
        summary["prove_s"]["std"]         or 0,
        summary["verify_s"]["std"]        or 0,
        summary["embed_with_proof_s"]["std"] or 0,
        summary["embed_no_proof_s"]["std"]   or 0,
    ]

    colors = [METHOD_COLORS["This Work"]] * 3 + [
        METHOD_COLORS["ACM-only"], METHOD_COLORS["Cover"]
    ]

    fig, ax = plt.subplots(figsize=(10, 5))
    y_pos = range(len(phases))
    bars = ax.barh(y_pos, means, xerr=stds, capsize=5,
                   color=colors, edgecolor="white", alpha=0.85, align="center")
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(phases)
    ax.set_xlabel("Time (seconds)")
    ax.set_title(f"ZK Phase Timing (mean +/- std, {n_runs} runs)\nDicom+Stego pipeline")
    for bar, mean, std in zip(bars, means, stds):
        ax.text(mean + std + 0.05, bar.get_y() + bar.get_height()/2,
                f"{mean:.2f}s", va="center", fontsize=9)
    plt.tight_layout()
    save_figure(fig, RDIR / "zk_timing_bar.png")

    # ── Line chart: individual run times (prove + verify) ─────────────────────
    fig2, ax2 = plt.subplots(figsize=(10, 5))
    if prove_times:
        ax2.plot(range(1, len(prove_times)+1), prove_times,
                 color=METHOD_COLORS["This Work"], marker="o",
                 linewidth=2, markersize=6, label="Groth16 Prove time")
    if verify_times:
        ax2.plot(range(1, len(verify_times)+1), verify_times,
                 color=METHOD_COLORS["Sequential LSB"], marker="s",
                 linewidth=2, markersize=6, label="Groth16 Verify time")
    ax2.set_xlabel("Run #")
    ax2.set_ylabel("Time (seconds)")
    ax2.set_title(f"ZK Timing — Individual Runs ({n_runs} runs)\nProve vs Verify per run")
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    plt.tight_layout()
    save_figure(fig2, RDIR / "zk_timing_line.png")

    if verbose:
        print(f"\n{'='*50}")
        for k, v in summary.items():
            if isinstance(v, dict) and "mean" in v:
                print(f"  {k:30s}: {v['mean']:.3f} +/- {v['std']:.3f} s")

    return summary


def save_figure(fig, path, also_pdf=False):
    from common import save_figure as _sf
    _sf(fig, path, also_pdf)


if __name__ == "__main__":
    run(verbose=True)
