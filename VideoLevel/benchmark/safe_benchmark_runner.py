"""
safe_benchmark_runner.py — Run benchmark with timeout protection and error handling
=====================================================================================
Wrapper script to run benchmark suite safely with:
- Timeout protection (avoid hanging)
- Error isolation (continue on section failure)
- Progress reporting
- Result validation

Usage:
    python safe_benchmark_runner.py [--force] [--sections 1 2 3] [--timeout 180]
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

BENCHMARK_DIR = Path(__file__).parent
RESULTS_DIR = BENCHMARK_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

SECTIONS = {
    1: "sec1_quality",
    2: "sec2_capacity",
    3: "sec3_methods",
    4: "sec4_security",
    5: "sec5_zkp",
    6: "sec6_performance",
}

DEFAULT_TIMEOUT = 180  # 3 minutes per section


def run_section_safe(sec_id: int, force: bool, timeout: int) -> dict:
    """
    Run a benchmark section with timeout protection.
    Returns: {success: bool, time: float, error: str or None, output: str}
    """
    module_name = f"benchmark.{SECTIONS[sec_id]}"
    force_arg = "--force" if force else ""
    
    cmd = [
        sys.executable, "-m", module_name, force_arg
    ]
    
    print(f"  [§{sec_id}] Running {SECTIONS[sec_id]} (timeout={timeout}s) ...")
    
    t0 = time.perf_counter()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=BENCHMARK_DIR.parent,
        )
        elapsed = time.perf_counter() - t0
        
        if result.returncode == 0:
            return {
                "success": True,
                "time": round(elapsed, 2),
                "error": None,
                "output": result.stdout[-500:],  # last 500 chars
            }
        else:
            return {
                "success": False,
                "time": round(elapsed, 2),
                "error": f"Exit code {result.returncode}",
                "output": result.stderr[-500:],
            }
    
    except subprocess.TimeoutExpired:
        elapsed = time.perf_counter() - t0
        return {
            "success": False,
            "time": round(elapsed, 2),
            "error": f"Timeout after {timeout}s",
            "output": None,
        }
    
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return {
            "success": False,
            "time": round(elapsed, 2),
            "error": str(e),
            "output": None,
        }


def validate_results() -> dict:
    """
    Validate benchmark results by checking expected output files.
    Returns: {section_id: {charts: int, data: int, valid: bool}}
    """
    validation = {}
    
    for sec_id, sec_name in SECTIONS.items():
        charts = list(RESULTS_DIR.glob(f"{sec_name}*.png"))
        data = list(RESULTS_DIR.glob(f"{sec_name}*.json"))
        
        # Expected: at least 1 chart and 1 data file per section
        valid = len(charts) >= 1 and len(data) >= 1
        
        validation[sec_id] = {
            "charts": len(charts),
            "data": len(data),
            "valid": valid,
        }
    
    return validation


def print_summary(results: dict, validation: dict) -> None:
    """Print a formatted summary table."""
    print("\n" + "=" * 70)
    print("  BENCHMARK SUMMARY")
    print("=" * 70)
    print(f"  {'Section':<30} {'Status':<10} {'Time':<10} {'Charts':<8} {'Data':<8}")
    print("  " + "-" * 68)
    
    total_time = 0.0
    success_count = 0
    
    for sec_id in sorted(results.keys()):
        r = results[sec_id]
        v = validation.get(sec_id, {"charts": 0, "data": 0, "valid": False})
        
        sec_name = f"§{sec_id} {SECTIONS[sec_id]}"
        status = "[OK]  " if r["success"] else "[FAIL]"
        time_str = f"{r['time']:.1f} s"
        charts_str = f"{v['charts']} PNG"
        data_str = f"{v['data']} JSON"
        
        print(f"  {sec_name:<30} {status:<10} {time_str:<10} {charts_str:<8} {data_str:<8}")
        
        if r["success"]:
            success_count += 1
        total_time += r["time"]
    
    print("  " + "-" * 68)
    print(f"  {'Total':<30} {'':<10} {total_time:.1f} s")
    print()
    print(f"  Passed: {success_count}/{len(results)} sections")
    print(f"  Output: {RESULTS_DIR}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Safe benchmark runner with timeout")
    parser.add_argument("--force", action="store_true",
                        help="Re-run all experiments (ignore cache)")
    parser.add_argument("--sections", type=int, nargs="+",
                        help="Run only these sections (e.g., --sections 1 3 5)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"Timeout per section in seconds (default: {DEFAULT_TIMEOUT})")
    args = parser.parse_args()
    
    sections_to_run = args.sections if args.sections else list(SECTIONS.keys())
    
    print("=" * 70)
    print("  ZK-SNARK x Steganography Benchmark Suite")
    print("=" * 70)
    print(f"  Sections: {sections_to_run}")
    print(f"  Force: {args.force}")
    print(f"  Timeout: {args.timeout}s per section")
    print()
    
    results = {}
    t_start = time.perf_counter()
    
    for sec_id in sections_to_run:
        if sec_id not in SECTIONS:
            print(f"  [warn] Unknown section {sec_id}, skipping")
            continue
        
        result = run_section_safe(sec_id, args.force, args.timeout)
        results[sec_id] = result
        
        if result["success"]:
            print(f"  [§{sec_id}] ✓ Completed in {result['time']:.1f}s")
        else:
            print(f"  [§{sec_id}] ✗ Failed: {result['error']}")
            if result["output"]:
                print(f"  [§{sec_id}] Output: {result['output'][:200]}")
    
    total_elapsed = time.perf_counter() - t_start
    
    # Validate results
    print("\n  Validating output files ...")
    validation = validate_results()
    
    # Print summary
    print_summary(results, validation)
    
    # Save run metadata
    metadata = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_time": round(total_elapsed, 2),
        "sections_run": sections_to_run,
        "results": results,
        "validation": validation,
    }
    metadata_path = RESULTS_DIR / "_run_metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"  Metadata: {metadata_path.name}")
    
    # Exit code: 0 if all passed, 1 if any failed
    failed = [s for s, r in results.items() if not r["success"]]
    if failed:
        print(f"\n  [warn] Failed sections: {failed}")
        sys.exit(1)
    else:
        print("\n  All sections completed successfully.\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
