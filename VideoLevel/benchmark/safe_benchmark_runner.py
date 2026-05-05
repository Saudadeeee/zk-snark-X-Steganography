"""
safe_benchmark_runner.py — Run benchmark with timeout protection and error handling
=====================================================================================
Wrapper script to run benchmark suite safely with:
- Timeout protection (avoid hanging)
- Error isolation (continue on section failure)
- Progress reporting
- Result validation

Usage:
    python safe_benchmark_runner.py [--force] [--fast] [--sections 1 2 3] [--timeout 180]
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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
FAST_CAPABLE_SECTIONS = {1, 2, 3, 4, 6}


def _load_json_file(path: Path) -> tuple[dict | None, str | None]:
    """Load JSON file and return (data, error_message)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
    except Exception as exc:
        return None, f"failed to parse {path.name}: {exc}"
    if not isinstance(obj, dict):
        return None, f"{path.name}: top-level JSON must be an object"
    return obj, None


def _validate_sec1_schema(data: dict) -> list[str]:
    errors: list[str] = []
    required = {
        "psnr_full_video",
        "avg_ssim",
        "embedded_bits",
        "required_bits",
        "payload_target_met",
        "validation_mode",
    }
    if not data:
        return ["sec1: empty JSON object"]
    for seq, payload in data.items():
        if not isinstance(payload, dict):
            errors.append(f"sec1:{seq} must be object")
            continue
        missing = sorted(required - set(payload.keys()))
        if missing:
            errors.append(f"sec1:{seq} missing keys: {', '.join(missing)}")
    return errors


def _validate_sec2_schema(data: dict) -> list[str]:
    errors: list[str] = []
    required = {
        "capacity_bits",
        "validation_applied",
        "rates_pct",
        "psnr_by_rate",
        "embedded_bits_by_rate",
        "effective_rate_t1_pct",
    }
    if not data:
        return ["sec2: empty JSON object"]
    for seq, payload in data.items():
        if not isinstance(payload, dict):
            errors.append(f"sec2:{seq} must be object")
            continue
        missing = sorted(required - set(payload.keys()))
        if missing:
            errors.append(f"sec2:{seq} missing keys: {', '.join(missing)}")
            continue
        rates = payload.get("rates_pct", [])
        psnr_vals = payload.get("psnr_by_rate", [])
        bits_vals = payload.get("embedded_bits_by_rate", [])
        if len(rates) != len(psnr_vals) or len(rates) != len(bits_vals):
            errors.append(
                f"sec2:{seq} length mismatch rates/psnr/embedded: "
                f"{len(rates)}/{len(psnr_vals)}/{len(bits_vals)}"
            )
    return errors


def _validate_sec3_schema(data: dict) -> list[str]:
    errors: list[str] = []
    methods = data.get("methods")
    if not isinstance(methods, dict):
        return ["sec3: missing or invalid 'methods' object"]
    if "This Work (CAVLC T1)" not in methods:
        return ["sec3: missing method 'This Work (CAVLC T1)'"]
    this_work = methods["This Work (CAVLC T1)"]
    if not isinstance(this_work, dict):
        return ["sec3: 'This Work (CAVLC T1)' must be object"]
    required = {"psnr", "validation_mode", "embedded_bits", "requested_bits", "simulated"}
    missing = sorted(required - set(this_work.keys()))
    if missing:
        errors.append(f"sec3: This Work missing keys: {', '.join(missing)}")
    return errors


def _schema_errors_for_section(sec_id: int, data_file: Path) -> list[str]:
    data, err = _load_json_file(data_file)
    if err:
        return [err]
    if sec_id == 1:
        return _validate_sec1_schema(data or {})
    if sec_id == 2:
        return _validate_sec2_schema(data or {})
    if sec_id == 3:
        return _validate_sec3_schema(data or {})
    return []


