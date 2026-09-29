import subprocess
import sys
from pathlib import Path

import pytest

from benchmark import clean_artifacts


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)


def test_clean_heavy_local_removes_only_known_rebuildable_directories(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    smoke = tmp_path / "tmp" / "benchmark_new_smoke"
    smoke.mkdir(parents=True)
    (smoke / "old_proving_key.zkey").write_bytes(b"rebuildable")

    cache = tmp_path / "demo" / "runs" / "session_A" / "python_analysis_cache"
    cache.mkdir(parents=True)
    (cache / "analysis.pkl").write_bytes(b"rebuildable")

    keep = tmp_path / "demo" / "runs" / "session_A" / "stego_video.h264"
    keep.write_bytes(b"keep")
    other = tmp_path / "tmp" / "unrelated_input.h264"
    other.write_bytes(b"keep")

    assert clean_artifacts.clean_heavy_local(tmp_path) == 2
    assert not smoke.exists()
    assert not cache.exists()
    assert keep.read_bytes() == b"keep"
    assert other.read_bytes() == b"keep"
    assert clean_artifacts.clean_heavy_local(tmp_path) == 0


def test_clean_heavy_local_refuses_tracked_file(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    smoke = tmp_path / "tmp" / "benchmark_new_smoke"
    smoke.mkdir(parents=True)
    tracked = smoke / "keep.zkey"
    tracked.write_bytes(b"tracked")
    subprocess.run(["git", "-C", str(tmp_path), "add", "--", "tmp/benchmark_new_smoke/keep.zkey"], check=True)

    with pytest.raises(ValueError, match="tracked"):
        clean_artifacts.clean_heavy_local(tmp_path)
    assert tracked.read_bytes() == b"tracked"


def test_clean_heavy_local_validates_all_targets_before_deleting(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    smoke = tmp_path / "tmp" / "benchmark_new_smoke"
    smoke.mkdir(parents=True)
    (smoke / "scratch.zkey").write_bytes(b"scratch")
    cache = tmp_path / "demo" / "runs" / "session_A" / "python_analysis_cache"
    cache.mkdir(parents=True)
    tracked = cache / "keep.pkl"
    tracked.write_bytes(b"tracked")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "--", "demo/runs/session_A/python_analysis_cache/keep.pkl"],
        check=True,
    )

    with pytest.raises(ValueError, match="tracked"):
        clean_artifacts.clean_heavy_local(tmp_path)
    assert smoke.exists()
    assert tracked.exists()


def test_clean_heavy_local_refuses_tracked_bracket_session(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    cache = tmp_path / "demo" / "runs" / "session[1]" / "python_analysis_cache"
    cache.mkdir(parents=True)
    tracked = cache / "keep.pkl"
    tracked.write_bytes(b"tracked")
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "--literal-pathspecs",
            "add",
            "--",
            "demo/runs/session[1]/python_analysis_cache/keep.pkl",
        ],
        check=True,
    )

    with pytest.raises(ValueError, match="tracked"):
        clean_artifacts.clean_heavy_local(tmp_path)
    assert tracked.read_bytes() == b"tracked"


def test_clean_heavy_local_refuses_linked_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init_repo(tmp_path)
    smoke = tmp_path / "tmp" / "benchmark_new_smoke"
    smoke.mkdir(parents=True)
    data = smoke / "keep.zkey"
    data.write_bytes(b"keep")
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda path: path == tmp_path / "tmp" or original(path))

    with pytest.raises(ValueError, match="linked"):
        clean_artifacts.clean_heavy_local(tmp_path)
    assert data.read_bytes() == b"keep"


def test_all_rebuildable_includes_heavy_local(monkeypatch: pytest.MonkeyPatch) -> None:
    called = []
    monkeypatch.setattr(clean_artifacts, "clean_diagnostic", lambda: 0)
    monkeypatch.setattr(clean_artifacts, "clean_stego", lambda: 0)
    monkeypatch.setattr(clean_artifacts, "clean_cache", lambda: 0)
    monkeypatch.setattr(clean_artifacts, "clean_heavy_local", lambda: called.append(True) or 0)
    monkeypatch.setattr(sys, "argv", ["clean_artifacts.py", "--all-rebuildable"])

    clean_artifacts.main()

    assert called == [True]
