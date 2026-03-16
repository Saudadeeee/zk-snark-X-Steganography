"""
Performance — §5.4: File Size Overhead
=========================================
Compares source .dcm file size vs output stego .png size.
Reports size increase in KB and percentage.

Charts:
  results/file_size_bar.png   — grouped bar: DCM size vs PNG size per file
  results/file_size.json      — raw data

Run:
    cd ImageLevel
    python Benchmark/Performance/file_size_overhead.py
"""

import sys
import os
import tempfile
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

RDIR = results_dir("Performance")


def run(verbose: bool = True) -> dict:
    from src.zk_stego.dicom_handler import DicomStego

    dcm_files = list_dicom_files()
    if verbose:
        print(f"File size overhead for {len(dcm_files)} DICOM files\n")

    records = []
    for dcm in dcm_files:
        dcm_size_kb = os.path.getsize(dcm) / 1024

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_png = f.name
        try:
            ds = DicomStego()
            ds.embed(str(dcm), tmp_png, chaos_key=CHAOS_KEY,
                     generate_zk_proof=False, verbose=False)
            png_size_kb = os.path.getsize(tmp_png) / 1024
        finally:
            if os.path.exists(tmp_png):
                os.unlink(tmp_png)

        delta_kb = png_size_kb - dcm_size_kb
        overhead_pct = delta_kb / dcm_size_kb * 100

        records.append({
            "file":          dcm.name,
            "dcm_size_kb":   round(dcm_size_kb,  1),
            "png_size_kb":   round(png_size_kb,  1),
            "delta_kb":      round(delta_kb,     1),
            "overhead_pct":  round(overhead_pct, 2),
        })
        if verbose:
            print(f"  {dcm.name:25s}  DCM={dcm_size_kb:.1f} KB  "
                  f"PNG={png_size_kb:.1f} KB  D={delta_kb:+.1f} KB ({overhead_pct:+.1f}%)")

    summary = {
        "per_file": records,
        "dcm_mean_kb":      round(float(np.mean([r["dcm_size_kb"]  for r in records])), 1),
        "png_mean_kb":      round(float(np.mean([r["png_size_kb"]  for r in records])), 1),
        "delta_mean_kb":    round(float(np.mean([r["delta_kb"]     for r in records])), 1),
        "overhead_mean_pct":round(float(np.mean([r["overhead_pct"] for r in records])), 2),
    }
    save_json(summary, RDIR / "file_size.json")

    # ── Grouped bar chart ─────────────────────────────────────────────────────
    labels   = [r["file"].replace(".dcm", "") for r in records]
    dcm_vals = [r["dcm_size_kb"] for r in records]
    png_vals = [r["png_size_kb"] for r in records]

    x       = np.arange(len(labels))
    width   = 0.35

    fig, axes = plt.subplots(1, 2, figsize=(15, 6))

    ax1 = axes[0]
    ax1.bar(x - width/2, dcm_vals, width, label="Source .dcm",
            color=METHOD_COLORS["Cover"], edgecolor="white", alpha=0.85)
    ax1.bar(x + width/2, png_vals, width, label="Stego .png",
            color=METHOD_COLORS["This Work"], edgecolor="white", alpha=0.85)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=30, ha="right", fontsize=8.5)
    ax1.set_ylabel("File size (KB)")
    ax1.set_title("File Size: Source DCM vs Stego PNG\n(no ZK proof)")
    ax1.legend()

    ax2 = axes[1]
    delta_vals    = [r["delta_kb"]     for r in records]
    overhead_vals = [r["overhead_pct"] for r in records]
    bar_colors = [METHOD_COLORS["This Work"] if v >= 0 else METHOD_COLORS["Sequential LSB"]
                  for v in delta_vals]
    bars = ax2.bar(labels, delta_vals, color=bar_colors, edgecolor="white", alpha=0.85)
    for bar, val, pct in zip(bars, delta_vals, overhead_vals):
        ax2.text(bar.get_x() + bar.get_width()/2,
                 bar.get_height() + (0.2 if val >= 0 else -1.2),
                 f"{val:+.1f} KB\n({pct:+.1f}%)",
                 ha="center", va="bottom", fontsize=7.5)
    ax2.axhline(0, color="black", linewidth=0.8)
    ax2.set_ylabel("Size delta (KB)")
    ax2.set_title("File Size Overhead per Image\n(positive = stego PNG is larger)")
    plt.sca(ax2); plt.xticks(rotation=30, ha="right", fontsize=8.5)

    plt.suptitle(
        f"File Size Analysis — DCM -> Stego PNG\n"
        f"Average overhead: {summary['delta_mean_kb']:+.1f} KB ({summary['overhead_mean_pct']:+.1f}%)",
        fontsize=13, y=1.01,
    )
    plt.tight_layout()
    from common import save_figure
    save_figure(fig, RDIR / "file_size_bar.png")

    if verbose:
        print(f"\n{'='*50}")
        print(f"  Mean DCM size : {summary['dcm_mean_kb']:.1f} KB")
        print(f"  Mean PNG size : {summary['png_mean_kb']:.1f} KB")
        print(f"  Mean overhead : {summary['delta_mean_kb']:+.1f} KB ({summary['overhead_mean_pct']:+.1f}%)")

    return summary


if __name__ == "__main__":
    run(verbose=True)
