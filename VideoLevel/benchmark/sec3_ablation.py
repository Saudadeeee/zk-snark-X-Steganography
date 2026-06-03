"""
Section 3A - Internal Ablation Study
====================================

Measures how much the current benchmark-grade operating path gains from:
  1. locked operating-point positions
  2. quality-guarded operating-position locking
  3. round-robin operating-position distribution
  4. chaos-enabled payload path

This is an internal ablation benchmark intended to support paper discussion.
"""

import json
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import (
    OUTPUT_DIR,
    PALETTE,
    SEQUENCES,
    SEQ_LABELS,
    cache_load,
    cache_save,
    decode_luma_frames,
    load_or_build_benchmark_analysis,
    save_fig,
    setup_style,
    select_best_sec1_operating_asset,
    sort_positions_round_robin_idrs,
)

CACHE_KEY = "sec3_ablation_data"
SECRET_KEY = bytes(range(32))
CHAOS_KEY = b"sec1_benchmark_chaos_v1"
REAL_PROOF_MESSAGE = b"ZK-bench-v1.0!"


def _fast_mode_enabled() -> bool:
    return os.environ.get("SEC3A_FAST_MODE", "0") == "1"


def _load_positions(seq_name: str, suffix: str) -> list[tuple[int, int, int]]:
    path = OUTPUT_DIR / f"sec1_stego_{seq_name}.h264{suffix}"
    if not path.exists():
        return []
    return [tuple(int(v) for v in row) for row in json.loads(path.read_text(encoding="utf-8"))]


def collect_data(force: bool = False) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        print("  [cache hit] sec3 ablation")
        return cached

    from src.embedder import embed
    from src.exceptions import InsufficientCapacityError
    from benchmark.sec1_quality import _build_real_proof_payload
    from benchmark._common import psnr as _psnr

    required_bits = len(_build_real_proof_payload()[0]) * 8
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
        raise RuntimeError("No SEC1 operating asset available for ablation study")

    positions_locked = _load_positions(seq_name, ".positions.json")
    positions_validated = _load_positions(seq_name, ".validated_pool.json")
    if not positions_locked or not positions_validated:
        raise RuntimeError(f"Missing SEC1 sidecars for {seq_name}")
    positions_validated_naive = sorted(positions_validated)[: len(positions_locked)]
    _coeffs, _fvd, _nC, _nal, _t1, safe_positions = load_or_build_benchmark_analysis(
        video_path,
        force=force,
    )
    positions_raw_safe = sort_positions_round_robin_idrs(safe_positions)[: len(positions_locked)]

    data = {
        "sequence": seq_name,
        "video_path": video_path,
        "variants": {},
    }

    variants = [
        {
            "name": "locked_operating_point",
            "message": REAL_PROOF_MESSAGE,
            "chaos_key": CHAOS_KEY,
            "positions": positions_locked,
            "trust_positions": True,
        },
        {
            "name": "no_quality_guard",
            "message": REAL_PROOF_MESSAGE,
            "chaos_key": CHAOS_KEY,
            "positions": positions_validated[: len(positions_locked)],
            "trust_positions": False,
        },
        {
            "name": "no_round_robin",
            "message": REAL_PROOF_MESSAGE,
            "chaos_key": CHAOS_KEY,
            "positions": positions_validated_naive,
            "trust_positions": False,
        },
        {
            "name": "no_patchability_pruning",
            "message": REAL_PROOF_MESSAGE,
            "chaos_key": CHAOS_KEY,
            "positions": positions_raw_safe,
            "trust_positions": False,
        },
        {
            "name": "locked_no_chaos",
            "message": REAL_PROOF_MESSAGE,
            "chaos_key": None,
            "positions": positions_locked,
            "trust_positions": True,
        },
    ]

    max_frames = 120 if _fast_mode_enabled() else 300
    orig = decode_luma_frames(video_path, max_frames=max_frames)

    for variant in variants:
        out_path = OUTPUT_DIR / f"_sec3a_{seq_name}_{variant['name']}.h264"
        try:
            result = embed(
                video_path=video_path,
                message=variant["message"],
                output_path=str(out_path),
                circuits_dir="circuits",
                secret_key=SECRET_KEY,
                chaos_key=variant["chaos_key"],
                precomputed_positions=variant["positions"],
                trust_precomputed_positions=variant["trust_positions"],
                use_analysis_cache=True,
            )
            stego = decode_luma_frames(out_path, max_frames=max_frames)
            n = min(len(orig), len(stego))
            psnr_val = float(_psnr(orig[:n], stego[:n])) if n > 0 else 0.0
            data["variants"][variant["name"]] = {
                "success": True,
                "bits_embedded": int(result.bits_embedded),
                "positions_used": len(result.used_positions or []),
                "psnr_full_video": psnr_val,
                "raw_safe_bits": result.raw_safe_bits,
                "patchable_usable_bits": result.patchable_usable_bits,
                "ffmpeg_validated_bits": result.ffmpeg_validated_bits,
                "requested_position_bits": result.requested_position_bits,
                "applied_position_bits": result.applied_position_bits,
            }
        except InsufficientCapacityError as exc:
            data["variants"][variant["name"]] = {
                "success": False,
                "error": str(exc),
                "bits_embedded": 0,
                "positions_used": 0,
                "psnr_full_video": None,
                "raw_safe_bits": exc.context.get("raw_safe_bits"),
                "patchable_usable_bits": exc.context.get("patchable_usable_bits"),
                "ffmpeg_validated_bits": exc.context.get("ffmpeg_validated_bits"),
                "requested_position_bits": exc.context.get("requested_position_bits"),
                "applied_position_bits": exc.context.get("applied_position_bits"),
                "failure_stage": exc.context.get("stage"),
            }
        finally:
            for path in (
                out_path,
                Path(f"{out_path}.positions.json"),
                Path(f"{out_path}.meta.json"),
                Path(f"{out_path}.manifest.json"),
            ):
                if Path(path).exists():
                    Path(path).unlink()

    cache_save(CACHE_KEY, data)
    return data


