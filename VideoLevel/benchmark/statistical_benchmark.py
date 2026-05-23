"""
Statistical benchmark wrapper for error bars and confidence intervals.

Runs each benchmark multiple times (default 3) and aggregates results
with mean ± std deviation for IEEE TIP/TIFS statistical validity.

Usage:
    python benchmark/statistical_benchmark.py --section sec1 --runs 3
"""

import argparse
import json
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import OUTPUT_DIR, RESULTS_DIR


def run_benchmark_section(section: str, run_id: int) -> Dict[str, Any]:
    """Run a single benchmark section and return results.

    Args:
        section: Benchmark section name (sec1, sec2, etc.)
        run_id: Run identifier for this iteration

    Returns:
        Dictionary of results from the benchmark run
    """
    module_name = f"benchmark.{section}"
    try:
        module = __import__(module_name, fromlist=["main"])
    except ImportError as e:
        raise ImportError(f"Cannot import benchmark module {module_name}: {e}")

    # Set environment to tag results with run_id
    os.environ["STATISTICAL_RUN_ID"] = str(run_id)

    # Run the benchmark
    result_path = RESULTS_DIR / f"{section}_run{run_id}.json"
    args = [f"--output={result_path}"]

    # Call main with args
    old_argv = sys.argv
    sys.argv = [f"{section}.py"] + args
    try:
        module.main()
    finally:
        sys.argv = old_argv

    # Load results
    if result_path.exists():
        with open(result_path, "r") as f:
            return json.load(f)
    return {}


def aggregate_results(
    section: str,
    results: List[Dict[str, Any]],
    metrics: List[str],
) -> Dict[str, Any]:
    """Aggregate multiple runs into statistical summary.

    Args:
        section: Benchmark section name
        results: List of result dictionaries from each run
        metrics: List of metric keys to aggregate (e.g., psnr, chi_p, timing)

    Returns:
        Dictionary with mean ± std for each metric
    """
    aggregated = {
        "section": section,
        "runs": len(results),
        "timestamp": datetime.now().isoformat(),
        "metrics": {},
        "by_sequence": {},
    }

    # Collect values per metric per sequence
    for metric in metrics:
        values_by_sequence: Dict[str, List[float]] = {}

        for run in results:
            if metric in run:
                if isinstance(run[metric], (int, float)):
                    # Global metric
                    values_by_sequence.setdefault("_global", []).append(float(run[metric]))
                elif isinstance(run[metric], dict):
                    # Per-sequence metric
                    for seq, val in run[metric].items():
                        if isinstance(val, (int, float)):
                            values_by_sequence.setdefault(seq, []).append(float(val))

        # Compute stats
        for seq, values in values_by_sequence.items():
            if len(values) < 2:
                # Not enough runs for std, just store value
                if seq == "_global":
                    aggregated["metrics"][f"{metric}_mean"] = values[0]
                    aggregated["metrics"][f"{metric}_std"] = 0.0
                else:
                    aggregated["by_sequence"].setdefault(seq, {})[f"{metric}_mean"] = values[0]
                    aggregated["by_sequence"][seq][f"{metric}_std"] = 0.0
            else:
                mean_val = statistics.mean(values)
                std_val = statistics.stdev(values) if len(values) > 1 else 0.0

                if seq == "_global":
                    aggregated["metrics"][f"{metric}_mean"] = mean_val
                    aggregated["metrics"][f"{metric}_std"] = std_val
                    aggregated["metrics"][f"{metric}_values"] = values
                else:
                    aggregated["by_sequence"].setdefault(seq, {})[f"{metric}_mean"] = mean_val
                    aggregated["by_sequence"][seq][f"{metric}_std"] = std_val
                    aggregated["by_sequence"][seq][f"{metric}_values"] = values

    return aggregated


def main():
    parser = argparse.ArgumentParser(
        description="Run statistical benchmarks with error bars"
    )
    parser.add_argument(
        "--section",
        type=str,
        default="sec1",
        help="Benchmark section to run (sec1, sec2, sec4, sec6)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of runs per sequence (default: 3, min: 3 for IEEE)",
    )
    parser.add_argument(
        "--metrics",
        type=str,
        nargs="+",
        default=["psnr", "chi_p", "embedding_time", "extraction_time"],
        help="Metrics to aggregate with error bars",
    )
    args = parser.parse_args()

    if args.runs < 3:
        print("Warning: IEEE TIP/TIFS requires at least 3 runs for statistical validity")

    print(f"Running {args.section} benchmark {args.runs} times...")

    results = []
    for run_id in range(1, args.runs + 1):
        print(f"Run {run_id}/{args.runs}...", end=" ", flush=True)
        result = run_benchmark_section(args.section, run_id)
        results.append(result)
        print("done")

    # Aggregate
    print("Aggregating results...")
    aggregated = aggregate_results(args.section, results, args.metrics)

    # Save aggregated results
    output_path = RESULTS_DIR / f"{args.section}_statistical.json"
    with open(output_path, "w") as f:
        json.dump(aggregated, f, indent=2)

    print(f"Results saved to {output_path}")

    # Print summary
    print("\n=== Statistical Summary ===")
    for metric, values in aggregated.get("metrics", {}).items():
        if metric.endswith("_mean"):
            base_name = metric[:-5]
            std_val = aggregated["metrics"].get(f"{base_name}_std", 0)
            print(f"{base_name}: {values:.3f} ± {std_val:.3f}")

    if aggregated["by_sequence"]:
        print("\n=== Per-Sequence Results ===")
        for seq, metrics in aggregated["by_sequence"].items():
            print(f"\n{seq}:")
            for metric, val in metrics.items():
                if metric.endswith("_mean"):
                    base_name = metric[:-5]
                    std_val = metrics.get(f"{base_name}_std", 0)
                    print(f"  {base_name}: {val:.3f} ± {std_val:.3f}")


if __name__ == "__main__":
    main()