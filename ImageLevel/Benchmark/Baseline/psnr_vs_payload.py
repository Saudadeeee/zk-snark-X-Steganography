"""
Baseline -- §3: PSNR vs Payload Rate
=======================================
Sweeps embedding rate (BPP) from 0.01 to 2.0, measures PSNR for each method.
Shows PSNR degradation as more bits are hidden.

Line charts:
  results/psnr_vs_payload.png  -- PSNR (dB) vs BPP, one line per method
  results/psnr_vs_payload.json -- raw data per rate

Run:
    cd ImageLevel
    python Benchmark/Baseline/psnr_vs_payload.py
"""

import sys
from pathlib import Path

BENCH_DIR   = Path(__file__).resolve().parent.parent
PROJECT_DIR = BENCH_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(BENCH_DIR))

import numpy as np
import matplotlib.pyplot as plt
from common import (
    list_dicom_files, load_dicom_cover,
    psnr, save_figure, save_json, results_dir,
    METHOD_COLORS, METHOD_ORDER, EMBED_FUNCS,
)

RDIR    = results_dir("Baseline")
METHODS = [m for m in METHOD_ORDER if m != "Cover"]
BPP_RATES = [0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 1.5, 2.0]


def run(verbose: bool = True) -> dict:
    dcm_files = list_dicom_files()
    cover, fname = load_dicom_cover(dcm_files[0])
    h, w = cover.shape
    max_bits = h * w * 2    # 2 bpp max for all methods

    if verbose:
        print(f"PSNR vs Payload on: {fname}  ({h}x{w})\n")
        print(f"{'BPP':>6s}  " + "  ".join(f"{m[:12]:>12s}" for m in METHODS))
        print("-" * (8 + 14 * len(METHODS)))

    from common import make_random_bits
    results_data = {m: [] for m in METHODS}

    for bpp_rate in BPP_RATES:
        n_bits = min(int(h * w * bpp_rate), max_bits)
        bits = make_random_bits(n_bits)
        row_vals = []
        for method in METHODS:
            stego = EMBED_FUNCS[method](cover, bits)
            p = psnr(cover, stego)
            # Cap at 100 dB if embedding is too small to measure
            p = min(p, 100.0)
            results_data[method].append(round(p, 2))
            row_vals.append(p)
        if verbose:
            print(f"  {bpp_rate:4.2f}  " + "  ".join(f"{v:>12.2f}" for v in row_vals))

    # ── Line chart ────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(12, 6))
    for method in METHODS:
        psnr_vals = results_data[method]
        # Clip inf at 100 for display
        display_vals = [min(v, 100.0) for v in psnr_vals]
        ax.plot(BPP_RATES, display_vals, color=METHOD_COLORS[method],
                linewidth=2.5, marker="o", markersize=7, label=method)
        ax.fill_between(BPP_RATES, [v - 0.5 for v in display_vals],
                        [v + 0.5 for v in display_vals],
                        color=METHOD_COLORS[method], alpha=0.08)

    # Reference lines
    ax.axhline(40, color="gray", linestyle="--", linewidth=1,
               alpha=0.6, label="40 dB threshold (good quality)")
    ax.axhline(30, color="orange", linestyle="--", linewidth=1,
               alpha=0.6, label="30 dB threshold (acceptable)")

    ax.set_xlabel("Embedding rate (BPP = bits per pixel)")
    ax.set_ylabel("PSNR (dB)")
    ax.set_title(f"PSNR vs Embedding Rate\n{fname} | higher PSNR = better quality")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(20, 105)
    ax.set_xlim(min(BPP_RATES) - 0.005, max(BPP_RATES) + 0.1)
    plt.tight_layout()
    save_figure(fig, RDIR / "psnr_vs_payload.png")

    output = {
        "file":      fname,
        "bpp_rates": BPP_RATES,
        "methods":   {m: results_data[m] for m in METHODS},
    }
    save_json(output, RDIR / "psnr_vs_payload.json")
    return output


if __name__ == "__main__":
    run(verbose=True)
