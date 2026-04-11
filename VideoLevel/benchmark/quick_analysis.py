"""
quick_analysis.py — Quick analysis of cached benchmark results
==============================================================
Reads cached JSON files and performs theory validation without re-running benchmarks.

Usage:
    python quick_analysis.py
"""

import json
import sys
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"

THEORY = {
    "sec1_quality_data": {
        "name": "§1 Quality vs Original",
        "expected": {
            "avg_psnr_min": 35.0,  # dB
            "avg_psnr_max": 50.0,
            "avg_ssim_min": 0.95,
            "avg_ssim_max": 1.00,
        }
    },
    "sec2_capacity_data": {
        "name": "§2 Capacity & PSNR vs Rate",
        "expected": {
            "capacity_bits_min": 2000,  # sufficient for ZK blob
            "capacity_bits_max": 20000,
        }
    },
    "sec4_security_data": {
        "name": "§4 Steganalysis Resistance",
        "expected": {
            "chi_p_at_0_pct_min": 0.5,  # p > 0.05 at low rates
            "chi_p_at_50_pct_min": 0.01,
        }
    },
    "sec5_zkp_data": {
        "name": "§5 ZKP System Comparison",
        "expected": {
            "groth16_proof_size": 274,  # bytes
            "groth16_prove_time_max": 120000,  # ms (2 min)
            "groth16_verify_time_max": 50,  # ms
        }
    },
    "sec6_performance_data": {
        "name": "§6 Pipeline Performance",
        "expected": {
            "total_time_max": 300,  # seconds (5 min)
        }
    }
}


def load_cache(name: str):
    """Load cached JSON data."""
    path = RESULTS_DIR / f"{name}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def validate_sec1(data: dict) -> dict:
    """Validate Section 1: Quality metrics."""
    if not data:
        return {"valid": False, "reason": "No cached data"}
    
    issues = []
    stats = {}
    
    for seq_name, seq_data in data.items():
        avg_psnr = seq_data.get("avg_psnr", 0)
        avg_ssim = seq_data.get("avg_ssim", 0)
        
        stats[seq_name] = {"psnr": avg_psnr, "ssim": avg_ssim}
        
        if avg_psnr < THEORY["sec1_quality_data"]["expected"]["avg_psnr_min"]:
            issues.append(f"{seq_name}: PSNR {avg_psnr:.1f} < 35 dB (poor quality)")
        
        if avg_ssim < THEORY["sec1_quality_data"]["expected"]["avg_ssim_min"]:
            issues.append(f"{seq_name}: SSIM {avg_ssim:.3f} < 0.95 (poor quality)")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "stats": stats,
    }


def validate_sec2(data: dict) -> dict:
    """Validate Section 2: Capacity."""
    if not data:
        return {"valid": False, "reason": "No cached data"}
    
    issues = []
    stats = {}
    
    for seq_name, seq_data in data.items():
        capacity_bits = seq_data.get("capacity_bits", 0)
        stats[seq_name] = {"capacity_bits": capacity_bits}
        
        if capacity_bits < THEORY["sec2_capacity_data"]["expected"]["capacity_bits_min"]:
            issues.append(f"{seq_name}: capacity {capacity_bits} < 2000 bits (insufficient)")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "stats": stats,
    }


def validate_sec4(data: dict) -> dict:
    """Validate Section 4: Steganalysis."""
    if not data:
        return {"valid": False, "reason": "No cached data"}
    
    issues = []
    
    chi_p_this_work = data.get("chi_p_this_work", [])
    rates = data.get("rates", [])
    
    stats = {"chi_p_by_rate": {}}
    for r, p in zip(rates, chi_p_this_work):
        stats["chi_p_by_rate"][f"{r}%"] = round(p, 4)
    
    # Check p-value at 0% (cover) and 50% rate
    if len(chi_p_this_work) > 0:
        p_at_0 = chi_p_this_work[0]  # rate=0%
        if p_at_0 < 0.5:
            issues.append(f"Chi-square p={p_at_0:.3f} at 0% rate (should be ~1.0 for cover)")
    
    if len(rates) >= 5:  # assuming 50% is around index 4-5
        idx_50 = rates.index(50) if 50 in rates else -1
        if idx_50 >= 0:
            p_at_50 = chi_p_this_work[idx_50]
            if p_at_50 < 0.01:
                issues.append(f"Chi-square p={p_at_50:.3f} at 50% rate (easily detectable)")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "stats": stats,
    }


