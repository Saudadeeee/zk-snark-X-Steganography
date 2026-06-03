"""
public_api_realization.py - Measure broad public-API realization without locked positions.

Reports how far the generic embed() path can realize the standard payload on
selected assets without precomputed operating positions.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import RESULTS_DIR, SEQUENCES, cache_load, cache_save
from src.embedder import embed
from src.exceptions import InsufficientCapacityError

CACHE_KEY = "public_api_realization"
SECRET_KEY = b"zk_mv_stego_2026_secret_key!!!!!"
MESSAGE = b"Hello ZK-Stego"


def collect_data(force: bool = False) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        print("  [cache hit] public api realization")
        return cached

    data = {}
    candidates = [
        "coastguard_q22_g1",
        "deadline_q22_g1",
        "coastguard_q22_g1_1000f",
        "foreman_q22_g1",
    ]
    for seq_name in candidates:
        video_path = SEQUENCES.get(seq_name)
        if video_path is None or not Path(video_path).exists():
            continue
        out_path = Path("data/output") / f"_public_api_{seq_name}.h264"
        try:
            result = embed(
                video_path=str(video_path),
                message=MESSAGE,
                output_path=str(out_path),
                circuits_dir="circuits",
                secret_key=SECRET_KEY,
                use_analysis_cache=True,
            )
            data[seq_name] = {
                "success": True,
                "stream_class": result.stream_class,
                "bits_embedded": result.bits_embedded,
                "raw_safe_bits": result.raw_safe_bits,
                "patchable_usable_bits": result.patchable_usable_bits,
                "requested_position_bits": result.requested_position_bits,
                "applied_position_bits": result.applied_position_bits,
            }
        except InsufficientCapacityError as exc:
            data[seq_name] = {
                "success": False,
                "error": str(exc),
                "failure_stage": exc.context.get("stage"),
                "stream_class": None,
                "raw_safe_bits": exc.context.get("raw_safe_bits"),
                "patchable_usable_bits": exc.context.get("patchable_usable_bits"),
                "requested_position_bits": exc.context.get("requested_position_bits"),
                "applied_position_bits": exc.context.get("applied_position_bits"),
            }
        finally:
            for path in (
                out_path,
                Path(f"{out_path}.positions.json"),
                Path(f"{out_path}.meta.json"),
                Path(f"{out_path}.manifest.json"),
            ):
                if path.exists():
                    path.unlink()

    cache_save(CACHE_KEY, data)
    return data


def run(force: bool = False) -> dict:
    print("\n=== Public API Realization Diagnostic ===")
    data = collect_data(force=force)
    for seq, row in data.items():
        if row.get("success"):
            print(f"  [{seq}] success bits={row['bits_embedded']}")
        else:
            print(
                f"  [{seq}] fail stage={row.get('failure_stage')} "
                f"requested={row.get('requested_position_bits')} applied={row.get('applied_position_bits')}"
            )
    print(f"  [saved] {(RESULTS_DIR / f'{CACHE_KEY}.json').name}")
    return data


if __name__ == "__main__":
    run(force="--force" in sys.argv)
