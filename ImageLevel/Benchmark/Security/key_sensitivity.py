"""
Security -- §7.1: Key Sensitivity (Avalanche Effect)
======================================================
Tests how many chaos embedding positions change when the secret key
is modified by 1, 2, 4, 8, 16, 32, 64 bit flips.

Good security: even 1-bit key change should shuffle >90% of positions
(avalanche effect from the Logistic chaos map).

Line chart:
  results/key_sensitivity_line.png  -- position overlap % vs bit flips
  results/key_sensitivity.json      -- raw data

Run:
    cd ImageLevel
    python Benchmark/Security/key_sensitivity.py
"""

import sys
import random
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
    CHAOS_KEY,
)

RDIR       = results_dir("Security")
BIT_FLIPS  = [0, 1, 2, 4, 8, 16, 32, 64]   # number of bits flipped in key
N_POSITIONS = 2000                           # positions to generate per test
N_REPEATS   = 5                              # repeat with different flip masks, take mean


def _get_positions(cover, roi_mask, key_int, n):
    """Generate n chaos positions using DicomStego internals."""
    from src.zk_stego.dicom_handler import DicomStego
    from src.zk_stego.utils import generate_chaos_key_from_secret
    h, w = cover.shape
    x0, y0 = DicomStego._key_start(key_int, w, h, roi_mask)
    pos_list = DicomStego._roi_positions(
        cover, roi_mask, x0, y0, key_int, n,
        sort_by_entropy=False, exclude=None,
    )
    return set(map(tuple, pos_list))


def _flip_bits(key_int: int, n_flips: int, rng) -> int:
    """Flip n_flips random bits in a 128-bit key integer."""
    bit_positions = rng.sample(range(128), k=min(n_flips, 128))
    result = key_int
    for bp in bit_positions:
        result ^= (1 << bp)
    return result


def _jaccard(set_a, set_b):
    if not set_a and not set_b:
        return 1.0
    return len(set_a & set_b) / len(set_a | set_b)


def run(verbose: bool = True) -> dict:
    dcm_files = list_dicom_files()
    cover, fname = load_dicom_cover(dcm_files[0])

    from src.zk_stego.dicom_handler import DicomHandler
    from src.zk_stego.utils import generate_chaos_key_from_secret

    roi_mask = DicomHandler.detect_roi(cover)
    key_int  = generate_chaos_key_from_secret(CHAOS_KEY)

    if verbose:
        print(f"Key sensitivity on: {fname}")
        print(f"Key (first 32 bits): {key_int & 0xFFFFFFFF:#010x}")
        print(f"Generating {N_POSITIONS} positions, {N_REPEATS} repeats per flip count\n")

    positions_correct = _get_positions(cover, roi_mask, key_int, N_POSITIONS)

    rng = random.Random(42)
    overlap_pct  = []   # mean Jaccard per flip count
    overlap_std  = []

    for n_flips in BIT_FLIPS:
        if n_flips == 0:
            overlap_pct.append(100.0)
            overlap_std.append(0.0)
            if verbose:
                print(f"  flips={n_flips:3d}: overlap=100.00%  (baseline)")
            continue

        jaccards = []
        for _ in range(N_REPEATS):
            key_flipped = _flip_bits(key_int, n_flips, rng)
            positions_flipped = _get_positions(cover, roi_mask, key_flipped, N_POSITIONS)
            j = _jaccard(positions_correct, positions_flipped) * 100
            jaccards.append(j)

        mean_j = float(np.mean(jaccards))
        std_j  = float(np.std(jaccards))
        overlap_pct.append(round(mean_j, 3))
        overlap_std.append(round(std_j, 3))

        if verbose:
            print(f"  flips={n_flips:3d}: overlap={mean_j:.2f}% +/- {std_j:.2f}%")

    # ── Line chart ────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(BIT_FLIPS, overlap_pct, color="#9C27B0", linewidth=2.5,
            marker="o", markersize=8, label="Position overlap %")
    ax.fill_between(
        BIT_FLIPS,
        [max(0, v - s) for v, s in zip(overlap_pct, overlap_std)],
        [min(100, v + s) for v, s in zip(overlap_pct, overlap_std)],
        color="#9C27B0", alpha=0.15,
    )
    ax.axhline(5, color="green", linestyle="--", linewidth=1.2,
               alpha=0.7, label="5% threshold (good sensitivity)")
    ax.axhline(50, color="orange", linestyle="--", linewidth=1.2,
               alpha=0.7, label="50% (moderate)")
    for flip, ov in zip(BIT_FLIPS, overlap_pct):
        ax.annotate(f"{ov:.1f}%", (flip, ov), textcoords="offset points",
                    xytext=(0, 10), ha="center", fontsize=8.5, color="#9C27B0")
    ax.set_xlabel("Number of bits flipped in chaos key")
    ax.set_ylabel("Position overlap with correct key (%)")
    ax.set_title(f"Key Sensitivity -- Avalanche Effect\n"
                 f"{fname} | {N_POSITIONS} positions | {N_REPEATS} repeats/point")
    ax.set_xticks(BIT_FLIPS)
    ax.set_ylim(-5, 115)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    save_figure(fig, RDIR / "key_sensitivity_line.png")

    output = {
        "file":             fname,
        "n_positions":      N_POSITIONS,
        "n_repeats":        N_REPEATS,
        "bit_flips":        BIT_FLIPS,
        "overlap_pct_mean": overlap_pct,
        "overlap_pct_std":  overlap_std,
    }
    save_json(output, RDIR / "key_sensitivity.json")

    if verbose:
        print(f"\n1-bit flip overlap: {overlap_pct[1]:.2f}%  "
              f"(target <5% for good avalanche)")

    return output


if __name__ == "__main__":
    run(verbose=True)