def plot_ablation(data: dict) -> None:
    setup_style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5))

    variants = list(data["variants"].keys())
    labels = [v.replace("_", "\n") for v in variants]
    psnr_vals = [data["variants"][v]["psnr_full_video"] or 0.0 for v in variants]
    bits_vals = [data["variants"][v]["bits_embedded"] for v in variants]
    palette = [PALETTE["this_work"], PALETTE["mv"], PALETTE["lsb"], PALETTE["f5"], PALETTE["ipm"]]
    colors = [palette[i % len(palette)] for i in range(len(variants))]
    x = np.arange(len(variants))

    bars1 = ax1.bar(x, psnr_vals, color=colors, width=0.55, zorder=3)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=10)
    ax1.set_ylabel("Full-video PSNR (dB)")
    ax1.set_title("§3A  Ablation: Quality")
    for bar, val in zip(bars1, psnr_vals):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.2,
                 f"{val:.2f}", ha="center", va="bottom", fontsize=9, fontweight="bold")

    bars2 = ax2.bar(x, bits_vals, color=colors, width=0.55, zorder=3)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, fontsize=10)
    ax2.set_ylabel("Bits embedded")
    ax2.set_title("§3A  Ablation: Realized Payload")
    for bar, val in zip(bars2, bits_vals):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 8,
                 f"{val}", ha="center", va="bottom", fontsize=9, fontweight="bold")

    fig.suptitle(f"§3A  Internal Ablation Study ({SEQ_LABELS.get(data['sequence'], data['sequence'])})",
                 fontsize=13, fontweight="bold")
    save_fig(fig, "sec3_ablation")


def run(force: bool = False) -> dict:
    print("\n=== §3A  Internal Ablation Study ===")
    data = collect_data(force=force)
    plot_ablation(data)
    return data


if __name__ == "__main__":
    if "--fast" in sys.argv:
        os.environ["SEC3A_FAST_MODE"] = "1"
    run(force="--force" in sys.argv)
