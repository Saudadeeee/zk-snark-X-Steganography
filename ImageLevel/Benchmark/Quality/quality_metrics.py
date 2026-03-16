"""
Quality -- §1.1: Image Quality Metrics
========================================
For every DICOM test file x every embedding method, compute:
  PSNR (dB), SSIM, MSE, BPP

Line charts (one line per method across files):
  results/quality_psnr_line.png   -- PSNR vs file index
  results/quality_ssim_line.png   -- SSIM vs file index
  results/quality_summary_bar.png -- mean PSNR/SSIM bar chart
  results/quality_metrics.json    -- raw data

Run:
    cd ImageLevel
    python Benchmark/Quality/quality_metrics.py
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
    list_dicom_files, load_dicom_cover, make_stego_pair,
    psnr, ssim, mse_metric, bpp,
    save_figure, save_json, results_dir,
    METHOD_COLORS, METHOD_ORDER, EMBED_FUNCS, CHAOS_KEY,
)

RDIR    = results_dir("Quality")
METHODS = [m for m in METHOD_ORDER if m != "Cover"]


def run(verbose: bool = True) -> dict:
    dcm_files = list_dicom_files()
    file_names = [f.stem for f in dcm_files]

    if verbose:
        print(f"Quality metrics on {len(dcm_files)} DICOM files x {len(METHODS)} methods\n")

    # results[method][metric] = list of values (one per file)
    results = {m: {"psnr": [], "ssim": [], "mse": [], "bpp": []} for m in METHODS}

    for fi, dcm_path in enumerate(dcm_files):
        cover, fname = load_dicom_cover(dcm_path)
        h, w = cover.shape
        n_bits = int(h * w * 0.1)          # 10% fill for quality measurement
        from common import make_random_bits
        bits = make_random_bits(n_bits)

        if verbose:
            print(f"  [{fi+1:2d}/{len(dcm_files)}] {fname}")

        for method in METHODS:
            embed_fn = EMBED_FUNCS[method]
            stego = embed_fn(cover, bits)
            p  = psnr(cover, stego)
            s  = ssim(cover, stego)
            m2 = mse_metric(cover, stego)
            b  = bpp(stego, n_bits)
            results[method]["psnr"].append(round(p, 2))
            results[method]["ssim"].append(round(s, 4))
            results[method]["mse"].append(round(m2, 4))
            results[method]["bpp"].append(round(b, 4))
            if verbose:
                print(f"      {method:18s}: PSNR={p:.2f}dB  SSIM={s:.4f}  MSE={m2:.2f}")

    # Means
    means = {m: {k: round(float(np.mean(v)), 4) for k, v in results[m].items()}
             for m in METHODS}

    # ── Figure 1: PSNR line chart ─────────────────────────────────────────────
    fig1, ax1 = plt.subplots(figsize=(12, 5))
    x = range(1, len(dcm_files) + 1)
    for method in METHODS:
        c = METHOD_COLORS[method]
        ax1.plot(x, results[method]["psnr"], color=c, linewidth=2, marker="o",
                 markersize=6, label=method)
    ax1.set_xlabel("DICOM file index")
    ax1.set_ylabel("PSNR (dB)")
    ax1.set_title("Image Quality: PSNR vs DICOM File\n(10% capacity fill, all embedding methods)")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels([f.stem[:8] for f in dcm_files], rotation=30, ha="right", fontsize=8)
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)
    plt.tight_layout()
    save_figure(fig1, RDIR / "quality_psnr_line.png")

    # ── Figure 2: SSIM line chart ─────────────────────────────────────────────
    fig2, ax2 = plt.subplots(figsize=(12, 5))
    for method in METHODS:
        c = METHOD_COLORS[method]
        ax2.plot(x, results[method]["ssim"], color=c, linewidth=2, marker="s",
                 markersize=6, label=method)
    ax2.set_xlabel("DICOM file index")
    ax2.set_ylabel("SSIM")
    ax2.set_title("Image Quality: SSIM vs DICOM File\n(10% capacity fill)")
    ax2.set_xticks(list(x))
    ax2.set_xticklabels([f.stem[:8] for f in dcm_files], rotation=30, ha="right", fontsize=8)
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(0.9, 1.005)
    plt.tight_layout()
    save_figure(fig2, RDIR / "quality_ssim_line.png")

    # ── Figure 3: Mean summary bar chart ─────────────────────────────────────
    fig3, axes3 = plt.subplots(1, 2, figsize=(12, 5))
    mean_psnr = [means[m]["psnr"] for m in METHODS]
    mean_ssim = [means[m]["ssim"] for m in METHODS]
    colors = [METHOD_COLORS[m] for m in METHODS]

    ax = axes3[0]
    bars = ax.bar(METHODS, mean_psnr, color=colors, edgecolor="white", alpha=0.87)
    for bar, val in zip(bars, mean_psnr):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.2,
                f"{val:.1f}", ha="center", fontsize=9)
    ax.set_ylabel("Mean PSNR (dB)")
    ax.set_title("Mean PSNR (all files)")
    ax.set_xticks(range(len(METHODS)))
    ax.set_xticklabels(METHODS, rotation=20, ha="right", fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")

    ax = axes3[1]
    bars = ax.bar(METHODS, mean_ssim, color=colors, edgecolor="white", alpha=0.87)
    for bar, val in zip(bars, mean_ssim):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.0002,
                f"{val:.4f}", ha="center", fontsize=9)
    ax.set_ylabel("Mean SSIM")
    ax.set_title("Mean SSIM (all files)")
    ax.set_xticks(range(len(METHODS)))
    ax.set_xticklabels(METHODS, rotation=20, ha="right", fontsize=9)
    ax.set_ylim(0.99, 1.001)
    ax.grid(True, alpha=0.3, axis="y")

    plt.suptitle("Quality Metrics Summary (mean across all DICOM files)", fontsize=12)
    plt.tight_layout()
    save_figure(fig3, RDIR / "quality_summary_bar.png")

    output = {
        "n_files":      len(dcm_files),
        "methods":      METHODS,
        "fill_bpp_pct": 10,
        "per_file":     {m: results[m] for m in METHODS},
        "means":        means,
        "file_names":   file_names,
    }
    save_json(output, RDIR / "quality_metrics.json")

    if verbose:
        print(f"\n{'Method':20s}  {'Mean PSNR':>10s}  {'Mean SSIM':>10s}")
        print("-" * 44)
        for m in METHODS:
            print(f"  {m:18s}  {means[m]['psnr']:>10.2f}  {means[m]['ssim']:>10.4f}")

    return output


if __name__ == "__main__":
    run(verbose=True)
