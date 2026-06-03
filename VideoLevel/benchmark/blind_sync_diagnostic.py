"""
blind_sync_diagnostic.py - Evaluate metadata-derived blind synchronization.

Measures how much the blind-derived position ordering overlaps with the current
locked SEC1 operating positions on available assets.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import (
    OUTPUT_DIR,
    RESULTS_DIR,
    SEQUENCES,
    cache_load,
    cache_save,
    select_best_sec1_operating_asset,
)
from src.blind_sync import (
    BlindOperatingContract,
    derive_blind_positions,
    derive_blind_positions_chaos_dedup,
    derive_blind_positions_operating_contract,
    derive_blind_positions_operating_like,
    derive_blind_positions_operating_signbit_like,
)

CACHE_KEY = "blind_sync_diagnostic"
SECRET_KEY = bytes(range(32))
REAL_PROOF_MESSAGE = b"ZK-bench-v1.0!"
SYNC_KEY = b"sec1_benchmark_chaos_v1"


def _load_positions(seq_name: str) -> list[tuple[int, int, int]]:
    path = OUTPUT_DIR / f"sec1_stego_{seq_name}.h264.positions.json"
    if not path.exists():
        return []
    return [tuple(int(v) for v in row) for row in json.loads(path.read_text(encoding="utf-8"))]


def _load_validated_pool(seq_name: str) -> list[tuple[int, int, int]]:
    path = OUTPUT_DIR / f"sec1_stego_{seq_name}.h264.validated_pool.json"
    if not path.exists():
        return []
    return [tuple(int(v) for v in row) for row in json.loads(path.read_text(encoding="utf-8"))]


def collect_data(force: bool = False) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        print("  [cache hit] blind sync diagnostic")
        return cached

    required_bits = (4 + len(REAL_PROOF_MESSAGE) + 129) * 8
    seq_name, video_path = select_best_sec1_operating_asset(
        required_bits=required_bits,
        preferred_sequences=[
            "coastguard_q22_g1",
            "deadline_q22_g1",
            "coastguard_q22_g1_1000f",
            "foreman_q22_g1",
        ],
    )
    if not seq_name or not video_path:
        raise RuntimeError("No SEC1 operating asset available for blind sync diagnostic")

    operating_positions = _load_positions(seq_name)
    if not operating_positions:
        raise RuntimeError(f"Missing SEC1 operating positions for {seq_name}")
    validated_pool = _load_validated_pool(seq_name)

    blind_positions, metadata = derive_blind_positions(
        video_path,
        SECRET_KEY,
        required_bits=len(operating_positions),
        use_analysis_cache=True,
    )
    chaos_positions, chaos_metadata = derive_blind_positions_chaos_dedup(
        video_path,
        SECRET_KEY,
        required_bits=len(operating_positions),
        metadata_bound=False,
        use_analysis_cache=True,
    )
    chaos_bound_positions, chaos_bound_metadata = derive_blind_positions_chaos_dedup(
        video_path,
        SECRET_KEY,
        required_bits=len(operating_positions),
        metadata_bound=True,
        use_analysis_cache=True,
    )
    operating_like_positions, operating_like_metadata = derive_blind_positions_operating_like(
        video_path,
        SECRET_KEY,
        required_bits=len(operating_positions),
        cif_mb_count=396,
        max_bits_per_idr=5,
        metadata_bound=False,
        use_analysis_cache=True,
    )
    operating_signbit_positions, operating_signbit_metadata = derive_blind_positions_operating_signbit_like(
        video_path,
        SECRET_KEY,
        required_bits=len(operating_positions),
        cif_mb_count=396,
        max_bits_per_idr=5,
        bottom_rows=4,
        metadata_bound=False,
        use_analysis_cache=True,
    )
    contracts = [
        BlindOperatingContract(signbit_only=False, bottom_rows=0, dedup_per_block=True, max_bits_per_idr=5, metadata_bound=False),
        BlindOperatingContract(signbit_only=False, bottom_rows=4, dedup_per_block=True, max_bits_per_idr=5, metadata_bound=False),
        BlindOperatingContract(signbit_only=True, bottom_rows=4, dedup_per_block=True, max_bits_per_idr=5, metadata_bound=False),
        BlindOperatingContract(signbit_only=True, bottom_rows=4, dedup_per_block=True, max_bits_per_idr=2, metadata_bound=False),
        BlindOperatingContract(signbit_only=True, bottom_rows=0, dedup_per_block=True, max_bits_per_idr=5, metadata_bound=False),
        BlindOperatingContract(signbit_only=True, bottom_rows=4, dedup_per_block=True, max_bits_per_idr=5, metadata_bound=True),
    ]
    contract_results = []
    for sync_name, sync_key in [("proof_key", SECRET_KEY), ("benchmark_sync_key", SYNC_KEY)]:
        for contract in contracts:
            contract_positions, _contract_metadata = derive_blind_positions_operating_contract(
                video_path,
                sync_key,
                required_bits=len(operating_positions),
                contract=contract,
                cif_mb_count=396,
                use_analysis_cache=True,
            )
            c_overlap = len(set(operating_positions) & set(contract_positions))
            c_prefix = sum(1 for a, b in zip(operating_positions, contract_positions) if a == b)
            contract_results.append(
                {
                    "sync_name": sync_name,
                    "contract": contract.__dict__,
                    "set_overlap": c_overlap,
                    "set_overlap_ratio": c_overlap / max(1, len(operating_positions)),
                    "prefix_match": c_prefix,
                    "prefix_match_ratio": c_prefix / max(1, len(operating_positions)),
                    "validated_pool_overlap": len(set(validated_pool) & set(contract_positions)) if validated_pool else None,
                    "validated_pool_overlap_ratio": (
                        len(set(validated_pool) & set(contract_positions)) / max(1, len(validated_pool))
                        if validated_pool else None
                    ),
                }
            )
    best_contract = max(contract_results, key=lambda row: (row["set_overlap"], row["prefix_match"]))

    overlap = len(set(operating_positions) & set(blind_positions))
    prefix_match = sum(1 for a, b in zip(operating_positions, blind_positions) if a == b)
    chaos_overlap = len(set(operating_positions) & set(chaos_positions))
    chaos_prefix = sum(1 for a, b in zip(operating_positions, chaos_positions) if a == b)
    chaos_bound_overlap = len(set(operating_positions) & set(chaos_bound_positions))
    chaos_bound_prefix = sum(1 for a, b in zip(operating_positions, chaos_bound_positions) if a == b)
    operating_like_overlap = len(set(operating_positions) & set(operating_like_positions))
    operating_like_prefix = sum(1 for a, b in zip(operating_positions, operating_like_positions) if a == b)
    operating_signbit_overlap = len(set(operating_positions) & set(operating_signbit_positions))
    operating_signbit_prefix = sum(1 for a, b in zip(operating_positions, operating_signbit_positions) if a == b)

    data = {
        "sequence": seq_name,
        "video_path": video_path,
        "required_bits": len(operating_positions),
        "operating_positions": len(operating_positions),
        "validated_pool_positions": len(validated_pool),
        "blind_positions": len(blind_positions),
        "set_overlap": overlap,
        "set_overlap_ratio": overlap / max(1, len(operating_positions)),
        "prefix_match": prefix_match,
        "prefix_match_ratio": prefix_match / max(1, len(operating_positions)),
        "chaos_dedup_overlap": chaos_overlap,
        "chaos_dedup_overlap_ratio": chaos_overlap / max(1, len(operating_positions)),
        "chaos_dedup_prefix_match": chaos_prefix,
        "chaos_dedup_prefix_match_ratio": chaos_prefix / max(1, len(operating_positions)),
        "chaos_bound_overlap": chaos_bound_overlap,
        "chaos_bound_overlap_ratio": chaos_bound_overlap / max(1, len(operating_positions)),
        "chaos_bound_prefix_match": chaos_bound_prefix,
        "chaos_bound_prefix_match_ratio": chaos_bound_prefix / max(1, len(operating_positions)),
        "operating_like_overlap": operating_like_overlap,
        "operating_like_overlap_ratio": operating_like_overlap / max(1, len(operating_positions)),
        "operating_like_prefix_match": operating_like_prefix,
        "operating_like_prefix_match_ratio": operating_like_prefix / max(1, len(operating_positions)),
        "operating_signbit_overlap": operating_signbit_overlap,
        "operating_signbit_overlap_ratio": operating_signbit_overlap / max(1, len(operating_positions)),
        "operating_signbit_prefix_match": operating_signbit_prefix,
        "operating_signbit_prefix_match_ratio": operating_signbit_prefix / max(1, len(operating_positions)),
        "contract_grid": contract_results,
        "best_contract": best_contract,
        "metadata": metadata.__dict__,
        "chaos_metadata": chaos_metadata.__dict__,
        "chaos_bound_metadata": chaos_bound_metadata.__dict__,
        "operating_like_metadata": operating_like_metadata.__dict__,
        "operating_signbit_metadata": operating_signbit_metadata.__dict__,
    }
    cache_save(CACHE_KEY, data)
    return data


def run(force: bool = False) -> dict:
    print("\n=== Blind Synchronization Diagnostic ===")
    data = collect_data(force=force)
    print(
        f"  [{data['sequence']}] stable_overlap={data['set_overlap']}/{data['operating_positions']} "
        f"({data['set_overlap_ratio']:.3f}), chaos_overlap={data['chaos_dedup_overlap']}/{data['operating_positions']} "
        f"({data['chaos_dedup_overlap_ratio']:.3f}), chaos_bound_overlap={data['chaos_bound_overlap']}/{data['operating_positions']} "
        f"({data['chaos_bound_overlap_ratio']:.3f}), operating_like_overlap={data['operating_like_overlap']}/{data['operating_positions']} "
        f"({data['operating_like_overlap_ratio']:.3f}), signbit_overlap={data['operating_signbit_overlap']}/{data['operating_positions']} "
        f"({data['operating_signbit_overlap_ratio']:.3f}), best_contract_overlap={data['best_contract']['set_overlap']}/{data['operating_positions']} "
        f"({data['best_contract']['set_overlap_ratio']:.3f})"
    )
    print(f"  [saved] {(RESULTS_DIR / f'{CACHE_KEY}.json').name}")
    return data


if __name__ == "__main__":
    run(force="--force" in sys.argv)
