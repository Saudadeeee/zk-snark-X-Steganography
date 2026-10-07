"""Summaries and figures of the method comparison (quality) and the steganalysis results.

    py -3.12 -m benchmark.stego_compare_report_new

Reads benchmark/results/stego_compare/{cif,hd}.jsonl and, if present, the steganalysis
result JSON files; writes stego_compare/summary.json and doc/paper/figures/{quality_qp,
steganalysis}.pdf.
"""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from benchmark.distortion_figures_new import COLORS, INK, MARKERS  # noqa: E402  (shared style)

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmark" / "results" / "stego_compare"
FIGURES = ROOT / "doc" / "paper" / "figures"
METHODS = ("low-drift", "random", "wang2018", "lin2012", "liao2009", "kim2007")
LABELS = {"low-drift": "ours, low-drift", "random": "ours, random", "wang2018": "Wang & Ma 2018",
          "lin2012": "Lin et al. 2012", "liao2009": "Liao-style 2009", "kim2007": "Kim et al. 2007"}
EXTRA_COLORS = ("#e87ba4", "#4a3aa7")


def _rows(dataset: str) -> list[dict]:
    """Rows of a comparison run, de-duplicated on (source, qp, gop, method, rate) (last one wins)."""
    path = RESULTS / f"{dataset}.jsonl"
    if not path.is_file():
        return []
    unique: dict[tuple, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        unique[(row["source"], row["qp"], row["gop"], row["method"], row["rate"])] = row
    return list(unique.values())


def _finite(values: list[float]) -> list[float]:
    return [v for v in values if math.isfinite(v)]


def quality_summary() -> dict:
    """Per dataset, GOP, rate, QP and method: medians over sequences of mean-MSE PSNR and minimum frame PSNR."""
    summary: dict = {}
    for dataset in ("cif", "hd"):
        rows = _rows(dataset)
        for row in rows:
            key = (row["gop"], row["rate"], row["qp"], row["method"])
            entry = summary.setdefault(dataset, {}).setdefault(str(key), {"runs": []})
            entry["runs"].append(row)
        for key, entry in summary.get(dataset, {}).items():
            runs = entry.pop("runs")
            entry.update({
                "sequences": len(runs),
                "psnr_y_median_db": statistics.median(_finite([r["psnr_y_mean_mse"] for r in runs]) or [math.inf]),
                "psnr_y_min_db": min(_finite([r["psnr_y_min"] for r in runs]) or [math.inf]),
                "ssim_y_min": min(r["ssim_y_min"] for r in runs),
                "embedded_bits_mean": statistics.fmean(r["embedded"] for r in runs),
                "changed_per_embedded_bit": statistics.fmean(r["changed"] / max(1, r["embedded"]) for r in runs),
                "bytes_delta_max": max(abs(r["bytes_delta"]) for r in runs),
                "candidates_per_idr": statistics.fmean(r["candidates_per_idr"] for r in runs)})
    return summary


def quality_figure(summary: dict) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.6), sharey=False)
    colors = COLORS + EXTRA_COLORS
    for ax, dataset in zip(axes, ("cif", "hd")):
        data = summary.get(dataset, {})
        for index, method in enumerate(METHODS):
            points = sorted((int(k.split(", ")[2]), v["psnr_y_median_db"]) for k, v in data.items()
                            if k.startswith("(1, 'cap64',") and f"'{method}')" in k)
            if points:
                ax.plot([p[0] for p in points], [p[1] for p in points], color=colors[index],
                        marker=MARKERS[index % len(MARKERS)], markersize=4, label=LABELS[method])
        ax.set_title({"cif": "CIF (8 sequences)", "hd": "native 720p/1080p (19 sequences)"}[dataset],
                     fontsize=8, color=INK)
        ax.set_xlabel("QP (P-frame QP; I-slice QP is 3 lower)")
        ax.set_xticks([18, 22, 28, 34])
    axes[0].set_ylabel("PSNR-Y, all frames [dB]")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, loc="upper center", ncol=6, fontsize=6.5, bbox_to_anchor=(0.5, 1.03))
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(FIGURES / "quality_qp.pdf")
    plt.close(fig)


DETECTORS = ("cavlc", "spam", "srmlite", "cnn")
RATE_ORDER = ("cap64", "rate5", "rate20")


def steganalysis_summary() -> dict:
    """detector -> method -> rate -> {auc, p_e, pairs, frames} from steganalysis_<detector>.json."""
    out: dict = {}
    for detector in DETECTORS:
        path = RESULTS / f"steganalysis_{detector}.json"
        if not path.is_file():
            continue
        for group in json.loads(path.read_text(encoding="utf-8"))["groups"]:
            if "skipped" in group:
                continue
            out.setdefault(detector, {}).setdefault(group["method"], {})[group["rate"]] = {
                "frame_auc": group["frame_auc"], "frame_p_e": group["frame_p_e"],
                "stream_auc": group["stream_auc"], "test_pairs": group["n_test_pairs"],
                "test_frames": group["n_test_frames"]}
    return out


def steganalysis_figure(summary: dict) -> None:
    if not summary:
        return
    colors = COLORS + EXTRA_COLORS
    fig, axes = plt.subplots(1, len(summary), figsize=(7.0, 2.4), sharey=True)
    axes = axes if hasattr(axes, "__len__") else [axes]
    for ax, (detector, by_method) in zip(axes, summary.items()):
        for index, method in enumerate(METHODS):
            rates = by_method.get(method, {})
            xs = [i for i, rate in enumerate(RATE_ORDER) if rate in rates]
            ax.plot(xs, [rates[RATE_ORDER[i]]["frame_p_e"] for i in xs], color=colors[index],
                    marker=MARKERS[index % len(MARKERS)], markersize=4, label=LABELS[method])
        ax.set_title({"cavlc": "CAVLC features", "spam": "SPAM-686", "srmlite": "SRM-lite",
                      "cnn": "CNN (Xu-Net style)"}[detector], fontsize=8, color=INK)
        ax.set_xticks(range(len(RATE_ORDER)), ["64 bits", "5%", "20%"])
        ax.set_ylim(0, 0.55)
        ax.axhline(0.5, color="#c3c2b7", linewidth=0.8)
    axes[0].set_ylabel("Detection error $P_E$ (test)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, loc="upper center", ncol=6, fontsize=6.5, bbox_to_anchor=(0.5, 1.03))
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    fig.savefig(FIGURES / "steganalysis.pdf")
    plt.close(fig)


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    summary = {"quality": quality_summary(), "steganalysis": steganalysis_summary()}
    steganalysis_figure(summary["steganalysis"])
    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    quality_figure(summary["quality"])
    print("summary and figures written")


if __name__ == "__main__":
    main()
