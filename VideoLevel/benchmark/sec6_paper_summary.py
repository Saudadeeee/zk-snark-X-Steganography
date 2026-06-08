"""
SEC6 Paper Summary — Timing text for IEEE paper.

Generates clear timing statements from benchmark/results/sec6_performance_data.json.
"""

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import RESULTS_DIR

PREPROCESS_STAGES = ("1_extract_idr", "2_safety_filter")
OPERATIONAL_STAGES = (
    "3_zk_prove",
    "4_embed",
    "5_public_embed_reconstruct",
    "6_extract_bits",
    "7_zk_verify",
)


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values)


def _load_rows() -> dict[str, dict]:
    data_path = RESULTS_DIR / "sec6_performance_data.json"
    if not data_path.exists():
        raise FileNotFoundError("sec6_performance_data.json not found. Run sec6 first.")
    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)
    return {
        seq: row
        for seq, row in data.items()
        if isinstance(row, dict) and isinstance(row.get("timings"), dict)
    }


def generate_timing_summary() -> str:
    rows = _load_rows()
    if not rows:
        raise RuntimeError("sec6_performance_data.json does not contain per-sequence timing rows")

    pre_vals: list[float] = []
    op_vals: list[float] = []
    zk_vals: list[float] = []
    total_vals: list[float] = []

    required_stages = PREPROCESS_STAGES + OPERATIONAL_STAGES

    for seq, row in rows.items():
        timings = row["timings"]
        missing = [stage for stage in required_stages if stage not in timings]
        if missing:
            raise RuntimeError(f"{seq}: missing timing stages: {', '.join(missing)}")
        pre_vals.append(sum(float(timings[stage]) for stage in PREPROCESS_STAGES))
        op_vals.append(sum(float(timings[stage]) for stage in OPERATIONAL_STAGES))
        zk_vals.append(float(timings["3_zk_prove"]))
        if "total_s" not in row:
            raise RuntimeError(f"{seq}: missing total_s field")
        total_vals.append(float(row["total_s"]))

    pre_avg = sum(pre_vals) / len(pre_vals)
    op_avg = sum(op_vals) / len(op_vals)
    zk_avg = sum(zk_vals) / len(zk_vals)
    total_avg = sum(total_vals) / len(total_vals)

    lines = [
        "=== SEC6 Timing Summary (IEEE Paper) ===",
        "",
        "Pre-processing Cost (one-time, cacheable):",
        f"  {pre_avg:.1f} s +/- {_std(pre_vals):.1f} s",
        "  Stages: IDR extraction + safety filter",
        "",
        "Operational Cost (per embed):",
        f"  {op_avg:.1f} s +/- {_std(op_vals):.1f} s",
        f"  Public API timing reports standalone ZK prove as {zk_avg:.1f} s +/- {_std(zk_vals):.1f} s",
        "  because proof generation is included inside the combined public embed stage.",
        "",
        "Total End-to-End:",
        f"  {total_avg:.1f} s +/- {_std(total_vals):.1f} s",
        "",
        "Paper Claim Text:",
        f"  The current committed SEC6 artifact reports {pre_avg:.0f}s of one-time pre-processing",
        f"  and {op_avg:.0f}s of operational cost per embed through the public API path.",
        "",
        "By Sequence:",
    ]

    for seq, row in rows.items():
        timings = row["timings"]
        pre = sum(float(timings[stage]) for stage in PREPROCESS_STAGES)
        op = sum(float(timings[stage]) for stage in OPERATIONAL_STAGES)
        zk = float(timings["3_zk_prove"])
        total = float(row.get("total_s", 0.0))
        lines.append(f"  {seq}: pre={pre:.1f}s, op={op:.1f}s, total={total:.1f}s, zk={zk:.1f}s")

    summary = "\n".join(lines) + "\n"
    output_path = RESULTS_DIR / "sec6_paper_summary.txt"
    output_path.write_text(summary, encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(generate_timing_summary(), end="")
