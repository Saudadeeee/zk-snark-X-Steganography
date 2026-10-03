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
    ("Phase 1", "ZK proof (Groth16)",          "test_zk_proof.py"),
    ("Phase 2", "Native contract (C++/Python)", "test_native_blind_contract.py"),
    ("Phase 3", "Native CLI fixture E2E",      "test_native_cli_fixture.py"),
    ("Phase 4", "H.264 VLC tables",            "test_h264_tables.py"),
    ("Phase 5", "Service API",                 "test_service_api.py"),
    ("Phase 6", "Native HTTP/stream E2E",      "test_native_http_channel.py"),
    ("Phase 7", "Manifest security",           "test_manifest_security.py"),
    ("Phase 8", "Realtime scheduler",          "test_realtime_scheduler.py"),
    ("Phase 9", "Benchmark recorder",          "test_benchmark_recorder.py"),
    ("Phase 10", "Trust interfaces",           "test_trust_interfaces.py"),
    ("Phase 11", "Demo H.264 explain math",    "test_demo_h264_explain.py"),
    ("Phase 12", "Demo smoke",                 "test_demo_smoke.py"),
]

# Requires a physical DirectShow camera (ZK_STEGO_CAMERA_NAME); run with --hardware.
HARDWARE_PHASES = [
    ("Phase H1", "Native camera HTTP E2E", "test_native_camera_http.py"),
]

# Fast subset: no FFmpeg-heavy demo runs, no fixture-wide native E2E.
QUICK_PHASE_LABELS = {
    "Phase 1", "Phase 2", "Phase 4", "Phase 5", "Phase 6", "Phase 7", "Phase 8", "Phase 9",
}

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
    parser.add_argument(
        "--hardware",
        action="store_true",
        help="Also run hardware-gated phases (physical camera; needs ZK_STEGO_CAMERA_NAME)",
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

    selected_phases = [phase for phase in PHASES if phase[0] in QUICK_PHASE_LABELS] if args.quick else list(PHASES)
    if args.hardware:
        selected_phases += HARDWARE_PHASES
    missing = [name for _, _, name in selected_phases if not os.path.isfile(os.path.join(RUNTEST, name))]
    if missing:
        # A registered phase without its file can never pass; fail loudly up front.
        print(f"  [FAIL] Registered test files are missing: {', '.join(missing)}")
        sys.exit(1)
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
