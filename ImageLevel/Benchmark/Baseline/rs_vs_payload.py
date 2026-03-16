"""
Baseline -- §3: RS Statistic vs Payload Rate
===============================================
Sweeps BPP from 0.01 to 2.0, measures RS statistic (Rm-Sm) for each method.
Shows detectability increase as more bits are hidden.

Line charts:
  results/rs_vs_payload.png  -- Rm-Sm vs BPP, one line per method
  results/rs_vs_payload.json -- raw data

Run:
    cd ImageLevel
    python Benchmark/Baseline/rs_vs_payload.py
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
    rs_analysis, spa_analysis,
    save_figure, save_json, results_dir,
    METHOD_COLORS, METHOD_ORDER, EMBED_FUNCS,
)

RDIR      = results_dir("Baseline")
METHODS   = [m for m in METHOD_ORDER if m != "Cover"]
BPP_RATES = [0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 1.5, 2.0]


def run(verbose: bool = True) -> dict:
    dcm_files = list_dicom_files()
    cover, fname = load_dicom_cover(dcm_files[0])
    h, w = cover.shape
    max_bits = h * w * 2

    if verbose:
        print(f"RS & SPA vs Payload on: {fname}  ({h}x{w})\n")

    from common import make_random_bits
    rs_data  = {m: [] for m in METHODS}
    spa_data = {m: [] for m in METHODS}

    for bpp_rate in BPP_RATES:
        n_bits = min(int(h * w * bpp_rate), max_bits)
        bits = make_random_bits(n_bits)
        for method in METHODS:
            stego = EMBED_FUNCS[method](cover, bits)
            rs  = rs_analysis(stego)
            spa = spa_analysis(stego)
            rs_data[method].append(round(float(rs["Rm"] - rs["Sm"]), 6))
            spa_data[method].append(round(float(spa["p_hat"]), 6))

        if verbose:
            print(f"  BPP={bpp_rate:.2f}: " +
                  "  ".join(f"{method[:8]}={rs_data[method][-1]:+.4f}"
                             for method in METHODS))

    # ── Figure: RS Rm-Sm vs BPP + SPA p_hat vs BPP (2 subplots) ──────────────
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    ax = axes[0]
    for method in METHODS:
        ax.plot(BPP_RATES, rs_data[method], color=METHOD_COLORS[method],
                linewidth=2.5, marker="o", markersize=7, label=method)
    ax.axhline(0, color="black", linewidth=0.8, linestyle=":", alpha=0.5)
    ax.set_xlabel("Embedding rate (BPP)")
    ax.set_ylabel("RS statistic: Rm - Sm")
    ax.set_title(f"RS Detectability vs Embedding Rate\n{fname}")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.annotate("lower = less detectable", xy=(0.02, 0.04),
                xycoords="axes fraction", fontsize=8.5, color="gray", style="italic")

    ax = axes[1]
    for method in METHODS:
        ax.plot(BPP_RATES, spa_data[method], color=METHOD_COLORS[method],
                linewidth=2.5, marker="s", markersize=7, label=method)
    ax.set_xlabel("Embedding rate (BPP)")
    ax.set_ylabel("SPA p_hat")
    ax.set_title(f"SPA Detectability vs Embedding Rate\n{fname}")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.annotate("lower = less detectable", xy=(0.02, 0.96),
                xycoords="axes fraction", fontsize=8.5, color="gray", style="italic",
                va="top")

    plt.suptitle("Steganalysis Detectability vs Payload Size", fontsize=12)
    plt.tight_layout()
    save_figure(fig, RDIR / "rs_vs_payload.png")

    output = {
        "file":      fname,
        "bpp_rates": BPP_RATES,
        "rs_rm_sm":  {m: rs_data[m]  for m in METHODS},
        "spa_p_hat": {m: spa_data[m] for m in METHODS},
    }
    save_json(output, RDIR / "rs_vs_payload.json")
    return output


if __name__ == "__main__":
    run(verbose=True)
