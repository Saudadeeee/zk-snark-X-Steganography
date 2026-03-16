"""
Benchmark Master Runner
========================
Runs all benchmark sections in the recommended order:

  §1  Quality     — PSNR, SSIM, histogram, LSB planes
  §2  Steganalysis— RS, chi-square, SPA
  §3  Baseline    — PSNR vs payload, RS vs payload (line charts)
  §4  ZK          — constraint pie, correctness, timing, scheme comparison
  §5  Performance — timing breakdown, memory, file size
  §6  SysCompare  — ECDSA benchmark, stego-only vs ZK, radar chart
  §7  Security    — key sensitivity, two-key separation

Usage:
    cd ImageLevel

    # Run all (non-ZK sections only — no circuit needed):
    python Benchmark/run_all.py

    # Include ZK benchmarks (requires compiled circuit):
    python Benchmark/run_all.py --with-zk

    # Run a single section:
    python Benchmark/run_all.py --section quality
    python Benchmark/run_all.py --section steganalysis
    python Benchmark/run_all.py --section baseline
    python Benchmark/run_all.py --section zk          # needs --with-zk
    python Benchmark/run_all.py --section performance
    python Benchmark/run_all.py --section syscompare
    python Benchmark/run_all.py --section security

Prerequisites:
    pip install numpy Pillow matplotlib scipy scikit-image pydicom cryptography
    npm install           (in ImageLevel/)
    # For ZK: python Benchmark/ZK/setup_circuit.py
    # Data: add .dcm files to examples/dicom/
"""

import sys
import time
import traceback
import argparse
from pathlib import Path

BENCH_DIR   = Path(__file__).resolve().parent
PROJECT_DIR = BENCH_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(BENCH_DIR))


def _section(name: str, fn, skip: bool = False) -> bool:
    if skip:
        print(f"\n[SKIP] {name}")
        return True
    print(f"\n{'='*60}")
    print(f"  SECTION: {name}")
    print(f"{'='*60}")
    t0 = time.perf_counter()
    try:
        fn()
        elapsed = time.perf_counter() - t0
        print(f"\n  [OK]  {name} done in {elapsed:.1f}s")
        return True
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(f"\n  [FAIL]  {name} FAILED in {elapsed:.1f}s: {e}")
        traceback.print_exc()
        return False


def run(with_zk: bool = False, section: str = "all") -> None:
    results = {}
    t_start = time.perf_counter()

    # ── §1 Quality ────────────────────────────────────────────────────────────
    if section in ("all", "quality"):
        from Quality.quality_metrics   import run as q_run
        from Quality.histogram_overlay import run as h_run
        from Quality.lsb_planes        import run as l_run
        results["quality_metrics"]   = _section("§1.1 Quality Metrics",   q_run)
        results["histogram_overlay"] = _section("§1.2 Histogram Overlay", h_run)
        results["lsb_planes"]        = _section("§1.3 LSB Bit Planes",    l_run)

    # ── §2 Steganalysis ───────────────────────────────────────────────────────
    if section in ("all", "steganalysis"):
        from Steganalysis.rs_analysis  import run as rs_run
        from Steganalysis.chi_square   import run as chi_run
        from Steganalysis.spa_analysis import run as spa_run
        results["rs_analysis"]  = _section("§2.1 RS Analysis",    rs_run)
        results["chi_square"]   = _section("§2.2 Chi-Square",     chi_run)
        results["spa_analysis"] = _section("§2.3 SPA Analysis",   spa_run)

    # ── §3 Baseline ───────────────────────────────────────────────────────────
    if section in ("all", "baseline"):
        from Baseline.psnr_vs_payload import run as psnr_run
        from Baseline.rs_vs_payload   import run as rs_pay_run
        results["psnr_vs_payload"] = _section("§3 PSNR vs Payload", psnr_run)
        results["rs_vs_payload"]   = _section("§3 RS vs Payload",   rs_pay_run)

    # ── §4 ZK ─────────────────────────────────────────────────────────────────
    if section in ("all", "zk"):
        from ZK.constraint_pie        import run as pie_run
        from ZK.zkp_scheme_comparison import run as zkp_run
        results["constraint_pie"]     = _section("§4.3 Constraint Pie",      pie_run)
        results["zkp_comparison"]     = _section("§4.5 ZKP Scheme Comparison", zkp_run)

        if with_zk:
            from ZK.correctness_tests import run as corr_run
            from ZK.zk_timing         import run as zkt_run
            results["correctness"]     = _section("§4.1 Correctness Tests", corr_run)
            results["zk_timing"]       = _section("§4 ZK Timing",           zkt_run)
        else:
            print("\n[INFO] §4 ZK timing/correctness skipped — run with --with-zk")
            print("       (requires compiled circuit: python Benchmark/ZK/setup_circuit.py)")

    # ── §5 Performance ────────────────────────────────────────────────────────
    if section in ("all", "performance"):
        from Performance.timing_breakdown  import run as perf_run
        from Performance.memory_profile    import run as mem_run
        from Performance.file_size_overhead import run as fs_run
        results["timing_breakdown"] = _section("§5.1 Timing Breakdown", perf_run)
        results["memory_profile"]   = _section("§5.2 Memory Profile",   mem_run)
        results["file_size"]        = _section("§5.4 File Size",        fs_run)

    # ── §6 System Comparison ──────────────────────────────────────────────────
    if section in ("all", "syscompare"):
        from SystemComparison.ecdsa_benchmark    import run as ecdsa_run
        from SystemComparison.stego_only_vs_zk   import run as stv_run
        from SystemComparison.capability_radar   import run as radar_run
        results["ecdsa"]    = _section("§6 ECDSA Benchmark",       ecdsa_run)
        results["stego_vs_zk"] = _section("§6.3 Stego-Only vs ZK", stv_run)
        results["radar"]    = _section("§6 Capability Radar",      radar_run)

    # ── §7 Security ───────────────────────────────────────────────────────────
    if section in ("all", "security"):
        from Security.key_sensitivity    import run as ks_run
        from Security.two_key_separation import run as tks_run
        results["key_sensitivity"]   = _section("§7.1 Key Sensitivity",   ks_run)
        results["two_key_separation"] = _section("§7.3 Two-Key Separation", tks_run)

    # ── Summary ───────────────────────────────────────────────────────────────
    total_time = time.perf_counter() - t_start
    n_ok   = sum(1 for v in results.values() if v is True)
    n_fail = sum(1 for v in results.values() if v is False)

    print(f"\n{'='*60}")
    print(f"  BENCHMARK SUMMARY  ({total_time:.1f}s total)")
    print(f"  Passed: {n_ok}    Failed: {n_fail}    Total: {len(results)}")
    print(f"{'='*60}")
    for name, ok in results.items():
        mark = "[OK]" if ok else "[FAIL]"
        print(f"  {mark}  {name}")

    print(f"\nResults saved in: {BENCH_DIR}/*/results/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run all benchmarks")
    parser.add_argument("--with-zk", action="store_true",
                        help="Also run ZK live-timing (requires compiled circuit)")
    parser.add_argument("--section", default="all",
                        choices=["all", "quality", "steganalysis", "baseline",
                                 "zk", "performance", "syscompare", "security"],
                        help="Run only one section")
    args = parser.parse_args()
    run(with_zk=args.with_zk, section=args.section)
