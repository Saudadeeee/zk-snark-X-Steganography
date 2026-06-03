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
    31: "sec3_ablation",
    32: "blind_sync_diagnostic",
    33: "public_api_realization",
    34: "blind_core_trial",
    35: "validated_pool_proxy_diagnostic",
    36: "blind_contract_operating_point",
    37: "blind_header_body_diagnostic",
    38: "blind_header_stability_diagnostic",
    39: "blind_header_redundancy_diagnostic",
    40: "blind_body_redundancy_diagnostic",
    41: "blind_payload_coding_diagnostic",
    42: "blind_partial_payload_contract",
    43: "blind_real_proof_header_diagnostic",
}

DEFAULT_TIMEOUT = 180  # 3 minutes per section
FAST_CAPABLE_SECTIONS = {1, 2, 3, 4, 6, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43}
PAPER_GRADE_DEFAULT = [1, 2, 3, 4, 6]
DIAGNOSTIC_DEFAULT = [31, 32]
SECTION_CLASS = {
    1: "paper_grade",
    2: "paper_grade",
    3: "paper_grade",
    4: "paper_grade",
    5: "paper_grade",
    6: "paper_grade",
    31: "diagnostic_grade",
    32: "diagnostic_grade",
    33: "diagnostic_grade",
    34: "diagnostic_grade",
    35: "diagnostic_grade",
    36: "diagnostic_grade",
    37: "diagnostic_grade",
    38: "diagnostic_grade",
    39: "diagnostic_grade",
    40: "diagnostic_grade",
    41: "diagnostic_grade",
    42: "diagnostic_grade",
    43: "diagnostic_grade",
}
ARTIFACT_SPEC = {
    1: {
        "charts": ["sec1_*.png"],
        "data": ["sec1_quality_data.json"],
    },
    2: {
        "charts": ["sec2_*.png"],
        "data": ["sec2_capacity_data.json"],
    },
    3: {
        "charts": ["sec3_psnr_comparison.png", "sec3_overhead_comparison.png", "sec3_radar_chart.png"],
        "data": ["sec3_methods_data.json"],
    },
    4: {
        "charts": ["sec4_*.png"],
        "data": ["sec4_security_data.json"],
    },
    5: {
        "charts": ["sec5_*.png"],
        "data": ["sec5_*.json"],
    },
    6: {
        "charts": ["sec6_*.png"],
        "data": ["sec6_performance_data.json"],
    },
    31: {
        "charts": ["sec3_ablation.png"],
        "data": ["sec3_ablation_data.json"],
    },
    32: {
        "charts": [],
        "data": ["blind_sync_diagnostic.json"],
    },
    33: {
        "charts": [],
        "data": ["public_api_realization.json"],
    },
    34: {
        "charts": [],
        "data": ["blind_core_trial.json"],
    },
    35: {
        "charts": [],
        "data": ["validated_pool_proxy_diagnostic.json"],
    },
    36: {
        "charts": ["blind_contract_operating_point.png"],
        "data": ["blind_contract_operating_point.json"],
    },
    37: {
        "charts": [],
        "data": ["blind_header_body_diagnostic.json"],
    },
    38: {
        "charts": [],
        "data": ["blind_header_stability_diagnostic.json"],
    },
    39: {
        "charts": [],
        "data": ["blind_header_redundancy_diagnostic.json"],
    },
    40: {
        "charts": [],
        "data": ["blind_body_redundancy_diagnostic.json"],
    },
    41: {
        "charts": [],
        "data": ["blind_payload_coding_diagnostic.json"],
    },
    42: {
        "charts": [],
        "data": ["blind_partial_payload_contract.json"],
    },
    43: {
        "charts": [],
        "data": ["blind_real_proof_header_diagnostic.json"],
    },
}


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
        "raw_safe_bits",
        "patchable_usable_bits",
        "validated_bits",
        "zk_blob_bits",
        "fractions_pct",
        "bits_at_fraction",
        "psnr_at_fraction",
    }
    if not data:
        return []
    for seq, payload in data.items():
        if not isinstance(payload, dict):
            errors.append(f"sec2:{seq} must be object")
            continue
        missing = sorted(required - set(payload.keys()))
        if missing:
            errors.append(f"sec2:{seq} missing keys: {', '.join(missing)}")
            continue
        rates = payload.get("fractions_pct", [])
        psnr_vals = payload.get("psnr_at_fraction", [])
        bits_vals = payload.get("bits_at_fraction", [])
        if len(rates) != len(psnr_vals) or len(rates) != len(bits_vals):
            errors.append(
                f"sec2:{seq} length mismatch fractions/psnr/bits: "
                f"{len(rates)}/{len(psnr_vals)}/{len(bits_vals)}"
            )
    return errors


