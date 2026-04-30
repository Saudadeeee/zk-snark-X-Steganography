"""
Section 8 - Warm-Cache Application Latency
==========================================

Measures the practical application path after all cover-video caches are warm:
  - cover analysis cache
  - reconstruction context cache
  - ZK bridge instance cache

This is the closest benchmark to the current app/runtime behavior without
re-running the full cold pipeline each time.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import RESULTS_DIR, SEQUENCES, OUTPUT_DIR, cache_load, cache_save
from src.core.analysis_cache import (
    load_or_build_reconstruction_context,
    load_or_build_video_analysis,
)
from src.embedder import embed
from src.verifier import verify


CACHE_KEY = "sec8_realtime_data"
SECRET_KEY = bytes(range(32))
CHAOS_KEY = b"sec8_realtime_chaos_v1"
MESSAGE = b"ZK realtime benchmark"


def _default_sequences() -> list[str]:
    return ["foreman_q22_g1", "coastguard_q22_g1"]


def _prime_runtime_caches(video_path: Path) -> None:
    load_or_build_video_analysis(str(video_path), use_cache=True, force_refresh=False)
    load_or_build_reconstruction_context(str(video_path), use_cache=True, force_refresh=False)


def _measure_warm(seq_name: str, video_path: Path, runs: int) -> dict:
    out_path = OUTPUT_DIR / f"_sec8_{seq_name}_stego.h264"

    # Prime caches once so measured runs reflect warm-cache app latency.
    _prime_runtime_caches(video_path)

    embed_times = []
    verify_times = []

    for _ in range(runs):
        t0 = time.perf_counter()
        embed_result = embed(
            video_path=str(video_path),
            message=MESSAGE,
            output_path=str(out_path),
            circuits_dir="circuits",
            secret_key=SECRET_KEY,
            chaos_key=CHAOS_KEY,
            use_analysis_cache=True,
        )
        t1 = time.perf_counter()
        verify_result = verify(
            stego_video_path=str(out_path),
            original_video_path=str(video_path),
            circuits_dir="circuits",
            secret_key=SECRET_KEY,
            message_length=len(MESSAGE),
            chaos_key=CHAOS_KEY,
            use_analysis_cache=True,
        )
        t2 = time.perf_counter()

        if not verify_result.valid:
            raise RuntimeError(f"{seq_name}: warm-cache verify failed")

        embed_times.append(t1 - t0)
        verify_times.append(t2 - t1)

    return {
        "runs": runs,
        "message_bytes": len(MESSAGE),
        "embed_bits": embed_result.bits_embedded,
        "embed_s": [round(v, 4) for v in embed_times],
        "verify_s": [round(v, 4) for v in verify_times],
        "embed_mean_s": round(sum(embed_times) / len(embed_times), 4),
        "verify_mean_s": round(sum(verify_times) / len(verify_times), 4),
        "end_to_end_mean_s": round((sum(embed_times) + sum(verify_times)) / len(embed_times), 4),
    }


def collect_data(force: bool = False, sequences: list[str] | None = None, runs: int = 1) -> dict:
    cache_meta = {"sequences": sequences or _default_sequences(), "runs": int(runs)}
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        if isinstance(cached, dict) and "__meta__" in cached and "data" in cached:
            if cached["__meta__"] == cache_meta:
                print("  [cache hit] sec8 - skipping warm-cache latency runs")
                return cached["data"]

    data = {}
    for seq_name in sequences or _default_sequences():
        video_path = SEQUENCES.get(seq_name)
        if not video_path or not video_path.exists():
            print(f"  [{seq_name}] video not found - skip")
            continue
        print(f"  [{seq_name}] measuring warm-cache latency ({runs} run) ...")
        data[seq_name] = _measure_warm(seq_name, video_path, runs)
        print(
            f"  [{seq_name}] embed={data[seq_name]['embed_mean_s']:.2f}s  "
            f"verify={data[seq_name]['verify_mean_s']:.2f}s  "
            f"end-to-end={data[seq_name]['end_to_end_mean_s']:.2f}s"
        )

    cache_save(CACHE_KEY, {"__meta__": cache_meta, "data": data})
    return data


def run(force: bool = False, sequences: list[str] | None = None, runs: int = 1) -> dict:
    print("\n=== §8  Warm-Cache Application Latency ===")
    data = collect_data(force=force, sequences=sequences, runs=runs)
    out = RESULTS_DIR / "sec8_realtime_data.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"data": data}, f, ensure_ascii=True, indent=2)
    print(f"  [saved] {out.name}")
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run sec8 warm-cache application latency benchmark")
    parser.add_argument("--force", action="store_true", help="Ignore cache and recompute")
    parser.add_argument("--runs", type=int, default=1, help="Number of warm runs per sequence")
    parser.add_argument(
        "--sequences",
        type=str,
        default="",
        help="Comma-separated sequence names to run",
    )
    args = parser.parse_args()
    selected = [s.strip() for s in args.sequences.split(",") if s.strip()] or None
    run(force=args.force, sequences=selected, runs=max(1, args.runs))
