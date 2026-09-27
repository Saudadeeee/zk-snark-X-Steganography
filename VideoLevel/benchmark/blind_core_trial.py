"""
blind_core_trial.py - Blind-core self-consistency diagnostic.

Checks whether the same blind position derivation is reproduced between:
  1. the original cover video
  2. the corresponding locked SEC1 stego video

This is lighter and more actionable than forcing a full blind E2E trial while
the architecture is still being shaped.
"""

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import RESULTS_DIR, cache_load, cache_save, load_sec1_positions
from benchmark.locked_operating_contract import (
    LOCKED_CHAOS_KEY,
    load_best_locked_operating_contract,
)
from src.blind_sync import derive_blind_positions_validated_pool_proxy

CACHE_KEY = "blind_core_trial"
BLIND_SYNC_KEY = LOCKED_CHAOS_KEY
MESSAGE = b"Hello ZK-Stego"
PREFERRED_SEQUENCES = [
    "coastguard_q22_g1",
    "deadline_q22_g1_600f",
    "deadline_q22_g1",
    "coastguard_q22_g1_1000f",
    "foreman_q22_g1",
]


def _worker_process_id() -> int:
    """Return the executing process ID; also used to verify isolation."""
    return os.getpid()


def _derive_blind_positions_worker(
    video_path: str,
    sync_key: bytes,
    required_bits: int,
) -> tuple[list[tuple[int, int, int]], dict]:
    positions, metadata = derive_blind_positions_validated_pool_proxy(
        video_path,
        sync_key,
        required_bits=required_bits,
        use_analysis_cache=False,
    )
    return positions, metadata.__dict__


def run_isolated(worker, *args):
    """Run one video analysis in a disposable process to release parser heap."""
    with ProcessPoolExecutor(max_workers=1) as executor:
        return executor.submit(worker, *args).result()


def _select_operating_asset(required_bits: int) -> tuple[str, str, str, int]:
    contract = load_best_locked_operating_contract(
        required_bits=required_bits,
        preferred_sequences=PREFERRED_SEQUENCES,
    )
    if contract is None:
        raise RuntimeError("No verified SEC1 operating asset meets required_bits")
    return (
        contract.sequence_name,
        contract.video_path,
        contract.stego_path,
        int(contract.bits_required),
    )


def _position_match_stats(
    derived: list[tuple[int, int, int]],
    reference: list[tuple[int, int, int]],
) -> dict[str, float | int]:
    derived_set = {tuple(int(value) for value in position) for position in derived}
    reference_set = {tuple(int(value) for value in position) for position in reference}
    overlap = len(derived_set & reference_set)
    prefix_match = sum(left == right for left, right in zip(derived, reference))
    return {
        "set_overlap": overlap,
        "set_overlap_ratio": overlap / max(1, len(derived_set)),
        "prefix_match": prefix_match,
        "prefix_match_ratio": prefix_match / max(1, len(derived)),
    }


def collect_data(force: bool = False) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        print("  [cache hit] blind core trial")
        return cached

    seq_name, video_path, stego_path, required_bits = _select_operating_asset(required_bits=1232)
    stego_path = Path(stego_path)
    if not stego_path.exists():
        raise RuntimeError(f"Missing SEC1 stego artifact for {seq_name}")

    cover_positions, cover_metadata = run_isolated(
        _derive_blind_positions_worker,
        video_path,
        BLIND_SYNC_KEY,
        required_bits,
    )
    stego_positions, stego_metadata = run_isolated(
        _derive_blind_positions_worker,
        str(stego_path),
        BLIND_SYNC_KEY,
        required_bits,
    )

    cover_stego_match = _position_match_stats(cover_positions, stego_positions)
    embedded_positions = load_sec1_positions(seq_name, validated_pool=False)
    blind_embedding_match = _position_match_stats(stego_positions, embedded_positions)

    data = {
        "sequence": seq_name,
        "video_path": video_path,
        "stego_path": str(stego_path),
        "required_bits": required_bits,
        "cover_positions": len(cover_positions),
        "stego_positions": len(stego_positions),
        "cover_stego_set_overlap": cover_stego_match["set_overlap"],
        "cover_stego_set_overlap_ratio": cover_stego_match["set_overlap_ratio"],
        "cover_stego_prefix_match": cover_stego_match["prefix_match"],
        "cover_stego_prefix_match_ratio": cover_stego_match["prefix_match_ratio"],
        "embedded_positions": len(embedded_positions),
        "blind_embedding_set_overlap": blind_embedding_match["set_overlap"],
        "blind_embedding_set_overlap_ratio": blind_embedding_match["set_overlap_ratio"],
        "blind_embedding_prefix_match": blind_embedding_match["prefix_match"],
        "blind_embedding_prefix_match_ratio": blind_embedding_match["prefix_match_ratio"],
        "cover_metadata": cover_metadata,
        "stego_metadata": stego_metadata,
    }
    cache_save(CACHE_KEY, data)
    return data


def run(force: bool = False) -> dict:
    print("\n=== Blind Core Trial ===")
    data = collect_data(force=force)
    print(f"  [{data['sequence']}] cover/stego derived positions:")
    print(
        f"    overlap={data['cover_stego_set_overlap']}/{data['cover_positions']} "
        f"({data['cover_stego_set_overlap_ratio']:.3f}), "
        f"prefix={data['cover_stego_prefix_match']}/{data['cover_positions']} "
        f"({data['cover_stego_prefix_match_ratio']:.3f})"
    )
    print(f"  Blind-derived vs embedded positions sidecar (benchmark ground truth only):")
    print(
        f"    overlap={data['blind_embedding_set_overlap']}/{data['stego_positions']} "
        f"({data['blind_embedding_set_overlap_ratio']:.3f}), "
        f"prefix={data['blind_embedding_prefix_match']}/{data['stego_positions']} "
        f"({data['blind_embedding_prefix_match_ratio']:.3f})"
    )
    print(f"  [saved] {(RESULTS_DIR / f'{CACHE_KEY}.json').name}")
    return data


if __name__ == "__main__":
    run(force="--force" in sys.argv)
