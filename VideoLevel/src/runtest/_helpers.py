"""
_helpers.py — Shared utilities for the runtest suite.

Usage in every test file:
    from src.runtest._helpers import setup_path, section, run_test, PASS, FAIL, SKIP
    setup_path()   # must be called before importing src.*
"""

import io
import os
import shutil
import sys


# ── Path setup ─────────────────────────────────────────────────────────── #

def get_project_root() -> str:
    """Return absolute path to project root (two levels above this file)."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def setup_path():
    """Add project root to sys.path so 'from src.X import Y' works."""
    root = get_project_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    # Force UTF-8 stdout on Windows
    if hasattr(sys.stdout, 'buffer') and not isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def get_video(name: str = 'foreman_cif_g8.h264') -> str:
    return os.path.join(get_project_root(), 'data', 'encoded', name)


def get_output(name: str) -> str:
    path = os.path.join(get_project_root(), 'data', 'output', name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def get_circuits_dir() -> str:
    return os.path.join(get_project_root(), 'circuits')


def node_available() -> bool:
    """Return True if 'node' executable is on PATH."""
    return shutil.which('node') is not None


# ── Output helpers ─────────────────────────────────────────────────────── #

def section(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def PASS(name: str):
    print(f"  [PASS] {name}")


def FAIL(name: str, detail: str = ''):
    msg = f"  [FAIL] {name}"
    if detail:
        msg += f"\n         {detail}"
    print(msg)


def SKIP(name: str, reason: str = ''):
    msg = f"  [SKIP] {name}"
    if reason:
        msg += f"  ({reason})"
    print(msg)


# ── Test runner ─────────────────────────────────────────────────────────── #

def run_test(name: str, fn) -> bool:
    """
    Execute fn().  Print PASS on success, FAIL with detail on any exception.
    Returns True if passed, False if failed.
    """
    try:
        fn()
        PASS(name)
        return True
    except AssertionError as exc:
        FAIL(name, str(exc))
        return False
    except Exception as exc:
        FAIL(name, f"{type(exc).__name__}: {exc}")
        return False


def summarise(results: list, phase_name: str) -> int:
    """Print pass/fail summary. Returns exit code (0 = all pass)."""
    passed = sum(results)
    total = len(results)
    status = 'OK' if passed == total else 'FAIL'
    print(f"\n  {phase_name}: {passed}/{total} passed  [{status}]")
    return 0 if passed == total else 1
