"""
Steganalysis -- §2.3: SPA Analysis
=====================================
Sample Pairs Analysis (Dumitrescu et al. 2003).
Estimates embedding rate from horizontal adjacent pairs.

p_hat is normalized by total pixel pairs. Lower p_hat = less detectable.

Line charts:
  results/spa_analysis_line.png -- p_hat per file, line per method
  results/spa_analysis_bar.png  -- mean p_hat bar chart
  results/spa_analysis.json     -- raw data

Run:
    cd ImageLevel
    python Benchmark/Steganalysis/spa_analysis.py
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
    spa_analysis, save_figure, save_json, results_dir,
    METHOD_COLORS, METHOD_ORDER, EMBED_FUNCS,
)

RDIR    = results_dir("Steganalysis")
METHODS = METHOD_ORDER


def run(verbose: bool = True) -> dict:
    dcm_files  = list_dicom_files()
    file_names = [f.stem for f in dcm_files]

    if verbose:
        print(f"SPA Analysis on {len(dcm_files)} DICOM files x {len(METHODS)} methods\n")

    from common import make_random_bits
    per_file = {m: [] for m in METHODS}

    for fi, dcm_path in enumerate(dcm_files):
        cover, fname = load_dicom_cover(dcm_path)
        h, w = cover.shape
        n_bits = int(h * w * 1.0)
        bits = make_random_bits(n_bits)

        if verbose:
            print(f"  [{fi+1:2d}/{len(dcm_files)}] {fname}")

        for method in METHODS:
            img = cover if method == "Cover" else EMBED_FUNCS[method](cover, bits)
            spa = spa_analysis(img)
            p_hat = round(float(spa["p_hat"]), 6)
            per_file[method].append(p_hat)
            if verbose:
                print(f"      {method:18s}: p_hat={p_hat:.6f}  "
                      f"(C0={spa['C0']:.0f}  Cp1={spa['Cp1']:.0f}  Cm1={spa['Cm1']:.0f})")

    means = {m: round(float(np.mean(per_file[m])), 6) for m in METHODS}

    # ── Figure 1: Line chart ──────────────────────────────────────────────────
    fig1, ax1 = plt.subplots(figsize=(12, 5))
    x = range(1, len(dcm_files) + 1)
    for method in METHODS:
        ls = "solid" if method in ("Cover", "This Work") else "dashed"
        ax1.plot(x, per_file[method], color=METHOD_COLORS[method],
                 linewidth=2, marker="o", markersize=6, linestyle=ls, label=method)
    ax1.set_xlabel("DICOM file index")
    ax1.set_ylabel("SPA p_hat (normalised by total pairs)")
    ax1.set_title("SPA Analysis: Estimated Embedding Rate per DICOM File\n"
                  "(lower p_hat = harder to detect | 1 bpp fill)")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels([f.stem[:8] for f in dcm_files], rotation=30, ha="right", fontsize=8)
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)
    plt.tight_layout()
    save_figure(fig1, RDIR / "spa_analysis_line.png")

    # ── Figure 2: Mean bar chart ──────────────────────────────────────────────
    fig2, ax2 = plt.subplots(figsize=(9, 5))
    colors = [METHOD_COLORS[m] for m in METHODS]
    bars = ax2.bar(METHODS, [means[m] for m in METHODS],
                   color=colors, edgecolor="white", alpha=0.87)
    for bar, m in zip(bars, METHODS):
        ax2.text(bar.get_x() + bar.get_width()/2, means[m] + max(means.values()) * 0.01,
                 f"{means[m]:.4f}", ha="center", va="bottom", fontsize=8.5)
    ax2.set_ylabel("Mean SPA p_hat")
    ax2.set_title("SPA Analysis: Mean Estimated Embedding Rate\n(lower = less detectable by SPA)")
    ax2.set_xticks(range(len(METHODS)))
    ax2.set_xticklabels(METHODS, rotation=20, ha="right", fontsize=9)
    ax2.grid(True, alpha=0.3, axis="y")
    plt.tight_layout()
    save_figure(fig2, RDIR / "spa_analysis_bar.png")

    output = {
        "n_files":    len(dcm_files),
        "fill_bpp":   1.0,
        "per_file":   per_file,
        "means":      means,
        "file_names": file_names,
    }
    save_json(output, RDIR / "spa_analysis.json")

    if verbose:
        print(f"\n{'Method':20s}  {'Mean p_hat':>12s}")
        print("-" * 36)
        for m in METHODS:
            print(f"  {m:18s}  {means[m]:>12.6f}")

    return output


if __name__ == "__main__":
    run(verbose=True)
