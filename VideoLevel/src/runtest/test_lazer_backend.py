"""Contracts for the Linux-only LaZer integration boundary."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtest._helpers import run_test, section, summarise


def t_lazer_preflight_accepts_a_supported_linux_avx512_host() -> None:
    from src.lazer_backend import assess_lazer_host

    assessment = assess_lazer_host(
        system_name="Linux",
        machine="x86_64",
        cpu_flags={"avx512f", "aes"},
        docker_available=True,
    )

    assert assessment.ready
    assert assessment.blockers == ()


def t_lazer_preflight_fails_closed_without_avx512_or_linux() -> None:
    from src.lazer_backend import assess_lazer_host

    assessment = assess_lazer_host(
        system_name="Windows",
        machine="AMD64",
        cpu_flags={"aes", "avx2"},
        docker_available=True,
    )

    assert not assessment.ready
    assert "linux_required" in assessment.blockers
    assert "avx512f_required" in assessment.blockers


def t_lazer_lock_is_pinned_and_declares_the_general_relation_demo() -> None:
    from src.lazer_backend import load_lazer_lock

    lock = load_lazer_lock(ROOT / "lazer" / "LAZER.lock.json")

    assert lock.revision == "10eafeca4cd53ff4fc54193dce904dbd0026fefd"
    assert lock.demo_path == "python/demo/demo.py"
    assert lock.relation == "A*s=t"


def main() -> None:
    section("LaZer Linux backend")
    results = [
        run_test("lazer_preflight_accepts_a_supported_linux_avx512_host", t_lazer_preflight_accepts_a_supported_linux_avx512_host),
        run_test("lazer_preflight_fails_closed_without_avx512_or_linux", t_lazer_preflight_fails_closed_without_avx512_or_linux),
        run_test("lazer_lock_is_pinned_and_declares_the_general_relation_demo", t_lazer_lock_is_pinned_and_declares_the_general_relation_demo),
    ]
    raise SystemExit(summarise(results, "LaZer Linux backend"))


if __name__ == "__main__":
    main()
