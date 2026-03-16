"""
Quality -- §1.3: LSB Bit Planes
==================================
Visualizes spatial distribution of LSB changes introduced by each method.

Line charts:
  results/lsb_row_density.png   -- changed-pixels-per-row (line per method)
  results/lsb_cumulative.png    -- cumulative change fraction vs row
  results/lsb_planes.json       -- row-wise change counts

The row-density chart shows embedding uniformity:
  - Sequential LSB concentrates changes in first rows (non-uniform)
  - PRNG/ACM/This Work should be more spatially uniform

Run:
    cd ImageLevel
    python Benchmark/Quality/lsb_planes.py
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
    save_figure, save_json, results_dir,
    METHOD_COLORS, METHOD_ORDER, EMBED_FUNCS,
)

RDIR    = results_dir("Quality")
METHODS = [m for m in METHOD_ORDER if m != "Cover"]


def run(verbose: bool = True) -> dict:
    dcm_files = list_dicom_files()
    cover, fname = load_dicom_cover(dcm_files[0])
    h, w = cover.shape

    # Use 50% fill so that non-uniform methods show clear spatial pattern
    n_bits = int(h * w * 1.0)    # 1 bpp = 50% of 2bpp capacity
    from common import make_random_bits
    bits = make_random_bits(n_bits)

    if verbose:
        print(f"LSB plane analysis on: {fname}  ({h}x{w})")

    row_counts = {}  # method -> array of changed pixels per row
    for method in METHODS:
        stego = EMBED_FUNCS[method](cover, bits)
        # Changed pixels: any bit differs
        diff = (cover != stego).astype(np.int32)
        row_change = diff.sum(axis=1)    # sum over columns for each row
        row_counts[method] = row_change
        if verbose:
            total = int(row_change.sum())
            uniformity = 1.0 - float(np.std(row_change)) / (float(np.mean(row_change)) + 1e-9)
            print(f"  {method:20s}: total_changed={total:6d}  uniformity={uniformity:.3f}")

    rows = np.arange(h)

    # ── Figure 1: Row change density (line per method) ────────────────────────
    fig1, ax1 = plt.subplots(figsize=(13, 5))
    for method in METHODS:
        # Smooth with a 5-row rolling average for readability
        rc = row_counts[method].astype(float)
        smoothed = np.convolve(rc, np.ones(5)/5, mode="same")
        ax1.plot(rows, smoothed, color=METHOD_COLORS[method], linewidth=1.8,
                 alpha=0.85, label=method)
    ax1.set_xlabel("Row index")
    ax1.set_ylabel("Changed pixels in row (5-row smoothed)")
    ax1.set_title(f"LSB Change Density per Row\n{fname} | 1 bpp embedding")
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)
    plt.tight_layout()
    save_figure(fig1, RDIR / "lsb_row_density.png")

    # ── Figure 2: Cumulative change fraction ──────────────────────────────────
    fig2, ax2 = plt.subplots(figsize=(13, 5))
    for method in METHODS:
        rc = row_counts[method].astype(float)
        cumsum = np.cumsum(rc)
        total  = cumsum[-1] if cumsum[-1] > 0 else 1
        ax2.plot(rows, cumsum / total, color=METHOD_COLORS[method], linewidth=2,
                 label=method)
    # Ideal uniform line
    ax2.plot(rows, rows / (h - 1), color="black", linewidth=1.2,
             linestyle="--", alpha=0.6, label="Ideal uniform")
    ax2.set_xlabel("Row index")
    ax2.set_ylabel("Cumulative fraction of total changes")
    ax2.set_title("Cumulative LSB Change Distribution\n(closer to ideal line = more spatially uniform)")
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)
    plt.tight_layout()
    save_figure(fig2, RDIR / "lsb_cumulative.png")

    output = {
        "file": fname,
        "shape": [h, w],
        "fill_bpp": 1.0,
        "total_changed": {m: int(row_counts[m].sum()) for m in METHODS},
        "uniformity": {
            m: round(1.0 - float(np.std(row_counts[m])) /
                     (float(np.mean(row_counts[m])) + 1e-9), 4)
            for m in METHODS
        },
    }
    save_json(output, RDIR / "lsb_planes.json")
    return output


if __name__ == "__main__":
    run(verbose=True)
