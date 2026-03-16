"""
Performance — §5.2: Memory Profiling
======================================
Profiles peak RSS during embed pipeline phases using tracemalloc.

Charts:
  results/memory_profile_bar.png  — bar chart of peak memory per phase
  results/memory_profile.json     — raw data

Run:
    cd ImageLevel
    python Benchmark/Performance/memory_profile.py
"""

import sys
import tracemalloc
import gc
from pathlib import Path

BENCH_DIR   = Path(__file__).resolve().parent.parent
PROJECT_DIR = BENCH_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(BENCH_DIR))

import numpy as np
import matplotlib.pyplot as plt
from common import list_dicom_files, save_json, results_dir, CHAOS_KEY, METHOD_COLORS

RDIR = results_dir("Performance")


def _measure_phase(func) -> tuple:
    """Run func() under tracemalloc. Returns (return_val, peak_mb)."""
    gc.collect()
    tracemalloc.start()
    result = func()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, peak / 1024**2


def run(verbose: bool = True) -> dict:
    dcm_files = list_dicom_files()
    dcm = str(dcm_files[0])

    if verbose:
        print(f"Memory profiling on: {Path(dcm).name}\n")

    from src.zk_stego.dicom_handler import DicomHandler, DicomStego
    import gzip, tempfile, os

    measurements = {}

    # Phase 1: DICOM load
    _, peak = _measure_phase(lambda: DicomHandler.load(dcm))
    measurements["DICOM Load"] = round(peak, 2)
    if verbose:
        print(f"  DICOM Load       : {peak:.1f} MB peak")

    # Phase 2: ROI detection
    cover, _, _ = DicomHandler.load(dcm)
    _, peak = _measure_phase(lambda: DicomHandler.detect_roi(cover))
    measurements["ROI Detection"] = round(peak, 2)
    if verbose:
        print(f"  ROI Detection    : {peak:.1f} MB peak")

    # Phase 3: gzip compress
    _, meta_json, _ = DicomHandler.load(dcm)
    _, peak = _measure_phase(lambda: gzip.compress(meta_json.encode(), compresslevel=9))
    measurements["gzip Compress"] = round(peak, 2)
    if verbose:
        print(f"  gzip Compress    : {peak:.1f} MB peak")

    # Phase 4: Full embed (no proof)
    def _embed_no_proof():
        ds = DicomStego()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp = f.name
        try:
            ds.embed(dcm, tmp, chaos_key=CHAOS_KEY, generate_zk_proof=False)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    _, peak = _measure_phase(_embed_no_proof)
    measurements["Full Embed (no ZK)"] = round(peak, 2)
    if verbose:
        print(f"  Full Embed (no ZK): {peak:.1f} MB peak")

    # Phase 5: Full extract
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        stego_tmp = f.name
    DicomStego().embed(dcm, stego_tmp, chaos_key=CHAOS_KEY, generate_zk_proof=False)

    def _extract():
        ds = DicomStego()
        return ds.extract(stego_tmp, chaos_key=CHAOS_KEY, verbose=False)
    _, peak = _measure_phase(_extract)
    measurements["Extract"] = round(peak, 2)
    if os.path.exists(stego_tmp):
        os.unlink(stego_tmp)
    if verbose:
        print(f"  Extract          : {peak:.1f} MB peak")

    save_json(measurements, RDIR / "memory_profile.json")

    # ── Bar chart ─────────────────────────────────────────────────────────────
    phases = list(measurements.keys())
    values = list(measurements.values())
    palette = [METHOD_COLORS["Cover"], METHOD_COLORS["PRNG-LSB"],
               METHOD_COLORS["ACM-only"], METHOD_COLORS["This Work"],
               METHOD_COLORS["Sequential LSB"]][:len(phases)]

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(phases, values, color=palette, edgecolor="white", alpha=0.87)
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                f"{val:.1f} MB", ha="center", va="bottom", fontsize=9.5)
    ax.set_ylabel("Peak RAM allocation (MB)")
    ax.set_title(f"Memory Usage per Pipeline Phase\n({Path(dcm).name}  |  tracemalloc peak)")
    ax.set_ylim(0, max(values) * 1.25)
    plt.xticks(rotation=15, ha="right")
    plt.tight_layout()
    from common import save_figure
    save_figure(fig, RDIR / "memory_profile_bar.png")

    if verbose:
        print(f"\n{'='*40}")
        for k, v in measurements.items():
            print(f"  {k:25s}: {v:.1f} MB")

    return measurements


if __name__ == "__main__":
    run(verbose=True)
