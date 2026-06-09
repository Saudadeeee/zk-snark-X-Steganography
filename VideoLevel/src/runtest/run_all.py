"""
run_all.py - Run all phase tests in order and print a summary table.

Usage:
    python src/runtest/run_all.py

Exit code: 0 if all phases pass, 1 if any phase fails, 2 if any phase is incomplete.
"""

import io
import os
import re
import subprocess
import sys
import argparse

# -- Locate project root and test files --------------------------------- #

ROOT     = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
RUNTEST  = os.path.join(ROOT, 'src', 'runtest')

PHASES = [
    ("Phase 1", "ZK Proof",           "test_phase1_zk_proof.py"),
    ("Phase 2", "H264 Parser",         "test_phase2_h264_parser.py"),
    ("Phase 3", "Safety + Embed",      "test_phase3_safety_embed.py"),
    ("Phase 4", "Reconstruct",         "test_phase4_reconstruct.py"),
    ("Phase 5", "Extract + Verify",    "test_phase5_extract_verify.py"),
    ("Phase 6", "Near-blind + Manifest", "test_phase6_near_blind_manifest.py"),
    ("Phase 7", "Regression Cases", "test_phase7_regression_cases.py"),
]

SEP  = '-' * 58
SEP2 = '=' * 58


def _count_results(output: str):
    """Count PASS/FAIL/SKIP lines in captured stdout."""
    passed = len(re.findall(r'\[PASS\]', output))
    failed = len(re.findall(r'\[FAIL\]', output))
    skipped = len(re.findall(r'\[SKIP\]', output))
    return passed, failed, skipped


def run_phase(label: str, description: str, filename: str):
    """Run one test file as a subprocess. Returns (passed, failed, skipped, exit_code)."""
    filepath = os.path.join(RUNTEST, filename)
    result   = subprocess.run(
        [sys.executable, filepath],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    stdout = result.stdout
    stderr = result.stderr

    # Print the test output indented
    for line in stdout.splitlines():
        print(f"  {line}")
    if result.returncode != 0 and stderr.strip():
        # Only print stderr if the phase actually failed
        for line in stderr.splitlines()[:10]:   # cap to avoid log spam
            print(f"  [STDERR] {line}")

    passed, failed, skipped = _count_results(stdout)
    return passed, failed, skipped, result.returncode


def _status_from_exit_code(code: int) -> str:
    if code == 0:
        return 'OK'
    if code == 2:
        return 'INCOMPLETE'
    return 'FAIL'


# -- Main --------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(description="Run full or quick phase test suite")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run only the fast correctness phases (1-3), skip long reconstruction and verify phases",
    )
    args = parser.parse_args()

    # Force UTF-8 output on Windows (sys.stdout may be TextIOWrapper with cp1252)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    elif hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print()
    print(SEP2)
    print("  ZK-SNARK Video Steganography - Full Test Suite")
    print(SEP2)

    selected_phases = PHASES[:3] if args.quick else PHASES
    summary = []
    for label, desc, filename in selected_phases:
        print(f"\n>>> Running {label} - {desc}")
        print(SEP)
        passed, failed, skipped, code = run_phase(label, desc, filename)
        print(SEP)
        total_run = passed + failed + skipped
        status    = _status_from_exit_code(code)
        summary.append((label, desc, passed, failed, skipped, status))
        print(
            f"  {label} result: {passed}/{total_run} passed, "
            f"{failed} failed, {skipped} skipped  [{status}]"
        )

    # Final summary table
    print()
    print(SEP2)
    print("  SUMMARY")
    print(SEP2)
    all_pass  = True
    any_incomplete = False
    total_p = total_f = total_s = 0
    for label, desc, p, f, s, status in summary:
        marker = '+' if status == 'OK' else ('!' if status == 'INCOMPLETE' else 'X')
        col    = f"{p}/{p+f+s} passed"
        if s:
            col += f", {s} skipped"
        if f:
            col += f", {f} failed"
        print(f"  [{marker}] {label:8s}  {desc:22s}  {col}")
        total_p += p; total_f += f; total_s += s
        if status == 'INCOMPLETE':
            any_incomplete = True
        elif status != 'OK':
            all_pass = False

    print(SEP)
    print(f"  TOTAL: {total_p}/{total_p+total_f} passed"
          + (f", {total_s} skipped" if total_s else ""))
    print()

    if all_pass and not any_incomplete:
        if args.quick:
            print("  [SUCCESS] Quick test phases passed.")
        else:
            print("  [SUCCESS] All test phases passed.")
    elif any_incomplete and not total_f:
        print("  [INCOMPLETE] One or more phases skipped required coverage.")
    else:
        print("  [FAIL] One or more phases failed - see output above.")

    print(SEP2)
    if total_f:
        sys.exit(1)
    if any_incomplete:
        sys.exit(2)
    sys.exit(0)


if __name__ == '__main__':
    main()
