"""
Steganalysis -- §2.2: Chi-Square Attack
==========================================
Westfeld & Pfitzmann 1999. Tests even/odd pixel value symmetry.
Small p-value → image is detected as containing hidden data.

NOTE: Chi-square is inapplicable to 16-bit DICOM images (histogram is
too sparse; p=0 for all methods including cover). This is a confirmed
known limitation reported in the benchmark results.

Line charts:
  results/chi_square_line.png  -- p-value per file, line per method
  results/chi_square_bar.png   -- mean p-value bar chart
  results/chi_square.json      -- raw data + limitation note

Run:
    cd ImageLevel
    python Benchmark/Steganalysis/chi_square.py
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
    chi_square_attack, save_figure, save_json, results_dir,
    METHOD_COLORS, METHOD_ORDER, EMBED_FUNCS,
)

RDIR    = results_dir("Steganalysis")
METHODS = METHOD_ORDER


def run(verbose: bool = True) -> dict:
    dcm_files  = list_dicom_files()
    file_names = [f.stem for f in dcm_files]

    if verbose:
        print(f"Chi-Square Attack on {len(dcm_files)} DICOM files x {len(METHODS)} methods")
        print("NOTE: Chi-square is inapplicable to 16-bit DICOM (p=0 for all including cover)\n")

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
            p = chi_square_attack(img)
            per_file[method].append(round(float(p), 6))
            if verbose:
                print(f"      {method:18s}: p-value={p:.4f}")

    means = {m: round(float(np.mean(per_file[m])), 6) for m in METHODS}

    # ── Figure 1: Line chart ──────────────────────────────────────────────────
    fig1, ax1 = plt.subplots(figsize=(12, 5))
    x = range(1, len(dcm_files) + 1)
    for method in METHODS:
        ls = "solid" if method in ("Cover", "This Work") else "dashed"
        ax1.plot(x, per_file[method], color=METHOD_COLORS[method],
                 linewidth=2, marker="o", markersize=6, linestyle=ls, label=method)
    ax1.axhline(0.05, color="crimson", linestyle="--", linewidth=1.2,
                alpha=0.7, label="p=0.05 detection threshold")
    ax1.set_xlabel("DICOM file index")
    ax1.set_ylabel("Chi-square p-value")
    ax1.set_title("Chi-Square Attack: p-value per DICOM File\n"
                  "(p<0.05 = detected; NOTE: p=0 for all 16-bit DICOM -- inapplicable)")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels([f.stem[:8] for f in dcm_files], rotation=30, ha="right", fontsize=8)
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)
    ax1.set_ylim(-0.05, 1.05)
    # Annotation about 16-bit limitation
    ax1.annotate(
        "16-bit DICOM: sparse histogram\n-> chi-square inapplicable (p=0 always)",
        xy=(0.5, 0.5), xycoords="axes fraction",
        ha="center", fontsize=10, color="crimson", style="italic",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="lightyellow", alpha=0.85),
    )
    plt.tight_layout()
    save_figure(fig1, RDIR / "chi_square_line.png")

    # ── Figure 2: Mean bar chart ──────────────────────────────────────────────
    fig2, ax2 = plt.subplots(figsize=(9, 5))
    colors = [METHOD_COLORS[m] for m in METHODS]
    bars = ax2.bar(METHODS, [means[m] for m in METHODS],
                   color=colors, edgecolor="white", alpha=0.87)
    for bar, m in zip(bars, METHODS):
        ax2.text(bar.get_x() + bar.get_width()/2, means[m] + 0.005,
                 f"{means[m]:.4f}", ha="center", va="bottom", fontsize=8.5)
    ax2.axhline(0.05, color="crimson", linestyle="--", linewidth=1.2,
                label="p=0.05 threshold")
    ax2.set_ylabel("Mean chi-square p-value")
    ax2.set_title("Chi-Square Attack: Mean p-value\n"
                  "(higher = harder to detect; 16-bit DICOM: p=0 always -- inapplicable)")
    ax2.set_xticks(range(len(METHODS)))
    ax2.set_xticklabels(METHODS, rotation=20, ha="right", fontsize=9)
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3, axis="y")
    ax2.set_ylim(0, 1.1)
    plt.tight_layout()
    save_figure(fig2, RDIR / "chi_square_bar.png")

    output = {
        "n_files":    len(dcm_files),
        "fill_bpp":   1.0,
        "per_file":   per_file,
        "means":      means,
        "file_names": file_names,
        "limitation": (
            "Chi-square attack requires dense even/odd histogram pairs. "
            "16-bit DICOM pixel histograms are too sparse: p-value=0 for ALL methods "
            "including unmodified cover. This confirms chi-square is inapplicable "
            "to 16-bit medical images -- a reportable finding."
        ),
    }
    save_json(output, RDIR / "chi_square.json")
    return output


if __name__ == "__main__":
    run(verbose=True)
