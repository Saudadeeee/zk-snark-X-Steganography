"""
clean_artifacts.py - Controlled cleanup for benchmark and stego artifacts.

Usage:
  py -3.12 benchmark/clean_artifacts.py --diagnostic
  py -3.12 benchmark/clean_artifacts.py --stego
  py -3.12 benchmark/clean_artifacts.py --cache
  py -3.12 benchmark/clean_artifacts.py --heavy-local
  py -3.12 benchmark/clean_artifacts.py --presentation-scratch
  py -3.12 benchmark/clean_artifacts.py --all-rebuildable
"""

import argparse
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_RESULTS = ROOT / "benchmark" / "results"
OUTPUT_DIR = ROOT / "data" / "output"
CACHE_DIR = ROOT / ".cache"


def _remove(paths: list[Path]) -> int:
    removed = 0
    for path in paths:
        if path.exists():
            try:
                if path.is_dir():
                    for child in sorted(path.rglob("*"), reverse=True):
                        if child.is_file():
                            child.unlink(missing_ok=True)
                    for child in sorted(path.rglob("*"), reverse=True):
                        if child.is_dir():
                            child.rmdir()
                    path.rmdir()
                else:
                    path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                pass
    return removed


def clean_diagnostic() -> int:
    patterns = [
        "_sec*.h264",
        "_sec*.json",
        "_sec*.png",
        "sec3_ablation.*",
        "patchable_capacity_scan.json",
        "_run_metadata.json",
    ]
    matches = []
    for pattern in patterns:
        matches.extend(BENCHMARK_RESULTS.glob(pattern))
        matches.extend(OUTPUT_DIR.glob(pattern))
    return _remove(list({p.resolve() for p in matches}))


def clean_stego() -> int:
    patterns = [
        "*.h264",
        "*.positions.json",
        "*.meta.json",
        "*.manifest.json",
        "*.validated_pool.json",
    ]
    matches = []
    for pattern in patterns:
        matches.extend(OUTPUT_DIR.glob(pattern))
    return _remove(list({p.resolve() for p in matches}))


def clean_cache() -> int:
    targets = [
        CACHE_DIR,
        BENCHMARK_RESULTS / "_proof_payload_cache.bin",
    ]
    return _remove(targets)


def clean_heavy_local(project_root: Path = ROOT) -> int:
    """Remove only known rebuildable, untracked heavyweight local workdirs."""
    root = project_root.resolve(strict=True)
    targets = [root / "tmp" / "benchmark_new_smoke"]
    targets.extend((root / "demo" / "runs").glob("*/python_analysis_cache"))
    validated = []
    for path in targets:
        if not path.exists():
            continue
        for ancestor in (path, *path.parents):
            if ancestor == root:
                break
            if ancestor.is_symlink() or ancestor.is_junction():
                raise ValueError(f"refusing linked cleanup path: {ancestor}")
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root) or resolved == root:
            raise ValueError(f"cleanup target escapes project: {path}")
        for child in path.rglob("*"):
            if child.is_symlink() or child.is_junction():
                raise ValueError(f"refusing linked content in cleanup target: {child}")
        tracked = subprocess.run(
            ["git", "--literal-pathspecs", "ls-files", "-z", "--", path.relative_to(root).as_posix()],
            cwd=root,
            capture_output=True,
            check=True,
        )
        if tracked.stdout:
            raise ValueError(f"refusing tracked content in cleanup target: {path}")
        validated.append(path)
    for path in validated:
        shutil.rmtree(path)
    return len(validated)


def _walk_without_links(directory: Path):
    for child in directory.iterdir():
        yield child
        if child.is_dir() and not child.is_symlink() and not child.is_junction():
            yield from _walk_without_links(child)


def clean_presentation_scratch(project_root: Path = ROOT) -> int:
    """Remove only root-level presentation build/chart scratch, not final decks."""
    root = project_root.resolve(strict=True)
    targets = [root / ".build-presentation", *root.glob(".chart-data-*")]
    validated = []
    junctions = []
    for path in targets:
        if not path.exists():
            continue
        if not path.is_dir():
            raise ValueError(f"presentation target is not a directory: {path}")
        for ancestor in (path, *path.parents):
            if ancestor == root:
                break
            if ancestor.is_symlink() or ancestor.is_junction():
                raise ValueError(f"refusing linked cleanup path: {ancestor}")
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root) or resolved == root:
            raise ValueError(f"cleanup target escapes project: {path}")
        for child in _walk_without_links(path):
            if child.is_symlink() or child.is_junction():
                if path.name == ".build-presentation" and child == path / "node_modules" and child.is_junction():
                    junctions.append(child)
                else:
                    raise ValueError(f"refusing linked content in cleanup target: {child}")
        tracked = subprocess.run(
            ["git", "--literal-pathspecs", "ls-files", "-z", "--", path.relative_to(root).as_posix()],
            cwd=root,
            capture_output=True,
            check=True,
        )
        if tracked.stdout:
            raise ValueError(f"refusing tracked content in cleanup target: {path}")
        validated.append(path)
    for junction in junctions:
        junction.rmdir()  # Windows RemoveDirectory unlinks the junction only.
    for path in validated:
        shutil.rmtree(path)
    return len(validated)


def main():
    parser = argparse.ArgumentParser(description="Clean benchmark and stego artifacts")
    parser.add_argument("--diagnostic", action="store_true", help="Remove diagnostic benchmark outputs")
    parser.add_argument("--stego", action="store_true", help="Remove stego outputs and sidecars")
    parser.add_argument("--cache", action="store_true", help="Remove caches")
    parser.add_argument(
        "--heavy-local",
        action="store_true",
        help="Remove legacy smoke benchmark workdir and demo analysis caches",
    )
    parser.add_argument(
        "--presentation-scratch",
        action="store_true",
        help="Remove root-level presentation build/chart scratch, not final decks",
    )
    parser.add_argument("--all-rebuildable", action="store_true", help="Remove all rebuildable artifacts")
    args = parser.parse_args()

    if not any([args.diagnostic, args.stego, args.cache, args.heavy_local, args.presentation_scratch, args.all_rebuildable]):
        parser.error("select at least one cleanup mode")

    removed = 0
    if args.all_rebuildable or args.diagnostic:
        removed += clean_diagnostic()
    if args.all_rebuildable or args.stego:
        removed += clean_stego()
    if args.all_rebuildable or args.cache:
        removed += clean_cache()
    if args.all_rebuildable or args.heavy_local:
        removed += clean_heavy_local()
    if args.presentation_scratch:
        removed += clean_presentation_scratch()

    print(f"Removed {removed} artifact roots")


if __name__ == "__main__":
    main()