def _validate_sec3_schema(data: dict) -> list[str]:
    errors: list[str] = []
    methods = data.get("methods")
    if not isinstance(methods, dict):
        return ["sec3: missing or invalid 'methods' object"]
    protocol = data.get("comparison_protocol")
    if protocol is not None and not isinstance(protocol, dict):
        errors.append("sec3: comparison_protocol must be an object when present")
    if "This Work (CAVLC T1)" not in methods:
        return ["sec3: missing method 'This Work (CAVLC T1)'"]
    this_work = methods["This Work (CAVLC T1)"]
    if not isinstance(this_work, dict):
        return ["sec3: 'This Work (CAVLC T1)' must be object"]
    required = {
        "psnr",
        "validation_mode",
        "embedded_bits",
        "requested_bits",
        "capacity_context",
        "method_group",
        "measurement_type",
        "simulated",
    }
    missing = sorted(required - set(this_work.keys()))
    if missing:
        errors.append(f"sec3: This Work missing keys: {', '.join(missing)}")
    return errors


def _schema_errors_for_section(sec_id: int, data_file: Path) -> list[str]:
    data, err = _load_json_file(data_file)
    if err:
        return [err]
    if isinstance(data, dict) and "__meta__" in data and "data" in data and isinstance(data["data"], dict):
        data = data["data"]
    if sec_id == 1:
        return _validate_sec1_schema(data or {})
    if sec_id == 2:
        return _validate_sec2_schema(data or {})
    if sec_id == 3:
        return _validate_sec3_schema(data or {})
    if sec_id == 31:
        if not isinstance(data, dict) or "variants" not in data:
            return ["sec3a: missing or invalid 'variants' object"]
        return []
    if sec_id == 32:
        if not isinstance(data, dict) or "set_overlap_ratio" not in data:
            return ["blind_sync: missing overlap metrics"]
        return []
    if sec_id == 33:
        if not isinstance(data, dict):
            return ["public_api_realization: top-level JSON must be an object"]
        return []
    if sec_id == 34:
        if not isinstance(data, dict) or "derived_positions" not in data:
            return ["blind_core_trial: missing derived position metrics"]
        return []
    if sec_id == 35:
        if not isinstance(data, dict) or "best_validated_proxy" not in data:
            return ["validated_pool_proxy: missing best proxy metrics"]
        return []
    if sec_id == 36:
        if not isinstance(data, dict) or "locked_contract" not in data or "blind_contract" not in data:
            return ["blind_contract_operating_point: missing contract comparison data"]
        return []
    if sec_id == 37:
        if not isinstance(data, dict) or "header_success_rate" not in data or "full_payload_success_rate" not in data:
            return ["blind_header_body: missing success-rate metrics"]
        return []
    if sec_id == 38:
        if not isinstance(data, dict) or "perfect_readout_ratio" not in data:
            return ["blind_header_stability: missing per-position stability metrics"]
        return []
    if sec_id == 39:
        if not isinstance(data, dict) or "rows" not in data:
            return ["blind_header_redundancy: missing redundancy rows"]
        return []
    if sec_id == 40:
        if not isinstance(data, dict) or "rows" not in data:
            return ["blind_body_redundancy: missing body redundancy rows"]
        return []
    if sec_id == 41:
        if not isinstance(data, dict) or "rows" not in data:
            return ["blind_payload_coding: missing payload coding rows"]
        return []
    if sec_id == 42:
        if not isinstance(data, dict) or "rows" not in data:
            return ["blind_partial_payload_contract: missing partial-payload rows"]
        return []
    if sec_id == 43:
        if not isinstance(data, dict) or "rows" not in data:
            return ["blind_real_proof_header_diagnostic: missing header rows"]
        return []
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


