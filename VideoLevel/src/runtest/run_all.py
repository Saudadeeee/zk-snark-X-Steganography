"""
run_all.py — Run all phase tests in order and print a summary table.

Usage:
    python src/runtest/run_all.py

Exit code: 0 if all phases pass, 1 if any phase fails, 2 if any phase is incomplete.
"""

import argparse
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
    ("Phase 4", "Reconstruct",         "test_phase4_reconstruct.py"),
    ("Phase 5", "Extract + Verify",    "test_phase5_extract_verify.py"),
    ("Phase 6", "Security Hardening",  "test_phase6_security_hardening.py"),
    ("Phase 7", "HTTP + Key Expiry",   "test_phase7_service_delivery.py"),
    ("Phase 8", "Blind Extraction",    "test_phase8_blind_extraction.py"),
    ("Phase 9", "Realtime CAVLC",      "test_phase9_realtime_cavlc.py"),
    ("Phase 10", "Native CLI Fixture E2E", "test_native_cli_fixture.py"),
    ("Phase 11", "Benchmark Reproducibility", "test_phase11_benchmark_reproducibility.py"),
    ("Phase 12", "Native HTTP/Stream E2E", "test_native_http_channel.py"),
]

QUICK_PHASE_LABELS = {"Phase 1", "Phase 6", "Phase 7", "Phase 9", "Phase 11", "Phase 12"}

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
        check=False,
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


def status_for_phase_result(passed: int, failed: int, skipped: int, exit_code: int) -> str:
    """Reject failed or empty test output even if a phase exits with code zero."""
    if failed > 0 or exit_code not in {0, 2}:
        return 'FAIL'
    if exit_code == 2 or skipped > 0:
        return 'INCOMPLETE'
    if passed <= 0:
        return 'FAIL'
    return 'OK'


def exit_code_for_phase_statuses(statuses: list[str]) -> int:
    """Return nonzero unless every selected phase completed successfully."""
    if not statuses or any(status not in {'OK', 'INCOMPLETE'} for status in statuses):
        return 1
    if any(status == 'INCOMPLETE' for status in statuses):
        return 2
    return 0


# ── Main ─────────────────────────────────────────────────────────────── #

def main():
    parser = argparse.ArgumentParser(description="Run full or quick phase test suite")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run only the fast proof and security phases, skipping video reconstruction and verification",
    )
    args = parser.parse_args()

    # Force UTF-8 output on Windows (sys.stdout may be TextIOWrapper with cp1252)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    elif hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print()
    print(SEP2)
    print("  ZK-SNARK Video Steganography — Full Test Suite")
    print(SEP2)

    selected_phases = [phase for phase in PHASES if phase[0] in QUICK_PHASE_LABELS] if args.quick else PHASES
    summary = []
    for label, desc, filename in selected_phases:
        print(f"\n>>> Running {label} — {desc}")
        print(SEP)
        passed, failed, skipped, code = run_phase(label, desc, filename)
        print(SEP)
        total_run = passed + failed + skipped
        status    = status_for_phase_result(passed, failed, skipped, code)
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
        print("  [FAIL] One or more phases failed — see output above.")

    print(SEP2)
    sys.exit(exit_code_for_phase_statuses([status for _, _, _, _, _, status in summary]))


if __name__ == '__main__':
    main()
