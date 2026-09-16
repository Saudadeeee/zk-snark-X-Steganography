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
    from src.lazer_backend import dockerfile_matches_lazer_lock, load_lazer_lock

    lock = load_lazer_lock(ROOT / "lazer" / "LAZER.lock.json")

    assert lock.revision == "10eafeca4cd53ff4fc54193dce904dbd0026fefd"
    assert lock.demo_path == "python/demo/demo.py"
    assert lock.relation == "A*s=t"
    assert dockerfile_matches_lazer_lock(ROOT / "lazer" / "Dockerfile", lock)


def t_lazer_runner_refuses_an_unsupported_container_host_before_execution() -> None:
    from src.lazer_backend import LazerHostAssessment, run_lazer_demo

    blocked = LazerHostAssessment(
        system_name="Linux", machine="x86_64", cpu_flags=("aes",), docker_available=True,
        ready=False, blockers=("avx512f_required",),
    )
    called = False

    def should_not_run(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("container must not start on an unsupported host")

    try:
        run_lazer_demo(assessment=blocked, executor=should_not_run)
    except RuntimeError as error:
        assert "avx512f_required" in str(error)
    else:
        raise AssertionError("unsupported LaZer host was accepted")
    assert not called


def main() -> None:
    section("LaZer Linux backend")
    results = [
        run_test("lazer_preflight_accepts_a_supported_linux_avx512_host", t_lazer_preflight_accepts_a_supported_linux_avx512_host),
        run_test("lazer_preflight_fails_closed_without_avx512_or_linux", t_lazer_preflight_fails_closed_without_avx512_or_linux),
        run_test("lazer_lock_is_pinned_and_declares_the_general_relation_demo", t_lazer_lock_is_pinned_and_declares_the_general_relation_demo),
        run_test("lazer_runner_refuses_an_unsupported_container_host_before_execution", t_lazer_runner_refuses_an_unsupported_container_host_before_execution),
    ]
    raise SystemExit(summarise(results, "LaZer Linux backend"))


if __name__ == "__main__":
    main()
