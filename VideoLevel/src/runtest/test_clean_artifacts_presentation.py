import os
import subprocess
from pathlib import Path

import pytest

from benchmark import clean_artifacts


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)


def test_presentation_cleanup_removes_only_scratch_directories(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    build = tmp_path / ".build-presentation"
    build.mkdir()
    (build / "draft.mjs").write_bytes(b"draft")
    chart = tmp_path / ".chart-data-one"
    chart.mkdir()
    (chart / "candidate.pptx").write_bytes(b"draft")
    empty_chart = tmp_path / ".chart-data-empty"
    empty_chart.mkdir()
    finalizer = tmp_path / ".codex-finalizer"
    finalizer.mkdir()
    (finalizer / "last_candidate.pptx").write_bytes(b"keep")
    report = tmp_path / "doc" / "report.pdf"
    report.parent.mkdir()
    report.write_bytes(b"keep")

    assert clean_artifacts.clean_presentation_scratch(tmp_path) == 3
    assert not build.exists()
    assert not chart.exists()
    assert not empty_chart.exists()
    assert (finalizer / "last_candidate.pptx").read_bytes() == b"keep"
    assert report.read_bytes() == b"keep"
    assert clean_artifacts.clean_presentation_scratch(tmp_path) == 0


def test_presentation_cleanup_refuses_tracked_content(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    chart = tmp_path / ".chart-data-old"
    chart.mkdir()
    tracked = chart / "keep.pptx"
    tracked.write_bytes(b"tracked")
    subprocess.run(
        ["git", "-C", str(tmp_path), "--literal-pathspecs", "add", "--", ".chart-data-old/keep.pptx"],
        check=True,
    )

    with pytest.raises(ValueError, match="tracked"):
        clean_artifacts.clean_presentation_scratch(tmp_path)
    assert tracked.read_bytes() == b"tracked"


def test_presentation_cleanup_refuses_unexpected_junction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init_repo(tmp_path)
    build = tmp_path / ".build-presentation"
    assets = build / "assets"
    assets.mkdir(parents=True)
    (assets / "keep.png").write_bytes(b"keep")
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda path: path == assets or original(path))

    with pytest.raises(ValueError, match="linked"):
        clean_artifacts.clean_presentation_scratch(tmp_path)
    assert (assets / "keep.png").read_bytes() == b"keep"


@pytest.mark.skipif(os.name != "nt", reason="Windows directory junction test")
def test_presentation_cleanup_removes_known_junction_not_its_target(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    build = tmp_path / ".build-presentation"
    build.mkdir()
    dependency = tmp_path / "shared-dependency"
    dependency.mkdir()
    keep = dependency / "keep.txt"
    keep.write_bytes(b"keep")
    junction = build / "node_modules"
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"New-Item -ItemType Junction -Path '{junction}' -Target '{dependency}' | Out-Null",
        ],
        check=True,
    )
    assert junction.is_junction()

    assert clean_artifacts.clean_presentation_scratch(tmp_path) == 1
    assert not build.exists()
    assert keep.read_bytes() == b"keep"
