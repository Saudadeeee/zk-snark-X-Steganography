"""
run_all.py — Run all phase tests in order and print a summary table.

Usage:
    python src/runtest/run_all.py

Exit code: 0 if all phases pass, 1 if any phase fails.
"""

import io
import os
import re
import subprocess
import sys

# ── Locate project root and test files ───────────────────────────────── #

ROOT     = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
RUNTEST  = os.path.join(ROOT, 'src', 'runtest')

PHASES = [
    ("Phase 1", "ZK Proof",           "test_phase1_zk_proof.py"),
    ("Phase 2", "H264 Parser",         "test_phase2_h264_parser.py"),
    ("Phase 3", "Safety + Embed",      "test_phase3_safety_embed.py"),
    ("Phase 4", "Reconstruct",         "test_phase4_reconstruct.py"),
    ("Phase 5", "Extract + Verify",    "test_phase5_extract_verify.py"),
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


# ── Main ─────────────────────────────────────────────────────────────── #

def main():
    # Force UTF-8 output on Windows (sys.stdout may be TextIOWrapper with cp1252)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    elif hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print()
    print(SEP2)
    print("  ZK-SNARK Video Steganography — Full Test Suite")
    print(SEP2)

    summary = []
    for label, desc, filename in PHASES:
        print(f"\n>>> Running {label} — {desc}")
        print(SEP)
        passed, failed, skipped, code = run_phase(label, desc, filename)
        print(SEP)
        total_run = passed + failed
        status    = 'OK' if code == 0 else 'FAIL'
        summary.append((label, desc, passed, failed, skipped, status))
        print(f"  {label} result: {passed}/{total_run} passed, {skipped} skipped  [{status}]")

    # Final summary table
    print()
    print(SEP2)
    print("  SUMMARY")
    print(SEP2)
    all_pass  = True
    total_p = total_f = total_s = 0
    for label, desc, p, f, s, status in summary:
        marker = '+' if status == 'OK' else 'X'
        col    = f"{p}/{p+f} passed"
        if s:
            col += f", {s} skipped"
        print(f"  [{marker}] {label:8s}  {desc:22s}  {col}")
        total_p += p; total_f += f; total_s += s
        if status != 'OK':
            all_pass = False

    print(SEP)
    print(f"  TOTAL: {total_p}/{total_p+total_f} passed"
          + (f", {total_s} skipped" if total_s else ""))
    print()

    if all_pass:
        print("  [SUCCESS] All test phases passed.")
    else:
        print("  [FAIL] One or more phases failed — see output above.")

    print(SEP2)
    sys.exit(0 if all_pass else 1)


if __name__ == '__main__':
    main()
