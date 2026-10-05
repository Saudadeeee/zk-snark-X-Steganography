"""Figures of the distortion-model experiments for doc/paper (PDF, vector).

    py -3.12 -m benchmark.distortion_figures_new
"""
from __future__ import annotations

import csv
import json
import random
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from benchmark.distortion_model_new import OUT  # noqa: E402

FIGURES = Path(__file__).resolve().parents[1] / "doc" / "paper" / "figures"
# Validated categorical slots 1-4 (dataviz reference palette); markers give a second encoding.
COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")
MARKERS = ("o", "s", "^", "D")
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"

plt.rcParams.update({
    "font.family": "serif", "font.size": 8, "axes.labelsize": 8, "legend.fontsize": 7,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5,
    "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 1.5, "pdf.fonttype": 42,
})


def _rows(name: str) -> list[dict[str, str]]:
    with (OUT / name).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _ecdf(ax, values: list[float], **style) -> None:
    ordered = sorted(values)
    ax.step(ordered, [(i + 1) / len(ordered) for i in range(len(ordered))], where="post", **style)


def frame_gain_cdf(summary: dict) -> None:
    """Measured frame-level gain (experiment A) and its prediction from single flips (experiment B)."""
    rows = [r for r in _rows("sequence_frames.csv") if int(r["flips_y"]) and float(r["measured_sse_y"]) > 0]
    single = [float(r["gain"]) for r in _rows("single_flips.csv")
              if r["config"] == "ultrafast" and r["category"] in ("LumaDC", "Luma4x4")]
    by_resolution = summary["A_sequence"]["by_resolution"]
    fig, ax = plt.subplots(figsize=(3.4, 2.5))
    for index, resolution in enumerate(("352x288", "640x480", "1280x960")):
        gains = [float(r["measured_sse_y"]) / float(r["predicted_direct_sse_y"]) for r in rows
                 if r["resolution"] == resolution]
        _ecdf(ax, gains, color=COLORS[index],
              label=f"{resolution}, measured (mean {by_resolution[resolution]['mean_gain']:.1f})")
    flips = round(by_resolution["352x288"]["flips_per_frame_y"])
    rng = random.Random(1)
    simulated = [statistics.fmean(rng.choice(single) for _ in range(flips)) for _ in range(20000)]
    _ecdf(ax, simulated, color=INK, linestyle="--", linewidth=1.2,
          label=f"CIF, predicted from single flips ({flips} flips)")
    ax.set_xscale("log")
    ax.set_xlabel(r"Frame-level gain $G_{\mathrm{frame}}$ (measured SSE / model SSE)")
    ax.set_ylabel("Cumulative share of frames")
    ax.legend(frameon=False, loc="lower right", fontsize=6)
    fig.tight_layout()
    fig.savefig(FIGURES / "frame_gain_cdf.pdf")
    plt.close(fig)


def gain_cdf() -> None:
    rows = _rows("single_flips.csv")
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.4), sharey=True)
    for ax, config in zip(axes, ("ultrafast", "default")):
        for index, category in enumerate(("Luma4x4", "LumaDC", "ChromaAC", "ChromaDC")):
            values = sorted(float(r["gain"]) for r in rows if r["config"] == config and r["category"] == category
                            and float(r["gain"]) > 0)
            if not values:
                continue
            ax.step(values, [(i + 1) / len(values) for i in range(len(values))], where="post", color=COLORS[index],
                    label=f"{category} (n={len(values)})")
            ax.plot(values[len(values) // 2], 0.5, marker=MARKERS[index], color=COLORS[index], markersize=5)
        ax.set_xscale("log")
        ax.set_xlabel("Propagation gain $G$ (single flip)")
        ax.set_title({"ultrafast": "x264 ultrafast (I16x16, no deblocking)",
                      "default": "x264 medium (I4x4+I16x16, deblocking)"}[config], fontsize=8, color=INK)
        ax.legend(frameon=False, loc="lower right")
    axes[0].set_ylabel("Cumulative share of flips")
    fig.tight_layout()
    fig.savefig(FIGURES / "gain_cdf.pdf")
    plt.close(fig)


POLICIES = (("expected", "expected gain"), ("p95", "p95, single-flip MC"), ("p95_sequence", "p95, sequence data"))


def inverse_check(summary: dict) -> None:
    rows = _rows("inverse_check.csv")
    targets = sorted({float(r["target_db"]) for r in rows})
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.6), sharey=True)
    for ax, config in zip(axes, ("ultrafast", "default")):
        for t_index, target in enumerate(targets):
            ax.plot([t_index - 0.42, t_index + 0.42], [target, target], color=INK, linewidth=1)
            for p_index, (policy, _) in enumerate(POLICIES):
                part = [r for r in rows if r["config"] == config and float(r["target_db"]) == target
                        and r["policy"] == policy]
                if not part:
                    continue
                values = sorted(float(r["psnr_y"]) for r in part)
                pick = lambda q: values[int(q * (len(values) - 1))]  # noqa: E731
                x = t_index + (p_index - 1) * 0.27
                ax.plot([x, x], [pick(0.05), pick(0.95)], color=COLORS[p_index], linewidth=1)
                ax.add_patch(plt.Rectangle((x - 0.08, pick(0.25)), 0.16, pick(0.75) - pick(0.25),
                                           facecolor="white", edgecolor=COLORS[p_index], linewidth=1))
                ax.plot([x - 0.08, x + 0.08], [pick(0.5)] * 2, color=COLORS[p_index], linewidth=1.5)
                if sum(r["saturated"] == "1" for r in part) > len(part) / 2:  # most frames saturated
                    ax.text(x, pick(0.05) - 0.6, "sat.", ha="center", va="top", fontsize=6, color=MUTED)
        ax.set_xticks(range(len(targets)), [f"T = {t:.0f} dB" for t in targets])
        ax.set_title({"ultrafast": "x264 ultrafast", "default": "x264 medium"}[config], fontsize=8, color=INK)
    axes[0].set_ylabel("Per-frame PSNR-Y [dB]")
    handles = [plt.Line2D([], [], color=COLORS[i], linewidth=2, label=label) for i, (_, label) in enumerate(POLICIES)]
    handles.append(plt.Line2D([], [], color=INK, linewidth=1, label="target T"))
    fig.legend(handles=handles, frameon=False, loc="upper center", ncol=4, bbox_to_anchor=(0.5, 1.02))
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(FIGURES / "inverse_check.pdf")
    plt.close(fig)


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    summary = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    frame_gain_cdf(summary)
    gain_cdf()
    inverse_check(summary)
    print("figures written to", FIGURES.relative_to(Path.cwd()) if FIGURES.is_relative_to(Path.cwd()) else FIGURES)


if __name__ == "__main__":
    main()
