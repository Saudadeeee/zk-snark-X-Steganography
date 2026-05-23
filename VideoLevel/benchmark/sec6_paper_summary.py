"""
SEC6 Paper Summary — Timing text for IEEE paper.

Generates clear, citable timing statements for manuscript.

Outputs:
    - Pre-processing cost (one-time, cacheable)
    - Operational cost (per-embed, repeated)
    - Total end-to-end cost
"""

import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import RESULTS_DIR


def generate_timing_summary():
    """Generate timing summary text for paper."""
    data_path = RESULTS_DIR / "sec6_performance_data.json"

    if not data_path.exists():
        print("Error: sec6_performance_data.json not found. Run sec6 first.")
        return

    with open(data_path) as f:
        data = json.load(f)

    # Calculate averages across sequences
    pre_processing_stages = ["1_extract_idr", "2_safety_filter"]
    operational_stages = [
        "3_zk_prove",
        "4_validation",
        "5_embed",
        "6_reconstruct",
        "7_extract",
    ]

    seq_timings = data.get("timings", {})

    # Pre-processing average (one-time)
    pre_avg = 0.0
    pre_vals = []
    for seq, timings in seq_timings.items():
        total_pre = sum(timings.get(s, 0.0) for s in pre_processing_stages)
        pre_vals.append(total_pre)
    pre_avg = sum(pre_vals) / len(pre_vals) if pre_vals else 0.0

    # Operational average (per-embed)
    op_avg = 0.0
    op_vals = []
    for seq, timings in seq_timings.items():
        total_op = sum(timings.get(s, 0.0) for s in operational_stages)
        op_vals.append(total_op)
    op_avg = sum(op_vals) / len(op_vals) if op_vals else 0.0

    # ZK proof generation
    zk_avg = 0.0
    zk_vals = []
    for seq, timings in seq_timings.items():
        zk_vals.append(timings.get("3_zk_prove", 0.0))
    zk_avg = sum(zk_vals) / len(zk_vals) if zk_vals else 0.0

    # Generate paper-ready text
    summary = f"""
=== SEC6 Timing Summary (IEEE Paper) ===

Pre-processing Cost (one-time, cacheable):
  {pre_avg:.1f} s ± {_std(pre_vals):.1f} s
  Stages: IDR extraction + safety filter
  Status: Run once per video; results cached for all subsequent embeddings

Operational Cost (per-embed, repeated):
  {op_avg:.1f} s ± {_std(op_vals):.1f} s
  Stages: ZK proof ({zk_avg:.1f} s) + validation + embedding + reconstruction + extraction

ZK Proof Generation:
  {zk_avg:.1f} s ± {_std(zk_vals):.1f} s (Groth16, 18680 constraints)

Paper Claim Text:
  "The system requires {pre_avg:.0f}s of one-time pre-processing per video
   (IDR extraction and safety filtering), which can be cached across multiple
   embeddings. The operational cost per embedding is {op_avg:.0f}s, with
   ZK proof generation accounting for {zk_avg:.0f}s of this time."

Cite as:
  "Pre-processing: {pre_avg:.1f}s (one-time, cacheable); per-embed: {op_avg:.1f}s"

By Sequence:
"""
    for seq, timings in seq_timings.items():
        total_pre = sum(timings.get(s, 0.0) for s in pre_processing_stages)
        total_op = sum(timings.get(s, 0.0) for s in operational_stages)
        zk_time = timings.get("3_zk_prove", 0.0)
        summary += f"  {seq}: pre={total_pre:.1f}s, op={total_op:.1f}s, zk={zk_time:.1f}s\n"

    print(summary)

    # Save to file
    output_path = RESULTS_DIR / "sec6_paper_summary.txt"
    output_path.write_text(summary)
    print(f"\nSaved to: {output_path}")


def _std(values: list[float]) -> float:
    """Calculate standard deviation."""
    import statistics
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values)


if __name__ == "__main__":
    generate_timing_summary()