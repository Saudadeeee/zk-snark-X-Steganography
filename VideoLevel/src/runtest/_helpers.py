"""
_helpers.py — Shared utilities for the runtest suite.

Usage in every test file:
    from src.runtest._helpers import setup_path, section, run_test, PASS, FAIL, SKIP
    setup_path()   # must be called before importing src.*
"""

from dataclasses import dataclass
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


def get_video(name: str = 'foreman_cif_q22_g1.h264') -> str:
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

@dataclass(frozen=True)
class TestResult:
    name: str
    status: str
    detail: str = ''

    def __bool__(self) -> bool:
        return self.status == 'pass'


class SkipTest(Exception):
    def __init__(self, name: str, reason: str = ''):
        super().__init__(reason)
        self.name = name
        self.reason = reason

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
    raise SkipTest(name, reason)


# ── Test runner ─────────────────────────────────────────────────────────── #

def run_test(name: str, fn) -> TestResult:
    """
    Execute fn(). Print PASS/FAIL/SKIP and return a structured result.
    """
    try:
        fn()
        PASS(name)
        return TestResult(name, 'pass')
    except SkipTest as exc:
        return TestResult(name, 'skip', exc.reason)
    except AssertionError as exc:
        FAIL(name, str(exc))
        return TestResult(name, 'fail', str(exc))
    except Exception as exc:
        FAIL(name, f"{type(exc).__name__}: {exc}")
        return TestResult(name, 'fail', f"{type(exc).__name__}: {exc}")


def summarise(results: list, phase_name: str) -> int:
    """Print pass/fail/skip summary. Returns 0 pass, 1 fail, 2 incomplete."""
    normalised = []
    for index, result in enumerate(results):
        if isinstance(result, TestResult):
            normalised.append(result)
        else:
            status = 'pass' if bool(result) else 'fail'
            normalised.append(TestResult(f"legacy_{index}", status))

    passed = sum(1 for result in normalised if result.status == 'pass')
    failed = sum(1 for result in normalised if result.status == 'fail')
    skipped = sum(1 for result in normalised if result.status == 'skip')
    total = len(results)
    if failed:
        status = 'FAIL'
        exit_code = 1
    elif skipped:
        status = 'INCOMPLETE'
        exit_code = 2
    else:
        status = 'OK'
        exit_code = 0
    print(
        f"\n  {phase_name}: {passed}/{total} passed, "
        f"{failed} failed, {skipped} skipped  [{status}]"
    )
    return exit_code
