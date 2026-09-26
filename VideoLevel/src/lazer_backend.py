"""Fail-closed integration boundary for the Linux-only LaZer research backend.

LaZer is not a replacement for ML-DSA receipts by itself.  This module only
admits a host for a future reviewed lattice-ZK sidecar when its documented
Linux/x86-64/AVX-512/AES prerequisites are present.  No public video API calls
LaZer until an application relation and its proof serialization are reviewed.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

LAZER_LOCK_VERSION = 1
LAZER_REQUIRED_FLAGS = frozenset({"avx512f", "aes"})
LAZER_PREFLIGHT_IMAGE = "debian@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171"
LAZER_BASE_IMAGE = "ubuntu@sha256:69cecf4bbf72d2d44a9eef1b71fb98c7fb973d78af11399deccef19beb008ad9"


@dataclass(frozen=True)
class LazerLock:
    repository: str
    revision: str
    demo_path: str
    relation: str
    purpose: str


@dataclass(frozen=True)
class LazerHostAssessment:
    system_name: str
    machine: str
    cpu_flags: tuple[str, ...]
    docker_available: bool
    ready: bool
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def load_lazer_lock(path: str | Path) -> LazerLock:
    """Load a strict, immutable source pin rather than tracking a branch."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("lock_version") != LAZER_LOCK_VERSION:
        raise ValueError("unsupported LaZer lock version")
    revision = data.get("revision")
    if not isinstance(revision, str) or len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
        raise ValueError("LaZer revision must be a lowercase 40-character Git SHA")
    lock = LazerLock(
        repository=str(data["repository"]),
        revision=revision,
        demo_path=str(data["demo_path"]),
        relation=str(data["relation"]),
        purpose=str(data["purpose"]),
    )
    if lock.repository != "https://github.com/lazer-crypto/lazer.git":
        raise ValueError("unexpected LaZer source repository")
    if lock.demo_path != "python/demo/demo.py" or lock.relation != "A*s=t":
        raise ValueError("LaZer lock must target the reviewed general linear-relation demo")
    return lock


def dockerfile_matches_lazer_lock(path: str | Path, lock: LazerLock) -> bool:
    """Ensure the Docker recipe cannot be overridden away from the lock pin."""
    source = Path(path).read_text(encoding="utf-8")
    required = (
        f"FROM {LAZER_BASE_IMAGE}",
        f"git clone \"{lock.repository}\" /opt/lazer",
        f"git -C /opt/lazer checkout --detach \"{lock.revision}\"",
        f"test \"$(git -C /opt/lazer rev-parse HEAD)\" = \"{lock.revision}\"",
    )
    return "ARG LAZER_" not in source and all(fragment in source for fragment in required)


def assess_lazer_host(
    *, system_name: str, machine: str, cpu_flags: Iterable[str], docker_available: bool
) -> LazerHostAssessment:
    """Return an explicit allow/deny decision for executing LaZer.

    The checks intentionally use only advertised architecture properties.  A
    Docker daemon does not manufacture unavailable AVX-512 instructions, so it
    is recorded for diagnostics but never bypasses the CPU checks.
    """
    normalized_system = str(system_name).strip().lower()
    normalized_machine = str(machine).strip().lower()
    flags = tuple(sorted({str(flag).strip().lower() for flag in cpu_flags if str(flag).strip()}))
    blockers: list[str] = []
    if normalized_system != "linux":
        blockers.append("linux_required")
    if normalized_machine not in {"x86_64", "amd64"}:
        blockers.append("x86_64_required")
    for required in sorted(LAZER_REQUIRED_FLAGS):
        if required not in flags:
            blockers.append(f"{required}_required")
    if not docker_available:
        blockers.append("docker_required")
    return LazerHostAssessment(
        system_name=str(system_name), machine=str(machine), cpu_flags=flags,
        docker_available=bool(docker_available), ready=not blockers, blockers=tuple(blockers),
    )


def _docker_daemon_available() -> bool:
    """Check the Docker Engine, not merely whether the CLI binary is installed."""
    if shutil.which("docker") is None:
        return False
    try:
        completed = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _linux_cpu_flags() -> set[str]:
    cpuinfo = Path("/proc/cpuinfo")
    if not cpuinfo.is_file():
        return set()
    for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.lower().startswith("flags") and ":" in line:
            return set(line.split(":", 1)[1].split())
    return set()


def assess_current_lazer_host() -> LazerHostAssessment:
    return assess_lazer_host(
        system_name=platform.system(), machine=platform.machine(),
        cpu_flags=_linux_cpu_flags(), docker_available=_docker_daemon_available(),
    )


def assess_docker_lazer_host(image: str = LAZER_PREFLIGHT_IMAGE) -> LazerHostAssessment:
    """Assess the CPU flags actually visible to an amd64 Linux container."""
    if shutil.which("docker") is None:
        return assess_lazer_host(system_name="", machine="", cpu_flags=(), docker_available=False)
    if not _docker_daemon_available():
        return LazerHostAssessment(
            system_name="",
            machine="",
            cpu_flags=(),
            docker_available=False,
            ready=False,
            blockers=("docker_daemon_unavailable",),
        )
    completed = subprocess.run(
        ["docker", "run", "--rm", "--platform", "linux/amd64", image, "sh", "-c", "uname -s; uname -m; grep -m1 '^flags' /proc/cpuinfo || true"],
        check=False, capture_output=True, text=True, timeout=30,
    )
    lines = completed.stdout.splitlines()
    if completed.returncode != 0 or len(lines) < 2:
        return assess_lazer_host(system_name="", machine="", cpu_flags=(), docker_available=True)
    flags = lines[2].split(":", 1)[1].split() if len(lines) > 2 and ":" in lines[2] else ()
    return assess_lazer_host(system_name=lines[0], machine=lines[1], cpu_flags=flags, docker_available=True)


def docker_demo_command(image: str = "zkstego-lazer:10eafec") -> tuple[str, ...]:
    """Return the exact, shell-free command for the pinned smoke proof."""
    if not image or any(character.isspace() for character in image):
        raise ValueError("LaZer image name must be non-empty and contain no whitespace")
    return ("docker", "run", "--rm", "--platform", "linux/amd64", image)


def run_lazer_demo(
    image: str = "zkstego-lazer:10eafec", *, assessment: LazerHostAssessment | None = None,
    executor: object = subprocess.run,
) -> object:
    """Run the smoke proof only after rechecking container-visible hardware."""
    current = assessment or assess_docker_lazer_host()
    if not current.ready:
        raise RuntimeError("LaZer execution blocked: " + ", ".join(current.blockers))
    return executor(
        list(docker_demo_command(image)), check=False, capture_output=True, text=True, timeout=120,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LaZer Linux runtime preflight")
    parser.add_argument("--run", action="store_true", help="run the guarded pinned demo after preflight")
    parser.add_argument("--image", default="zkstego-lazer:10eafec")
    arguments = parser.parse_args()
    if arguments.run:
        result = run_lazer_demo(arguments.image)
        print(result.stdout, end="")
        raise SystemExit(result.returncode)
    print(json.dumps(assess_docker_lazer_host().to_dict(), sort_keys=True))
