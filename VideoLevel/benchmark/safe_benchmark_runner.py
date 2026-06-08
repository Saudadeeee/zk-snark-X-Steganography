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
import os
import platform
import shutil
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
    44: "trust_architecture_diagnostic",
}

DEFAULT_TIMEOUT = 180  # 3 minutes per section
FAST_CAPABLE_SECTIONS = {1, 2, 3, 4, 6, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44}
PAPER_GRADE_DEFAULT = [1, 2, 3, 4, 5, 6]
DIAGNOSTIC_DEFAULT = [31, 32, 44]
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
    44: "diagnostic_grade",
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
    44: {
        "charts": [],
        "data": ["trust_architecture_diagnostic.json"],
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
        "verify_valid",
        "verify_message_match",
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
            continue
        if payload.get("payload_target_met") is not True:
            errors.append(f"sec1:{seq} payload_target_met must be true")
        if payload.get("verify_valid") is not True or payload.get("verify_message_match") is not True:
            errors.append(f"sec1:{seq} must have verified proof/message match")
    return errors


def _validate_sec2_schema(data: dict) -> list[str]:
    errors: list[str] = []
    required = {
        "raw_safe_bits",
        "patchable_usable_bits",
        "zk_blob_bits",
        "fractions_pct",
        "bits_at_fraction",
        "psnr_at_fraction",
    }
    if not data:
        return ["sec2: empty JSON object; regenerate after verified SEC1 sidecars exist"]
    for seq, payload in data.items():
        if not isinstance(payload, dict):
            errors.append(f"sec2:{seq} must be object")
            continue
        missing = sorted(required - set(payload.keys()))
        if missing:
            errors.append(f"sec2:{seq} missing keys: {', '.join(missing)}")
            continue
        if "validated_pool_bits" not in payload and "validated_bits" not in payload:
            errors.append(f"sec2:{seq} missing keys: validated_pool_bits (or legacy validated_bits)")
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


def _validate_sec4_schema(data: dict) -> list[str]:
    required = {
        "rates",
        "capacity",
        "op_rate_pct",
        "op_bits",
        "op_chi_p",
        "op_spa",
        "op_rs",
    }
    missing = sorted(required - set(data.keys()))
    return [f"sec4 missing keys: {', '.join(missing)}"] if missing else []


def _validate_sec5_schema(data: dict) -> list[str]:
    errors: list[str] = []
    groth16 = data.get("Groth16 BN128\n(This Work)")
    if not isinstance(groth16, dict):
        return ["sec5: missing Groth16 BN128\\n(This Work) row"]
    required = {"proof_size_bytes", "prove_time_ms", "verify_time_ms", "trusted_setup", "simulated"}
    missing = sorted(required - set(groth16.keys()))
    if missing:
        errors.append(f"sec5: Groth16 row missing keys: {', '.join(missing)}")
    return errors


def _validate_sec6_schema(data: dict) -> list[str]:
    errors: list[str] = []
    if not data:
        return ["sec6: empty JSON object"]
    for seq, payload in data.items():
        if not isinstance(payload, dict):
            errors.append(f"sec6:{seq} must be object")
            continue
        required = {"timings", "total_s", "capacity_bits", "bits_embedded", "blob_size", "zk_valid"}
        missing = sorted(required - set(payload.keys()))
        if missing:
            errors.append(f"sec6:{seq} missing keys: {', '.join(missing)}")
            continue
        timings = payload.get("timings")
        if not isinstance(timings, dict) or not timings:
            errors.append(f"sec6:{seq} missing timing breakdown")
        if payload.get("zk_valid") is not True:
            errors.append(f"sec6:{seq} zk_valid must be true for paper-grade performance evidence")
    return errors


def _validate_trust_architecture_schema(data: dict) -> list[str]:
    required = {
        "tier",
        "provenance",
        "c2pa_bridge",
        "fingerprint_registry",
        "watermark_receipt",
        "attestation",
        "zkml_interface",
        "circuits",
    }
    missing = sorted(required - set(data.keys()))
    if missing:
        return [f"trust_architecture missing keys: {', '.join(missing)}"]
    errors: list[str] = []
    if data.get("tier") != "diagnostic_grade":
        errors.append("trust_architecture tier must be diagnostic_grade")
    if data["provenance"].get("valid") is not True:
        errors.append("trust_architecture provenance root must verify")
    if data["provenance"].get("tamper_detected") is not True:
        errors.append("trust_architecture provenance tamper test must pass")
    c2pa = data["c2pa_bridge"]
    if c2pa.get("payload_bytes") != 32:
        errors.append("trust_architecture C2PA payload must be 32 bytes")
    if c2pa.get("manifest_fields", {}).get("roundtrip_valid") is not True:
        errors.append("trust_architecture C2PA manifest provenance fields must roundtrip")
    if c2pa.get("embedded_payload_valid") is not True:
        errors.append("trust_architecture C2PA embedded payload must verify")
    if c2pa.get("embedded_payload_tamper_detected") is not True:
        errors.append("trust_architecture C2PA payload tamper test must pass")
    if c2pa.get("manifest_tamper_detected") is not True:
        errors.append("trust_architecture C2PA manifest tamper test must pass")
    if data["fingerprint_registry"].get("matched") is not True:
        errors.append("trust_architecture fingerprint registry must match")
    video_fp = data["fingerprint_registry"].get("video_fingerprint", {})
    if not isinstance(video_fp, dict) or not video_fp.get("fingerprint_hex"):
        errors.append("trust_architecture video fingerprint policy must produce a fingerprint")
    threshold_rows = data["fingerprint_registry"].get("threshold_behavior", {}).get("synthetic_rows", [])
    if not isinstance(threshold_rows, list) or not threshold_rows:
        errors.append("trust_architecture fingerprint threshold behavior must be measured")
    committed_fp = data["fingerprint_registry"].get("committed_synthetic_benchmark", {})
    if committed_fp.get("available") is not True:
        errors.append("trust_architecture committed synthetic fingerprint benchmark must be available")
    if not isinstance(committed_fp.get("rows"), list) or not committed_fp.get("rows"):
        errors.append("trust_architecture committed synthetic fingerprint benchmark must report rows")
    if not committed_fp.get("positive_distances") or not committed_fp.get("negative_distances"):
        errors.append("trust_architecture committed synthetic fingerprint benchmark must report distances")
    real_clip = data["fingerprint_registry"].get("real_clip_benchmark", {})
    if real_clip.get("available") is not True:
        errors.append("trust_architecture real-clip fingerprint benchmark must be available")
    if not isinstance(real_clip.get("rows"), list) or not real_clip.get("rows"):
        errors.append("trust_architecture real-clip fingerprint benchmark must report rows")
    if data["watermark_receipt"].get("receipt", {}).get("valid") is not True:
        errors.append("trust_architecture watermark receipt must be valid")
    transform_rows = data["watermark_receipt"].get("transform_benchmark", {}).get("rows", [])
    if not isinstance(transform_rows, list) or not transform_rows:
        errors.append("trust_architecture detector transform benchmark must report rows")
    transform_summary = data["watermark_receipt"].get("transform_benchmark", {}).get("summary", {})
    if not isinstance(transform_summary, dict) or transform_summary.get("positive_count", 0) <= 0:
        errors.append("trust_architecture detector transform benchmark must report positive controls")
    if not isinstance(transform_summary, dict) or transform_summary.get("negative_count", 0) <= 0:
        errors.append("trust_architecture detector transform benchmark must report negative controls")
    if data["attestation"].get("signature_valid") is not True:
        errors.append("trust_architecture attestation signature must verify")
    if data["attestation"].get("sidecar_roundtrip_valid") is not True:
        errors.append("trust_architecture attestation sidecar must roundtrip")
    if data["zkml_interface"].get("interface_valid") is not True:
        errors.append("trust_architecture ZKML interface must validate")
    circuits = data.get("circuits", {})
    for circuit_name in ("fingerprint_verify", "detector_receipt"):
        circuit = circuits.get(circuit_name)
        if not isinstance(circuit, dict):
            errors.append(f"trust_architecture missing circuit diagnostic for {circuit_name}")
            continue
        if circuit.get("compile_ok") is not True:
            errors.append(f"trust_architecture circuit {circuit_name} must compile")
        stats = circuit.get("stats", {})
        if not isinstance(stats, dict) or int(stats.get("non_linear_constraints", 0)) <= 0:
            errors.append(f"trust_architecture circuit {circuit_name} must report constraints")
        groth16 = circuit.get("groth16_measurement", {})
        if not isinstance(groth16, dict) or groth16.get("verified") is not True:
            errors.append(f"trust_architecture circuit {circuit_name} Groth16 proof must verify")
        if int(float(groth16.get("prove_time_ms", 0))) <= 0:
            errors.append(f"trust_architecture circuit {circuit_name} must report prove time")
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
    if sec_id == 4:
        return _validate_sec4_schema(data or {})
    if sec_id == 5:
        return _validate_sec5_schema(data or {})
    if sec_id == 6:
        return _validate_sec6_schema(data or {})
    if sec_id == 44:
        return _validate_trust_architecture_schema(data or {})
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
    if SECTION_CLASS.get(sec_id) == "paper_grade" and sec_id in {1, 2, 6}:
        cmd.extend(["--sequences", "akiyo_q22_g1"])
    env = os.environ.copy()
    if SECTION_CLASS.get(sec_id) == "paper_grade" and sec_id == 1:
        env["SEC1_USE_REAL_PROOF_PIPELINE"] = "1"
    
    print(f"  [§{sec_id}] Running {SECTIONS[sec_id]} (timeout={timeout}s) ...")
    
    t0 = time.perf_counter()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=BENCHMARK_DIR.parent,
            env=env,
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
        if data and sec_id in {1, 2, 3, 4, 5, 6, 44}:
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


def _cmd_output(cmd: list[str], *, cwd: Path | None = None, timeout: int = 10) -> str | None:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return None
    text = (result.stdout or result.stderr or "").strip()
    return text.splitlines()[0].strip() if text else None


def collect_environment_metadata() -> dict[str, object]:
    root = BENCHMARK_DIR.parent
    git_commit = _cmd_output(["git", "rev-parse", "HEAD"], cwd=root)
    git_status = _cmd_output(["git", "status", "--short"], cwd=root)
    snarkjs_version = _cmd_output(["cmd", "/c", "cd circuits && npx snarkjs --version"], cwd=root)
    return {
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "git_commit": git_commit,
        "git_dirty": bool(git_status),
        "node": _cmd_output(["node", "--version"]),
        "circom": _cmd_output(["circom", "--version"]),
        "snarkjs": snarkjs_version,
        "ffmpeg": _cmd_output(["ffmpeg", "-version"]),
        "cwd": str(root),
        "path_has_ffmpeg": shutil.which("ffmpeg") is not None,
        "env": {
            "SEC1_USE_REAL_PROOF_PIPELINE": os.environ.get("SEC1_USE_REAL_PROOF_PIPELINE"),
            "SEC1_FAST_MODE": os.environ.get("SEC1_FAST_MODE"),
            "SEC2_FAST_MODE": os.environ.get("SEC2_FAST_MODE"),
        },
    }


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
        "environment": collect_environment_metadata(),
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