def _parse_sections(raw_sections: list[str] | None) -> list[int]:
    """Parse section ids from either space-separated or comma-separated CLI input."""
    if not raw_sections:
        return list(SECTIONS.keys())

    parsed: list[int] = []
    for token in raw_sections:
        for part in token.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                parsed.append(int(part))
            except ValueError as exc:
                raise argparse.ArgumentTypeError(
                    f"Invalid section value '{part}'. Use integers like 1 2 3 or 1,2,3"
                ) from exc

    return parsed


def run_section_safe(sec_id: int, force: bool, timeout: int, fast: bool = False) -> dict:
    """
    Run a benchmark section with timeout protection.
    Returns: {success: bool, time: float, error: str or None, output: str}
    """
    module_name = f"benchmark.{SECTIONS[sec_id]}"
    cmd = [sys.executable, "-m", module_name]
    if force:
        cmd.append("--force")
    if fast and sec_id in FAST_CAPABLE_SECTIONS:
        cmd.append("--fast")
    
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
        # Benchmark artifacts are named by section prefix (sec1_*, sec2_*, ...)
        section_prefix = f"sec{sec_id}_"
        charts = list(RESULTS_DIR.glob(f"{section_prefix}*.png"))
        data = list(RESULTS_DIR.glob(f"{section_prefix}*.json"))
        
        # Expected: at least 1 chart and 1 data file per section
        valid = len(charts) >= 1 and len(data) >= 1
        
        schema_errors: list[str] = []
        if data and sec_id in {1, 2, 3}:
            schema_errors = _schema_errors_for_section(sec_id, data[0])

        validation[sec_id] = {
            "charts": len(charts),
            "data": len(data),
            "valid": valid,
            "schema_valid": len(schema_errors) == 0,
            "schema_errors": schema_errors,
        }
    
    return validation


def print_summary(results: dict, validation: dict) -> None:
    """Print a formatted summary table."""
    print("\n" + "=" * 70)
    print("  BENCHMARK SUMMARY")
    print("=" * 70)
    print(f"  {'Section':<30} {'Status':<10} {'Time':<10} {'Charts':<8} {'Data':<8} {'Schema':<8}")
    print("  " + "-" * 78)
    
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
        schema_str = "OK" if v.get("schema_valid", True) else "FAIL"
        
        print(f"  {sec_name:<30} {status:<10} {time_str:<10} {charts_str:<8} {data_str:<8} {schema_str:<8}")

        if not v.get("schema_valid", True):
            for msg in v.get("schema_errors", [])[:2]:
                print(f"    -> {msg}")
        
        if r["success"]:
            success_count += 1
        total_time += r["time"]
    
    print("  " + "-" * 78)
    print(f"  {'Total':<30} {'':<10} {total_time:.1f} s")
    print()
    print(f"  Passed: {success_count}/{len(results)} sections")
    print(f"  Output: {RESULTS_DIR}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Safe benchmark runner with timeout")
    parser.add_argument("--force", action="store_true",
                        help="Re-run all experiments (ignore cache)")
    parser.add_argument("--fast", action="store_true",
                        help="Pass --fast through to supported benchmark sections")
    parser.add_argument("--sections", type=str, nargs="+",
                        help="Run only these sections (e.g., --sections 1 3 5 or --sections 1,3,5)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"Timeout per section in seconds (default: {DEFAULT_TIMEOUT})")
    args = parser.parse_args()

    sections_to_run = _parse_sections(args.sections)
    if not sections_to_run:
        print("[error] No valid sections provided. Use values like --sections 1 2 3 or --sections 1,2,3")
        sys.exit(2)
    
    print("=" * 70)
    print("  ZK-SNARK x Steganography Benchmark Suite")
    print("=" * 70)
    print(f"  Sections: {sections_to_run}")
    print(f"  Force: {args.force}")
    print(f"  Fast: {args.fast}")
    print(f"  Timeout: {args.timeout}s per section")
    print()
    
    results = {}
    t_start = time.perf_counter()
    
    for sec_id in sections_to_run:
        if sec_id not in SECTIONS:
            print(f"  [warn] Unknown section {sec_id}, skipping")
            continue
        
        result = run_section_safe(sec_id, args.force, args.timeout, args.fast)
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