def validate_sec5(data: dict) -> dict:
    """Validate Section 5: ZKP comparison."""
    if not data:
        return {"valid": False, "reason": "No cached data"}
    
    issues = []
    stats = {}
    
    groth16_key = "Groth16 BN128\n(This Work)"
    if groth16_key in data:
        g = data[groth16_key]
        stats["groth16"] = {
            "proof_size": g.get("proof_size_bytes"),
            "prove_time_ms": g.get("prove_time_ms"),
            "verify_time_ms": g.get("verify_time_ms"),
        }
        
        if g.get("prove_time_ms", 0) > THEORY["sec5_zkp_data"]["expected"]["groth16_prove_time_max"]:
            issues.append(f"Groth16 prove time {g['prove_time_ms']:.0f} ms > 120s (too slow)")
        
        if g.get("verify_time_ms", 0) > THEORY["sec5_zkp_data"]["expected"]["groth16_verify_time_max"]:
            issues.append(f"Groth16 verify time {g['verify_time_ms']:.1f} ms > 50ms (too slow)")
    else:
        issues.append("Groth16 data not found")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "stats": stats,
    }


def validate_sec6(data: dict) -> dict:
    """Validate Section 6: Performance."""
    if not data:
        return {"valid": False, "reason": "No cached data"}
    
    issues = []
    stats = {}
    
    for seq_name, seq_data in data.items():
        total_s = seq_data.get("total_s", 0)
        stats[seq_name] = {"total_s": total_s}
        
        if total_s > THEORY["sec6_performance_data"]["expected"]["total_time_max"]:
            issues.append(f"{seq_name}: total time {total_s:.0f}s > 5 min (too slow)")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "stats": stats,
    }


def main():
    print("=" * 70)
    print("  Quick Analysis of Cached Benchmark Results")
    print("=" * 70)
    print()
    
    all_valid = True
    summary = {}
    
    validators = {
        "sec1_quality_data": validate_sec1,
        "sec2_capacity_data": validate_sec2,
        "sec4_security_data": validate_sec4,
        "sec5_zkp_data": validate_sec5,
        "sec6_performance_data": validate_sec6,
    }
    
    for cache_name, validator in validators.items():
        theory_info = THEORY.get(cache_name, {})
        section_name = theory_info.get("name", cache_name)
        
        print(f"  {section_name}")
        print("  " + "-" * 68)
        
        data = load_cache(cache_name)
        
        if data is None:
            print(f"  [SKIP] No cached data found")
            print()
            continue
        
        result = validator(data)
        
        if result["valid"]:
            print(f"  [OK] Validation passed")
            if "stats" in result:
                print(f"  Stats: {json.dumps(result['stats'], indent=4)}")
        else:
            print(f"  [FAIL] Validation failed")
            if "issues" in result:
                for issue in result["issues"]:
                    print(f"    - {issue}")
            if "reason" in result:
                print(f"    Reason: {result['reason']}")
            all_valid = False
        
        summary[section_name] = result
        print()
    
    # Overall summary
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for r in summary.values() if r.get("valid", False))
    total = len(summary)
    
    print(f"  Validated: {passed}/{total} sections")
    
    if all_valid:
        print("  [OK] All cached results match theoretical expectations")
        print()
        print("  → System is ready for paper submission")
    else:
        print("  [WARN] Some results deviate from theory")
        print()
        print("  → Re-run benchmark with: python safe_benchmark_runner.py --force")
    
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
