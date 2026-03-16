"""
Performance — §5.1: Timing Breakdown per Phase
================================================
Measures each embed/extract phase independently using perf_counter.
Produces stacked bar chart (Figure F5).

Charts:
  results/timing_breakdown_bar.png   — F5: stacked bar (embed phases)
  results/timing_comparison_line.png — line: with-proof vs no-proof
  results/timing_breakdown.json      — raw data

Run:
    cd ImageLevel
    python Benchmark/Performance/timing_breakdown.py
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
import platform
from common import (
    list_dicom_files, save_json, results_dir, CHAOS_KEY,
    METHOD_COLORS,
)

RDIR   = results_dir("Performance")
N_RUNS = 5


def _profile_embed_phases(dcm_path: str, with_proof: bool = False) -> dict:
    """Run embed with internal timing instrumentation."""
    import gzip, hashlib
    from src.zk_stego.dicom_handler import DicomHandler, DicomStego, _build_proof_block, _bytes_to_bits
    from src.zk_stego.utils import generate_chaos_key_from_secret

    timings = {}

    # Phase 1: Load DICOM
    t0 = time.perf_counter()
    pixel_array, metadata_json, info = DicomHandler.load(dcm_path)
    timings["load_dicom"] = time.perf_counter() - t0

    # Phase 2: ROI detection
    t0 = time.perf_counter()
    roi_mask = DicomHandler.detect_roi(pixel_array)
    timings["roi_detect"] = time.perf_counter() - t0

    # Phase 3: gzip compress metadata
    t0 = time.perf_counter()
    meta_bytes = gzip.compress(metadata_json.encode("utf-8"), compresslevel=9)
    timings["gzip_compress"] = time.perf_counter() - t0

    # Phase 4: Chaos position generation (proof_key)
    t0 = time.perf_counter()
    proof_key_int = generate_chaos_key_from_secret("zkdicom_proof_key_v1")
    h, w = pixel_array.shape
    pk_x0, pk_y0 = DicomStego._key_start(proof_key_int, w, h, roi_mask)
    timings["chaos_proof_positions"] = time.perf_counter() - t0

    # Phase 5: Chaos position generation (chaos_key, entropy sorted)
    t0 = time.perf_counter()
    chaos_key_int = generate_chaos_key_from_secret(CHAOS_KEY)
    meta_x0, meta_y0 = DicomStego._key_start(chaos_key_int, w, h, roi_mask)
    meta_bits = _bytes_to_bits(meta_bytes)
    from src.zk_stego.dicom_handler import _positions_needed
    n = _positions_needed(len(meta_bits))
    _ = DicomStego._roi_positions(
        pixel_array, roi_mask, meta_x0, meta_y0, chaos_key_int, n,
        sort_by_entropy=True, exclude=None,
    )
    timings["chaos_meta_positions"] = time.perf_counter() - t0

    # Phase 6: ZK witness + proving (optional)
    if with_proof:
        from src.zk_stego.prover import Prover
        from src.zk_stego.utils import SnarkJSRunner
        prover = Prover()
        runner = SnarkJSRunner()
        meta_sha256 = hashlib.sha256(meta_bytes).digest()
        fingerprint_msg = meta_sha256[:4].decode("latin-1")

        chaos_params = prover._extract_chaos_parameters(
            pixel_array, fingerprint_msg, CHAOS_KEY, meta_x0, meta_y0
        )
        witness_input = prover._create_witness_input(chaos_params)

        t0 = time.perf_counter()
        wtns = runner.generate_witness(witness_input)
        timings["zk_witness"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        if wtns:
            runner.generate_groth16_proof(wtns)
        timings["zk_prove"] = time.perf_counter() - t0
    else:
        timings["zk_witness"] = 0.0
        timings["zk_prove"]   = 0.0

    # Phase 7: LSB embedding
    from src.zk_stego.dicom_handler import _embed_at
    t0 = time.perf_counter()
    proof_key_int2 = generate_chaos_key_from_secret("zkdicom_proof_key_v1")
    pk_x0b, pk_y0b = DicomStego._key_start(proof_key_int2, w, h, roi_mask)
    proof_block = _build_proof_block(CHAOS_KEY, hashlib.sha256(meta_bytes).digest(),
                                     len(meta_bits), None, None)
    proof_bits = _bytes_to_bits(proof_block)
    from src.zk_stego.dicom_handler import _positions_needed as _pn
    pp = DicomStego._roi_positions(
        pixel_array, roi_mask, pk_x0b, pk_y0b, proof_key_int2,
        _pn(len(proof_bits)), sort_by_entropy=False, exclude=None
    )
    stego = _embed_at(pixel_array.copy(), pp, proof_bits)
    from src.zk_stego.dicom_handler import _positions_needed as _pnm
    mp = DicomStego._roi_positions(
        stego, roi_mask, meta_x0, meta_y0, chaos_key_int,
        _pnm(len(meta_bits)), sort_by_entropy=True, exclude=set(map(tuple, pp))
    )
    stego = _embed_at(stego, mp, meta_bits)
    timings["lsb_embed"] = time.perf_counter() - t0

    # Phase 8: PNG save
    from PIL import Image
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name
    try:
        t0 = time.perf_counter()
        Image.fromarray(stego.astype(np.uint16)).save(tmp)
        timings["png_save"] = time.perf_counter() - t0
    finally:
        os.unlink(tmp)

    timings["total_no_zk"]   = sum(v for k, v in timings.items() if "zk_" not in k)
    timings["total_with_zk"] = sum(timings.values())
    return timings


def run(n_runs: int = N_RUNS, with_proof: bool = False, verbose: bool = True) -> dict:
    dcm_files = list_dicom_files()
    dcm = str(dcm_files[0])

    if verbose:
        cpu  = platform.processor() or "unknown"
        ram  = "unknown"
        try:
            import psutil
            ram = f"{psutil.virtual_memory().total / 1e9:.1f} GB"
        except ImportError:
            pass
        print(f"Platform: {platform.system()} {platform.machine()}")
        print(f"CPU     : {cpu[:60]}")
        print(f"RAM     : {ram}")
        print(f"Runs    : {n_runs}\n")

    all_runs = []
    for i in range(n_runs):
        if verbose:
            print(f"  Run {i+1}/{n_runs} ...", end=" ", flush=True)
        t = _profile_embed_phases(dcm, with_proof=with_proof)
        all_runs.append(t)
        if verbose:
            print(f"total={t['total_no_zk']:.3f}s (no ZK)")

    phases = ["load_dicom", "roi_detect", "gzip_compress",
              "chaos_proof_positions", "chaos_meta_positions",
              "lsb_embed", "png_save"]
    if with_proof:
        phases = ["load_dicom", "roi_detect", "gzip_compress",
                  "chaos_proof_positions", "chaos_meta_positions",
                  "zk_witness", "zk_prove", "lsb_embed", "png_save"]

    means = {p: float(np.mean([r[p] for r in all_runs])) for p in phases}
    stds  = {p: float(np.std( [r[p] for r in all_runs])) for p in phases}

    summary = {
        "n_runs":   n_runs,
        "with_proof": with_proof,
        "phases":   {p: {"mean_s": round(means[p], 4), "std_s": round(stds[p], 5)}
                     for p in phases},
        "total_no_zk_mean_s":   round(float(np.mean([r["total_no_zk"]   for r in all_runs])), 4),
        "total_with_zk_mean_s": round(float(np.mean([r["total_with_zk"] for r in all_runs])), 4),
        "platform": {"os": platform.system(), "cpu": platform.processor()[:80]},
    }
    save_json(summary, RDIR / "timing_breakdown.json")

    # ── F5: Stacked bar chart ─────────────────────────────────────────────────
    phase_labels = {
        "load_dicom":             "DICOM Load",
        "roi_detect":             "ROI Detection",
        "gzip_compress":          "gzip Compress",
        "chaos_proof_positions":  "Chaos Pos (proof)",
        "chaos_meta_positions":   "Chaos Pos (meta)",
        "zk_witness":             "ZK Witness Gen",
        "zk_prove":               "ZK Groth16 Prove",
        "lsb_embed":              "LSB Embed",
        "png_save":               "PNG Save",
    }
    pal = [
        "#2196F3", "#4CAF50", "#FF9800", "#9C27B0",
        "#673AB7", "#F44336", "#E91E63", "#795548", "#009688",
    ]

    fig, ax = plt.subplots(figsize=(10, 6))
    cumulative = 0.0
    bar_x = 0
    for j, phase in enumerate(phases):
        color  = pal[j % len(pal)]
        height = means[phase]
        err    = stds[phase]
        ax.barh(bar_x, height, left=cumulative, color=color,
                edgecolor="white", label=phase_labels.get(phase, phase))
        if height > 0.005:
            ax.text(cumulative + height/2, bar_x, f"{height:.3f}s",
                    ha="center", va="center", fontsize=7.5, color="white", fontweight="bold")
        cumulative += height

    ax.set_yticks([0])
    ax.set_yticklabels(["Embed pipeline"])
    ax.set_xlabel("Time (seconds)")
    ax.set_title(
        f"Embed Phase Timing Breakdown {'(with ZK proof)' if with_proof else '(no ZK proof)'}\n"
        f"(mean of {n_runs} runs on {Path(dcm).name})"
    )
    ax.legend(loc="lower right", fontsize=8.5)
    total_mean = sum(means.values())
    ax.set_xlim(0, total_mean * 1.15)
    ax.text(total_mean * 1.02, bar_x, f"Total: {total_mean:.3f}s", va="center", fontsize=9)
    plt.tight_layout()
    save_figure(fig, RDIR / "timing_breakdown_bar.png")

    if verbose:
        print(f"\n{'='*50}")
        for p in phases:
            print(f"  {phase_labels.get(p,p):28s}: {means[p]:.4f} +/- {stds[p]:.5f} s")
        print(f"  {'TOTAL':28s}: {total_mean:.4f} s")

    return summary


def save_figure(fig, path, also_pdf=False):
    from common import save_figure as _sf
    _sf(fig, path, also_pdf)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-proof", action="store_true",
                        help="Include ZK witness+prove phases (requires compiled circuit)")
    parser.add_argument("--runs", type=int, default=N_RUNS)
    args = parser.parse_args()
    run(n_runs=args.runs, with_proof=args.with_proof, verbose=True)
