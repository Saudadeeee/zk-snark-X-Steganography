"""
System Comparison -- §6: Capability Radar Chart
=================================================
Spider/radar chart comparing 3 approaches on 8 qualitative dimensions:
  - This Work (Groth16 + DicomStego)
  - Stego Only (DicomStego, no proof)
  - Stego + ECDSA (DicomStego + ECDSA P-256 signature)

Charts:
  results/capability_radar.png   -- radar chart (8 dimensions, 3 systems)
  results/capability_radar.json  -- scores + metadata

Run:
    cd ImageLevel
    python Benchmark/SystemComparison/capability_radar.py
"""

import sys
from pathlib import Path

BENCH_DIR   = Path(__file__).resolve().parent.parent
PROJECT_DIR = BENCH_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(BENCH_DIR))

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch
from common import save_figure, save_json, results_dir

RDIR = results_dir("SystemComparison")

# ── Dimensions and scores (0-5, 5=best) ──────────────────────────────────────
DIMENSIONS = [
    "Small proof\noverhead",
    "Fast\nverification",
    "Fast\nproving",
    "Zero-knowledge\nprivacy",
    "No trusted\nsetup",
    "Post-quantum\nresistant",
    "DICOM\nembeddable",
    "Tamper\ndetection",
]

# Scores per method: [dim0, dim1, ..., dim7]
SCORES = {
    "This Work (Groth16)": [4, 4, 2, 5, 2, 1, 5, 5],
    "Stego Only":          [5, 5, 5, 1, 5, 3, 5, 1],
    "Stego + ECDSA":       [5, 5, 5, 1, 5, 1, 4, 4],
}

COLORS = {
    "This Work (Groth16)": "#9C27B0",  # purple
    "Stego Only":          "#2196F3",  # blue
    "Stego + ECDSA":       "#4CAF50",  # green
}

SCORE_NOTES = {
    "Small proof overhead": "Groth16=192B(4), ECDSA~72B(5), None(5)",
    "Fast verification":    "Groth16 ~2ms(4), ECDSA ~0.1ms(5), reextract(5)",
    "Fast proving":         "Groth16 ~2-3s(2), ECDSA ~0.14ms(5), none(5)",
    "Zero-knowledge privacy": "Groth16 full ZK(5), others none(1)",
    "No trusted setup":     "Groth16 circuit-specific setup(2), others none(5)",
    "Post-quantum resistant": "None are PQ; chaos adds obscurity(3 Stego)",
    "DICOM embeddable":     "Groth16 192B fits(5), ECDSA 72B fits(4), none(5)",
    "Tamper detection":     "Groth16 cryptographic(5), ECDSA strong(4), none(1)",
}


def run(verbose: bool = True) -> dict:
    N = len(DIMENSIONS)
    angles = [n / float(N) * 2 * np.pi for n in range(N)]
    angles += angles[:1]  # close the polygon

    fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(polar=True))

    # Draw gridlines and axis labels
    ax.set_theta_offset(np.pi / 2)  # start at top
    ax.set_theta_direction(-1)       # clockwise
    ax.set_rlabel_position(0)
    ax.set_ylim(0, 5)
    ax.set_yticks([1, 2, 3, 4, 5])
    ax.set_yticklabels(["1", "2", "3", "4", "5"], fontsize=8, color="gray")
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(DIMENSIONS, fontsize=10.5, fontweight="bold")

    # Plot each method
    for method, scores in SCORES.items():
        color = COLORS[method]
        values = scores + scores[:1]
        ax.plot(angles, values, color=color, linewidth=2.5, linestyle="solid",
                marker="o", markersize=7, label=method)
        ax.fill(angles, values, color=color, alpha=0.18)
        if verbose:
            print(f"  {method:30s}: {scores}")

    # Title and legend
    ax.set_title(
        "Capability Comparison: This Work vs Alternatives\n",
        fontsize=14, fontweight="bold", pad=20,
    )
    fig.text(
        0.5, 0.02,
        "Qualitative scores 0-5 (5=best) -- indicative only, not formally derived.\n"
        "Dimensions reflect design tradeoffs; individual scores are subjective assessments.",
        ha="center", fontsize=9, color="gray", style="italic",
    )
    ax.legend(
        loc="upper right",
        bbox_to_anchor=(1.35, 1.15),
        fontsize=11,
        framealpha=0.85,
    )

    plt.tight_layout()
    save_figure(fig, RDIR / "capability_radar.png")

    result = {
        "dimensions": DIMENSIONS,
        "methods": {m: {"scores": s} for m, s in SCORES.items()},
        "score_notes": SCORE_NOTES,
        "score_range": "0-5 (5=best)",
        "note": "Qualitative scores -- indicative only, not formally derived",
    }
    save_json(result, RDIR / "capability_radar.json")

    if verbose:
        print(f"\nSaved: {RDIR / 'capability_radar.png'}")

    return result


if __name__ == "__main__":
    run(verbose=True)
