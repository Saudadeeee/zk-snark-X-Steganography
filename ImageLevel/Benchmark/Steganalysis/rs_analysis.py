"""
Steganalysis -- §2.1: RS Analysis
====================================
Runs RS Analysis (Fridrich et al. 2001) on cover and each stego method.
Compares Rm-Sm statistic (higher = more detectable).

Line charts:
  results/rs_analysis_line.png  -- Rm-Sm per file, line per method
  results/rs_analysis_bar.png   -- mean Rm-Sm bar chart
  results/rs_analysis.json      -- raw per-file data

Important note: RS p_hat is DEGENERATE for 16-bit DICOM images (symmetric
histogram causes p_hat = 0.5 regardless of embedding). This is a known
limitation of RS analysis applied to 16-bit data. We report Rm-Sm instead.

Run:
    cd ImageLevel
    python Benchmark/Steganalysis/rs_analysis.py
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
    rs_analysis, save_figure, save_json, results_dir,
    METHOD_COLORS, METHOD_ORDER, EMBED_FUNCS,
)

RDIR    = results_dir("Steganalysis")
METHODS = METHOD_ORDER   # include "Cover" as baseline


def run(verbose: bool = True) -> dict:
    dcm_files  = list_dicom_files()
    file_names = [f.stem for f in dcm_files]

    if verbose:
        print(f"RS Analysis on {len(dcm_files)} DICOM files x {len(METHODS)} methods\n")

    from common import make_random_bits
    per_file = {m: [] for m in METHODS}

    for fi, dcm_path in enumerate(dcm_files):
        cover, fname = load_dicom_cover(dcm_path)
        h, w = cover.shape
        n_bits = int(h * w * 1.0)        # 1 bpp
        bits = make_random_bits(n_bits)

        if verbose:
            print(f"  [{fi+1:2d}/{len(dcm_files)}] {fname}")

        for method in METHODS:
            if method == "Cover":
                img = cover
            else:
                img = EMBED_FUNCS[method](cover, bits)
            rs = rs_analysis(img)
            rm_sm = round(float(rs["Rm"] - rs["Sm"]), 6)
            per_file[method].append(rm_sm)
            if verbose:
                print(f"      {method:18s}: Rm-Sm={rm_sm:+.4f}  "
                      f"(Rm={rs['Rm']:.4f}  Sm={rs['Sm']:.4f})")

    means = {m: round(float(np.mean(per_file[m])), 6) for m in METHODS}

    # ── Figure 1: Line chart -- Rm-Sm per file ────────────────────────────────
    fig1, ax1 = plt.subplots(figsize=(12, 5))
    x = range(1, len(dcm_files) + 1)
    for method in METHODS:
        ls = "solid" if method in ("Cover", "This Work") else "dashed"
        ax1.plot(x, per_file[method], color=METHOD_COLORS[method],
                 linewidth=2, marker="o", markersize=6,
                 linestyle=ls, label=method)
    ax1.axhline(0, color="black", linewidth=0.8, linestyle=":", alpha=0.5)
    ax1.set_xlabel("DICOM file index")
    ax1.set_ylabel("RS statistic: Rm - Sm")
    ax1.set_title("RS Analysis: Rm-Sm per DICOM File\n"
                  "(positive = detectable; lower = more resistant to RS attack | 1 bpp fill)")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels([f.stem[:8] for f in dcm_files], rotation=30, ha="right", fontsize=8)
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)
    plt.tight_layout()
    save_figure(fig1, RDIR / "rs_analysis_line.png")

    # ── Figure 2: Mean bar chart ──────────────────────────────────────────────
    fig2, ax2 = plt.subplots(figsize=(9, 5))
    colors = [METHOD_COLORS[m] for m in METHODS]
    bars = ax2.bar(METHODS, [means[m] for m in METHODS],
                   color=colors, edgecolor="white", alpha=0.87)
    for bar, m in zip(bars, METHODS):
        v = means[m]
        ax2.text(bar.get_x() + bar.get_width()/2,
                 v + 0.0005 * np.sign(v) if v >= 0 else v - 0.001,
                 f"{v:+.4f}", ha="center", va="bottom" if v >= 0 else "top", fontsize=8.5)
    ax2.axhline(0, color="black", linewidth=0.8)
    ax2.set_ylabel("Mean Rm - Sm (across all files)")
    ax2.set_title("RS Analysis: Mean Rm-Sm\n(closer to 0 = less detectable by RS attack)")
    ax2.set_xticks(range(len(METHODS)))
    ax2.set_xticklabels(METHODS, rotation=20, ha="right", fontsize=9)
    ax2.grid(True, alpha=0.3, axis="y")
    plt.tight_layout()
    save_figure(fig2, RDIR / "rs_analysis_bar.png")

    output = {
        "n_files":   len(dcm_files),
        "fill_bpp":  1.0,
        "per_file":  per_file,
        "means":     means,
        "file_names": file_names,
        "note": "RS p_hat is degenerate for 16-bit images (symmetric histogram). "
                "Rm-Sm reported instead.",
    }
    save_json(output, RDIR / "rs_analysis.json")

    if verbose:
        print(f"\n{'Method':20s}  {'Mean Rm-Sm':>12s}")
        print("-" * 36)
        for m in METHODS:
            print(f"  {m:18s}  {means[m]:>+12.6f}")

    return output


if __name__ == "__main__":
    run(verbose=True)
