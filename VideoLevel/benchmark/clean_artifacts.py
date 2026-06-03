"""
clean_artifacts.py - Controlled cleanup for benchmark and stego artifacts.

Usage:
  py -3.12 benchmark/clean_artifacts.py --diagnostic
  py -3.12 benchmark/clean_artifacts.py --stego
  py -3.12 benchmark/clean_artifacts.py --cache
  py -3.12 benchmark/clean_artifacts.py --all-rebuildable
"""

import argparse
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


def main():
    parser = argparse.ArgumentParser(description="Clean benchmark and stego artifacts")
    parser.add_argument("--diagnostic", action="store_true", help="Remove diagnostic benchmark outputs")
    parser.add_argument("--stego", action="store_true", help="Remove stego outputs and sidecars")
    parser.add_argument("--cache", action="store_true", help="Remove caches")
    parser.add_argument("--all-rebuildable", action="store_true", help="Remove all rebuildable artifacts")
    args = parser.parse_args()

    if not any([args.diagnostic, args.stego, args.cache, args.all_rebuildable]):
        parser.error("select at least one cleanup mode")

    removed = 0
    if args.all_rebuildable or args.diagnostic:
        removed += clean_diagnostic()
    if args.all_rebuildable or args.stego:
        removed += clean_stego()
    if args.all_rebuildable or args.cache:
        removed += clean_cache()

    print(f"Removed {removed} artifact roots")


if __name__ == "__main__":
    main()
