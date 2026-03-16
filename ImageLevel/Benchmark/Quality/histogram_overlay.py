"""
Quality -- §1.2: Histogram Overlay
=====================================
Compares pixel-value histograms: cover vs each stego method.
Uses one representative DICOM file.

Line charts:
  results/histogram_overlay.png  -- PDF overlay (all methods)
  results/histogram_diff.png     -- histogram difference vs cover (line per method)
  results/histogram_overlay.json -- bin statistics

Run:
    cd ImageLevel
    python Benchmark/Quality/histogram_overlay.py
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
N_BINS  = 256   # histogram bins (covering 0..65535 range for 16-bit)


def run(verbose: bool = True) -> dict:
    dcm_files = list_dicom_files()
    dcm_path  = dcm_files[0]
    cover, fname = load_dicom_cover(dcm_path)

    h, w = cover.shape
    n_bits = int(h * w * 0.5)          # 50% fill to make histogram effect visible
    from common import make_random_bits
    bits = make_random_bits(n_bits)

    bin_edges = np.linspace(0, 65535, N_BINS + 1)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

    if verbose:
        print(f"Histogram overlay on: {fname}  ({h}x{w}, 50% fill)")

    cover_hist, _ = np.histogram(cover.ravel(), bins=bin_edges, density=True)

    stego_hists = {}
    for method in METHODS:
        stego = EMBED_FUNCS[method](cover, bits)
        hist, _ = np.histogram(stego.ravel(), bins=bin_edges, density=True)
        stego_hists[method] = hist
        if verbose:
            diff = np.sum(np.abs(hist - cover_hist))
            print(f"  {method:20s}: L1 hist diff = {diff:.6f}")

    # ── Figure 1: Histogram overlay (zoom to occupied range) ─────────────────
    # Find range where cover has pixels
    nonzero_bins = np.where(cover_hist > 0)[0]
    lo, hi = max(0, nonzero_bins[0] - 5), min(N_BINS, nonzero_bins[-1] + 5)

    fig1, ax1 = plt.subplots(figsize=(13, 5))
    ax1.plot(bin_centers[lo:hi], cover_hist[lo:hi],
             color=METHOD_COLORS["Cover"], linewidth=2.5, label="Cover",
             zorder=5)
    for method in METHODS:
        ax1.plot(bin_centers[lo:hi], stego_hists[method][lo:hi],
                 color=METHOD_COLORS[method], linewidth=1.5,
                 linestyle="--" if method != "This Work" else "solid",
                 alpha=0.8, label=method)
    ax1.set_xlabel("Pixel value (16-bit)")
    ax1.set_ylabel("Probability density")
    ax1.set_title(f"Pixel Value Histogram Overlay\n{fname} | 50% capacity fill")
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)
    plt.tight_layout()
    save_figure(fig1, RDIR / "histogram_overlay.png")

    # ── Figure 2: Histogram difference vs cover ───────────────────────────────
    fig2, ax2 = plt.subplots(figsize=(13, 5))
    for method in METHODS:
        diff = stego_hists[method] - cover_hist
        ax2.plot(bin_centers[lo:hi], diff[lo:hi],
                 color=METHOD_COLORS[method], linewidth=1.8,
                 label=f"{method} (L1={np.sum(np.abs(diff)):.5f})")
    ax2.axhline(0, color="black", linewidth=0.8, linestyle="--")
    ax2.set_xlabel("Pixel value (16-bit)")
    ax2.set_ylabel("Histogram delta (stego - cover)")
    ax2.set_title(f"Histogram Difference vs Cover\n(positive = gain, negative = loss of pixel values)")
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)
    plt.tight_layout()
    save_figure(fig2, RDIR / "histogram_diff.png")

    output = {
        "file": fname,
        "n_bins": N_BINS,
        "fill_pct": 50,
        "l1_diff": {m: round(float(np.sum(np.abs(stego_hists[m] - cover_hist))), 6)
                    for m in METHODS},
    }
    save_json(output, RDIR / "histogram_overlay.json")
    return output


if __name__ == "__main__":
    run(verbose=True)
