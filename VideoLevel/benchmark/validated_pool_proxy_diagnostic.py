"""
validated_pool_proxy_diagnostic.py - Blind-sync proxy search for the SEC1 validated pool.

Goal:
  1. search operating-contract-derived blind candidates against the SEC1 validated pool
  2. use the best validated-pool proxy as a bridge to the SEC1 operating positions
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import OUTPUT_DIR, RESULTS_DIR, cache_load, cache_save, select_best_sec1_operating_asset
from src.blind_sync import BlindOperatingContract, derive_blind_positions_operating_contract

CACHE_KEY = "validated_pool_proxy_diagnostic"
SECRET_KEY = bytes(range(32))
SYNC_KEY = b"sec1_benchmark_chaos_v1"


def _load_positions(seq_name: str, suffix: str) -> list[tuple[int, int, int]]:
    path = OUTPUT_DIR / f"sec1_stego_{seq_name}.h264{suffix}"
    if not path.exists():
        return []
    return [tuple(int(v) for v in row) for row in json.loads(path.read_text(encoding="utf-8"))]


def collect_data(force: bool = False) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        print("  [cache hit] validated pool proxy diagnostic")
        return cached

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
        raise RuntimeError("No SEC1 operating asset available for validated-pool proxy diagnostic")

    validated_pool = _load_positions(seq_name, ".validated_pool.json")
    operating_positions = _load_positions(seq_name, ".positions.json")
    if not validated_pool or not operating_positions:
        raise RuntimeError(f"Missing SEC1 sidecars for {seq_name}")

    contracts = [
        BlindOperatingContract(signbit_only=False, bottom_rows=0, dedup_per_block=True, max_bits_per_idr=0, metadata_bound=False),
        BlindOperatingContract(signbit_only=False, bottom_rows=4, dedup_per_block=True, max_bits_per_idr=0, metadata_bound=False),
        BlindOperatingContract(signbit_only=False, bottom_rows=4, dedup_per_block=True, max_bits_per_idr=5, metadata_bound=False),
        BlindOperatingContract(signbit_only=True, bottom_rows=4, dedup_per_block=True, max_bits_per_idr=5, metadata_bound=False),
        BlindOperatingContract(signbit_only=True, bottom_rows=4, dedup_per_block=True, max_bits_per_idr=5, metadata_bound=True),
    ]

    rows = []
    for sync_name, sync_key in [("proof_key", SECRET_KEY), ("benchmark_sync_key", SYNC_KEY)]:
        for contract in contracts:
            proxy_positions, metadata = derive_blind_positions_operating_contract(
                video_path,
                sync_key,
                required_bits=len(validated_pool),
                contract=contract,
                cif_mb_count=396,
                use_analysis_cache=True,
            )
            validated_overlap = len(set(validated_pool) & set(proxy_positions))
            validated_prefix = sum(1 for a, b in zip(validated_pool, proxy_positions) if a == b)
            operating_prefix_positions = proxy_positions[: len(operating_positions)]
            operating_overlap = len(set(operating_positions) & set(operating_prefix_positions))
            operating_prefix = sum(1 for a, b in zip(operating_positions, operating_prefix_positions) if a == b)
            rows.append(
                {
                    "sync_name": sync_name,
                    "contract": contract.__dict__,
                    "validated_overlap": validated_overlap,
                    "validated_overlap_ratio": validated_overlap / max(1, len(validated_pool)),
                    "validated_prefix_match": validated_prefix,
                    "validated_prefix_match_ratio": validated_prefix / max(1, len(validated_pool)),
                    "operating_overlap": operating_overlap,
                    "operating_overlap_ratio": operating_overlap / max(1, len(operating_positions)),
                    "operating_prefix_match": operating_prefix,
                    "operating_prefix_match_ratio": operating_prefix / max(1, len(operating_positions)),
                    "metadata": metadata.__dict__,
                }
            )

    best_validated = max(rows, key=lambda row: (row["validated_overlap"], row["validated_prefix_match"]))

    data = {
        "sequence": seq_name,
        "video_path": video_path,
        "validated_pool_positions": len(validated_pool),
        "operating_positions": len(operating_positions),
        "best_validated_proxy": best_validated,
        "contract_grid": rows,
    }
    cache_save(CACHE_KEY, data)
    return data


def run(force: bool = False) -> dict:
    print("\n=== Validated Pool Proxy Diagnostic ===")
    data = collect_data(force=force)
    best = data["best_validated_proxy"]
    print(
        f"  [{data['sequence']}] validated_overlap={best['validated_overlap']}/{data['validated_pool_positions']} "
        f"({best['validated_overlap_ratio']:.3f}), operating_overlap={best['operating_overlap']}/{data['operating_positions']} "
        f"({best['operating_overlap_ratio']:.3f})"
    )
    print(f"  [saved] {(RESULTS_DIR / f'{CACHE_KEY}.json').name}")
    return data


if __name__ == "__main__":
    run(force="--force" in sys.argv)
