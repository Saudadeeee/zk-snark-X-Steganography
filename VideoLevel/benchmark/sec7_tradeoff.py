"""
Section 7 — Fixed-Payload QP Tradeoff Recommendations
=====================================================

Summarises which all-intra QP operating points satisfy the paper's
quality floor for the fixed Groth16-sized payload.

Inputs:
  - benchmark/results/sec1_quality_data.json

Produces:
  - benchmark/results/sec7_tradeoff_data.json
  - benchmark/results/sec7_qp_feasibility.png
"""

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import RESULTS_DIR, SEQ_LABELS, PALETTE, setup_style, save_fig

SEC1_RESULTS = RESULTS_DIR / "sec1_quality_data.json"
CACHE_KEY_OUT = RESULTS_DIR / "sec7_tradeoff_data.json"

STRICT_THRESHOLD_DB = 40.0
RELAXED_THRESHOLD_DB = 35.0
FIXED_PAYLOAD_BITS = 1232


def _load_sec1_data() -> dict:
    if not SEC1_RESULTS.exists():
        raise FileNotFoundError(f"SEC1 results not found: {SEC1_RESULTS}")
    raw = json.loads(SEC1_RESULTS.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "data" not in raw:
        raise ValueError("Unexpected SEC1 results format")
    return raw["data"]


def _qp_groups(sec1_data: dict) -> dict[str, list[tuple[int, str, dict]]]:
    groups: dict[str, list[tuple[int, str, dict]]] = {}
    for seq, values in sec1_data.items():
        if not seq.endswith("_g1") or "_q" not in seq or seq.endswith("_1000"):
            continue
        base = seq.split("_q", 1)[0]
        qp = int(seq.split("_q", 1)[1].split("_", 1)[0])
        groups.setdefault(base, []).append((qp, seq, values))
    return {base: sorted(items) for base, items in groups.items()}


def collect_data() -> dict:
    sec1_data = _load_sec1_data()
    groups = _qp_groups(sec1_data)

    recommendations: dict[str, dict] = {}
    for base, items in groups.items():
        evaluated = []
        strict_ok = []
        relaxed_ok = []
        for qp, seq, values in items:
            min_psnr = float(values["min_psnr"])
            full_psnr = float(values["psnr_full_video"])
            payload_ok = bool(values["payload_target_met"]) and int(values["embedded_bits"]) >= FIXED_PAYLOAD_BITS
            row = {
                "sequence": seq,
                "label": SEQ_LABELS.get(seq, seq),
                "qp": qp,
                "full_video_psnr_db": full_psnr,
                "frame_min_psnr_db": min_psnr,
                "payload_ok": payload_ok,
            }
            evaluated.append(row)
            if payload_ok and min_psnr >= STRICT_THRESHOLD_DB:
                strict_ok.append(row)
            if payload_ok and min_psnr >= RELAXED_THRESHOLD_DB:
                relaxed_ok.append(row)

        recommendations[base] = {
            "evaluated": evaluated,
            "strict_threshold_db": STRICT_THRESHOLD_DB,
            "relaxed_threshold_db": RELAXED_THRESHOLD_DB,
            "best_qp_strict": max((row["qp"] for row in strict_ok), default=None),
            "best_qp_relaxed": max((row["qp"] for row in relaxed_ok), default=None),
            "strict_pass_qps": [row["qp"] for row in strict_ok],
            "relaxed_pass_qps": [row["qp"] for row in relaxed_ok],
        }

    output = {
        "fixed_payload_bits": FIXED_PAYLOAD_BITS,
        "strict_threshold_db": STRICT_THRESHOLD_DB,
        "relaxed_threshold_db": RELAXED_THRESHOLD_DB,
        "recommendations": recommendations,
    }
    with open(CACHE_KEY_OUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=True, indent=2)
    return output


def plot_qp_feasibility(data: dict) -> None:
    recommendations = data["recommendations"]
    if not recommendations:
        return

    setup_style()
    fig, ax = plt.subplots(figsize=(9, 5))
    colors = [PALETTE["this_work"], PALETTE["f5"], PALETTE["mv"], PALETTE["ipm"]]
    for i, (base, rec) in enumerate(sorted(recommendations.items())):
        evaluated = rec["evaluated"]
        if not evaluated:
            continue
        qps = [row["qp"] for row in evaluated]
        mins = [row["frame_min_psnr_db"] for row in evaluated]
        ax.plot(
            qps, mins,
            color=colors[i % len(colors)],
            linewidth=2.2,
            label=base.capitalize(),
        )
        for row in evaluated:
            marker = "PASS" if row["payload_ok"] and row["frame_min_psnr_db"] >= STRICT_THRESHOLD_DB else "FAIL"
            ax.text(row["qp"], row["frame_min_psnr_db"] + 0.15, marker, fontsize=8, ha="center")

    ax.axhline(STRICT_THRESHOLD_DB, color="#C62828", linestyle="--", linewidth=1.3, label="40 dB strict")
    ax.axhline(RELAXED_THRESHOLD_DB, color="#F9A825", linestyle=":", linewidth=1.3, label="35 dB relaxed")
    ax.set_xlabel("QP (all-intra, GOP=1)")
    ax.set_ylabel("Frame-min PSNR (dB)")
    ax.set_title("§7  Fixed-Payload QP Feasibility")
    ax.legend(fontsize=9)
    save_fig(fig, "sec7_qp_feasibility")


def run() -> dict:
    print("\n=== §7  Fixed-Payload QP Tradeoff ===")
    data = collect_data()
    plot_qp_feasibility(data)

    for base, rec in sorted(data["recommendations"].items()):
        print(
            f"  [{base}] strict<=best_qp {rec['best_qp_strict']}  "
            f"relaxed<=best_qp {rec['best_qp_relaxed']}  "
            f"strict_pass={rec['strict_pass_qps']}"
        )
    return data


if __name__ == "__main__":
    run()