def _default_timeout_for_section(sec_id: int) -> int:
    if sec_id == 1:
        return 1200
    if sec_id == 2:
        return 600
    if sec_id == 3:
        return 600
    if sec_id == 4:
        return 300
    if sec_id == 6:
        return 600
    if sec_id in {31, 32}:
        return 300
    return DEFAULT_TIMEOUT


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
        spec = ARTIFACT_SPEC.get(sec_id, {"charts": [f"sec{sec_id}_*.png"], "data": [f"sec{sec_id}_*.json"]})
        charts = []
        for pattern in spec["charts"]:
            charts.extend(list(RESULTS_DIR.glob(pattern)))
        data = []
        for pattern in spec["data"]:
            data.extend(list(RESULTS_DIR.glob(pattern)))
        charts = sorted({p.resolve() for p in charts})
        data = sorted({p.resolve() for p in data})

        valid = len(charts) >= len(spec["charts"]) and len(data) >= len(spec["data"])

        schema_errors: list[str] = []
        if data and sec_id in {1, 2, 3}:
            schema_errors = _schema_errors_for_section(sec_id, Path(data[0]))

        validation[sec_id] = {
            "charts": len(charts),
            "data": len(data),
            "valid": valid,
            "schema_valid": len(schema_errors) == 0,
            "schema_errors": schema_errors,
            "tier": SECTION_CLASS.get(sec_id, "paper_grade"),
            "artifact_spec": spec,
        }
    
    return validation


def print_summary(results: dict, validation: dict) -> None:
    """Print a formatted summary table."""
    print("\n" + "=" * 70)
    print("  BENCHMARK SUMMARY")
    print("=" * 70)
    print(f"  {'Section':<30} {'Status':<10} {'Time':<10} {'Charts':<8} {'Data':<8} {'Schema':<8} {'Tier':<12}")
    print("  " + "-" * 92)
    
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
        tier_str = v.get("tier", "paper_grade")
        
        print(f"  {sec_name:<30} {status:<10} {time_str:<10} {charts_str:<8} {data_str:<8} {schema_str:<8} {tier_str:<12}")

        if not v.get("schema_valid", True):
            for msg in v.get("schema_errors", [])[:2]:
                print(f"    -> {msg}")
        
        if r["success"]:
            success_count += 1
        total_time += r["time"]
    
    print("  " + "-" * 92)
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
    parser.add_argument("--paper-grade", action="store_true",
                        help="Run the default paper-grade benchmark subset")
    parser.add_argument("--diagnostic-grade", action="store_true",
                        help="Run the default diagnostic benchmark subset")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"Timeout per section in seconds (default: {DEFAULT_TIMEOUT})")
    args = parser.parse_args()

    if args.paper_grade and args.diagnostic_grade:
        sections_to_run = PAPER_GRADE_DEFAULT + DIAGNOSTIC_DEFAULT
    elif args.paper_grade:
        sections_to_run = PAPER_GRADE_DEFAULT
    elif args.diagnostic_grade:
        sections_to_run = DIAGNOSTIC_DEFAULT
    else:
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
    if args.timeout == DEFAULT_TIMEOUT:
        print("  Timeout: section-specific defaults")
    else:
        print(f"  Timeout: {args.timeout}s per section")
    print()
    
    results = {}
    t_start = time.perf_counter()
    
    for sec_id in sections_to_run:
        if sec_id not in SECTIONS:
            print(f"  [warn] Unknown section {sec_id}, skipping")
            continue
        
        timeout = args.timeout if args.timeout != DEFAULT_TIMEOUT else _default_timeout_for_section(sec_id)
        result = run_section_safe(sec_id, args.force, timeout, args.fast)
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
    
    # Exit code: 0 if all passed and paper-grade validation is clean, 1 otherwise
    failed = [s for s, r in results.items() if not r["success"]]
    invalid = [
        s for s, v in validation.items()
        if s in results
        if v.get("tier") == "paper_grade" and (not v.get("valid", False) or not v.get("schema_valid", True))
    ]
    if failed or invalid:
        print(f"\n  [warn] Failed sections: {failed}")
        if invalid:
            print(f"  [warn] Invalid paper-grade artifacts: {invalid}")
        sys.exit(1)
    else:
        print("\n  All sections completed successfully.\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
