"""
run_all.py — Master benchmark runner
======================================
Runs all 6 benchmark sections in order and prints a summary table.

Usage:
    cd VideoLevel/
    python benchmark/run_all.py           # Run all (cache-first)
    python benchmark/run_all.py --force   # Re-run everything from scratch
    python benchmark/run_all.py --sections 1 3 5   # Run specific sections

Output: benchmark/results/*.png + benchmark/results/*.json
"""

import argparse
import sys
import time
import concurrent.futures
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Per-section timeout in seconds (30 min default; sec2 is the heaviest)
SECTION_TIMEOUT = 1800

# -------------------------------------------------------------------------
# Section registry
# -------------------------------------------------------------------------
SECTIONS = {
    1: ("§1 Quality vs Original",          "benchmark.sec1_quality"),
    2: ("§2 Capacity & PSNR vs Rate",       "benchmark.sec2_capacity"),
    3: ("§3 Method Comparison",             "benchmark.sec3_methods"),
    4: ("§4 Steganalysis Resistance",       "benchmark.sec4_security"),
    5: ("§5 ZKP System Comparison",         "benchmark.sec5_zkp"),
    6: ("§6 Pipeline Performance",          "benchmark.sec6_performance"),
}


def _run_section_inner(module_path: str, force: bool) -> None:
    """Inner runner executed in a thread (so timeout can interrupt it)."""
    import importlib
    mod = importlib.import_module(module_path)
    mod.run(force=force)


def _run_section(sec_id: int, force: bool,
                 timeout: int = SECTION_TIMEOUT) -> tuple[bool, float]:
    title, module_path = SECTIONS[sec_id]
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    t0 = time.perf_counter()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_run_section_inner, module_path, force)
            fut.result(timeout=timeout)
        elapsed = time.perf_counter() - t0
        print(f"  [OK] Completed in {elapsed:.1f} s")
        return True, elapsed
    except concurrent.futures.TimeoutError:
        elapsed = time.perf_counter() - t0
        print(f"  [TIMEOUT] after {elapsed:.1f} s (limit={timeout} s)")
        return False, elapsed
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(f"  [FAIL] after {elapsed:.1f} s: {e}")
        import traceback; traceback.print_exc()
        return False, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Run benchmark suite")
    parser.add_argument("--force",    action="store_true",
                        help="Re-run all experiments (ignore cache)")
    parser.add_argument("--sections", type=int, nargs="+",
                        help="Run only these sections (e.g. --sections 1 3 5)")
    args = parser.parse_args()

    sections_to_run = sorted(args.sections) if args.sections else list(SECTIONS.keys())
    results: dict[int, tuple[bool, float]] = {}

    t_start = time.perf_counter()

    for sec_id in sections_to_run:
        if sec_id not in SECTIONS:
            print(f"  [warn] Unknown section {sec_id}, skipping")
            continue
        ok, elapsed = _run_section(sec_id, force=args.force)
        results[sec_id] = (ok, elapsed)

    total_elapsed = time.perf_counter() - t_start

    # -------------------------------------------------------------------------
    # Summary table
    # -------------------------------------------------------------------------
    print(f"\n{'='*60}")
    print("  BENCHMARK SUMMARY")
    print(f"{'='*60}")
    print(f"  {'Section':<40} {'Status':>8}  {'Time':>8}")
    print(f"  {'-'*40}  {'-'*8}  {'-'*8}")
    for sec_id, (ok, elapsed) in sorted(results.items()):
        title = SECTIONS[sec_id][0]
        status = "[OK]  " if ok else "[FAIL]"
        print(f"  {title:<40} {status:>8}  {elapsed:>6.1f} s")
    print(f"  {'-'*40}  {'-'*8}  {'-'*8}")
    print(f"  {'Total':40} {'':>8}  {total_elapsed:>6.1f} s")

    from benchmark._common import RESULTS_DIR
    print(f"\n  Output: {RESULTS_DIR}")
    print(f"  Files:  {len(list(RESULTS_DIR.glob('*.png')))} charts, "
          f"{len(list(RESULTS_DIR.glob('*.json')))} data files")

    failed = [s for s, (ok, _) in results.items() if not ok]
    if failed:
        print(f"\n  [warn] Failed sections: {failed}")
        sys.exit(1)
    else:
        print("\n  All sections completed successfully.\n")


if __name__ == "__main__":
    main()
