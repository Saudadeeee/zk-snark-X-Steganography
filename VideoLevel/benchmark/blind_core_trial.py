"""
blind_core_trial.py - Blind-core self-consistency diagnostic.

Checks whether the same blind position derivation is reproduced between:
  1. the original cover video
  2. the corresponding locked SEC1 stego video

This is lighter and more actionable than forcing a full blind E2E trial while
the architecture is still being shaped.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import OUTPUT_DIR, RESULTS_DIR, cache_load, cache_save, select_best_sec1_operating_asset
from src.blind_sync import derive_blind_positions_validated_pool_proxy

CACHE_KEY = "blind_core_trial"
SECRET_KEY = b"zk_mv_stego_2026_secret_key!!!!!"
MESSAGE = b"Hello ZK-Stego"


def collect_data(force: bool = False) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        print("  [cache hit] blind core trial")
        return cached

    required_bits = (4 + len(MESSAGE) + 129) * 8
    seq_name, video_path = select_best_sec1_operating_asset(
        required_bits=1232,
        preferred_sequences=[
            "coastguard_q22_g1",
            "deadline_q22_g1",
            "coastguard_q22_g1_1000f",
            "foreman_q22_g1",
        ],
    )
    if not seq_name or not video_path:
        raise RuntimeError("No SEC1 operating asset available for blind core trial")

    stego_path = OUTPUT_DIR / f"sec1_stego_{seq_name}.h264"
    if not stego_path.exists():
        raise RuntimeError(f"Missing SEC1 stego artifact for {seq_name}")

    cover_positions, cover_metadata = derive_blind_positions_validated_pool_proxy(
        video_path,
        SECRET_KEY,
        required_bits=required_bits,
        use_analysis_cache=True,
    )
    stego_positions, stego_metadata = derive_blind_positions_validated_pool_proxy(
        str(stego_path),
        SECRET_KEY,
        required_bits=required_bits,
        use_analysis_cache=True,
    )

    set_overlap = len(set(cover_positions) & set(stego_positions))
    prefix_match = sum(1 for a, b in zip(cover_positions, stego_positions) if a == b)

    data = {
        "sequence": seq_name,
        "video_path": video_path,
        "stego_path": str(stego_path),
        "required_bits": required_bits,
        "cover_positions": len(cover_positions),
        "stego_positions": len(stego_positions),
        "set_overlap": set_overlap,
        "set_overlap_ratio": set_overlap / max(1, len(cover_positions)),
        "prefix_match": prefix_match,
        "prefix_match_ratio": prefix_match / max(1, len(cover_positions)),
        "cover_metadata": cover_metadata.__dict__,
        "stego_metadata": stego_metadata.__dict__,
    }
    cache_save(CACHE_KEY, data)
    return data


def run(force: bool = False) -> dict:
    print("\n=== Blind Core Trial ===")
    data = collect_data(force=force)
    print(
        f"  [{data['sequence']}] cover/stego overlap={data['set_overlap']}/{data['cover_positions']} "
        f"({data['set_overlap_ratio']:.3f}), prefix={data['prefix_match']}/{data['cover_positions']} "
        f"({data['prefix_match_ratio']:.3f})"
    )
    print(f"  [saved] {(RESULTS_DIR / f'{CACHE_KEY}.json').name}")
    return data


if __name__ == "__main__":
    run(force="--force" in sys.argv)
