"""
patchable_capacity_scan.py - Measure patchable usable capacity across assets.

Outputs:
  - benchmark/results/patchable_capacity_scan.json

Usage:
  py -3.12 benchmark/patchable_capacity_scan.py
  py -3.12 benchmark/patchable_capacity_scan.py --force
  py -3.12 benchmark/patchable_capacity_scan.py --sequences foreman_q22_g1,deadline_q22_g1
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import (
    RESULTS_DIR,
    SEQUENCES,
    cache_load,
    cache_save,
    get_capacity_views,
    measure_patchable_usable_bits,
)

CACHE_KEY = "patchable_capacity_scan"


def _scan_meta(sequence_names: list[str]) -> dict[str, object]:
    return {
        "sequence_names": list(sequence_names),
        "source_mtimes": {
            seq: os.path.getmtime(str(SEQUENCES[seq]))
            for seq in sequence_names
            if seq in SEQUENCES and Path(SEQUENCES[seq]).exists()
        },
    }


def collect_data(
    force: bool = False,
    include_sequences: set[str] | None = None,
    max_positions: int | None = None,
) -> dict:
    sequence_names = [seq for seq in SEQUENCES if include_sequences is None or seq in include_sequences]
    meta = _scan_meta(sequence_names)
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        if isinstance(cached, dict) and cached.get("__meta__") == meta and "data" in cached:
            print("  [cache hit] patchable capacity scan")
            return cached["data"]

    data: dict[str, dict[str, object]] = {}

    for seq_name in sequence_names:
        video_path = SEQUENCES[seq_name]
        if not Path(video_path).exists():
            continue
        print(f"  [{seq_name}] scanning patchable usable bits ...")
        scan = measure_patchable_usable_bits(video_path, force=force, max_positions=max_positions)
        caps = get_capacity_views(seq_name, video_path, force=force)
        data[seq_name] = {
            "video_path": str(video_path),
            "raw_safe_bits": int(caps["raw_safe_bits"]),
            "patchable_usable_bits": int(scan["patchable_usable_bits"]),
            "validated_pool_bits": caps["validated_pool_bits"],
            "operating_bits": caps["operating_bits"],
            "bits_embedded": caps["bits_embedded"],
            "bits_required": caps["bits_required"],
        }

    cache_save(CACHE_KEY, {"__meta__": meta, "data": data})
    return data


def print_summary(data: dict) -> None:
    ranked = sorted(
        data.items(),
        key=lambda kv: (int(kv[1].get("patchable_usable_bits") or 0), int(kv[1].get("raw_safe_bits") or 0)),
        reverse=True,
    )
    print("\nPatchable usable capacity ranking:")
    for seq_name, row in ranked:
        print(
            f"  {seq_name:<28} "
            f"patchable={int(row.get('patchable_usable_bits') or 0):>8}  "
            f"raw_safe={int(row.get('raw_safe_bits') or 0):>8}  "
            f"validated={str(row.get('validated_pool_bits')):>8}  "
            f"operating={str(row.get('operating_bits')):>8}"
        )
    out_path = RESULTS_DIR / f"{CACHE_KEY}.json"
    print(f"\n  [saved] {out_path.name}")


def main():
    parser = argparse.ArgumentParser(description="Scan patchable usable capacity across encoded assets")
    parser.add_argument("--force", action="store_true", help="Ignore cached scan results")
    parser.add_argument(
        "--sequences",
        type=str,
        default="",
        help="Comma-separated sequence names to scan",
    )
    parser.add_argument(
        "--max-positions",
        type=int,
        default=1600,
        help="Only measure up to this many positions per asset (default: 1600)",
    )
    args = parser.parse_args()
    selected = {s.strip() for s in args.sequences.split(",") if s.strip()} or None
    data = collect_data(force=args.force, include_sequences=selected, max_positions=args.max_positions)
    print_summary(data)


if __name__ == "__main__":
    main()
