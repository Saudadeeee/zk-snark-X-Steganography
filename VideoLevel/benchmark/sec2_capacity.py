"""
Section 2 — Embedding Capacity & PSNR vs Payload Size
======================================================
Answers: "How much data can we embed while maintaining quality?"

Methodology:
  1. Raw safe-position capacity: all CAVLC-safe candidate positions before
     SEC1 operating-point quality pruning.
  2. Patchable usable capacity: positions surviving the public API patchability
     flow before SEC1 quality validation.
  3. Quality-constrained capacity: positions surviving SEC1 validation
     (FFmpeg hard-error filter + PSNR validation).
  4. Operating-point capacity: exact positions used by the SEC1 operating point.
  5. PSNR vs bits embedded: embed increasing fractions of the validated
     positions (25 / 50 / 75 / 100 %) and measure full-video PSNR.
     No additional FFmpeg validation needed — positions are pre-verified.

Produces:
  - sec2_psnr_vs_bits.png      : PSNR vs bits embedded (validated positions)
  - sec2_capacity_budget.png   : Capacity chart (raw safe / patchable / validated / operating / payload)
  - sec2_capacity_bar.png      : Raw safe-position capacity per sequence (bits + bytes)
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import (
    PALETTE, SEQUENCES, SEQ_LABELS,
    setup_style, save_fig, cache_save, cache_load,
    decode_luma_frames,
    OUTPUT_DIR, get_capacity_views, load_or_build_benchmark_analysis,
)

CACHE_KEY   = "sec2_capacity_data"
CIF_MB_COUNT = 396

# Fractions of validated positions to test (in %)
VALIDATED_FRACTIONS = [25, 50, 75, 100]

# Packed blob size before chaos. SEC2 operating point is driven by the
# chaos-expanded payload imported from SEC1 at runtime.
ZK_PAYLOAD_BYTES    = 147
ZK_PAYLOAD_BITS     = ZK_PAYLOAD_BYTES * 8   # 1176 packed bits before chaos


def _fast_mode_enabled() -> bool:
    return os.environ.get("SEC2_FAST_MODE", "0") == "1"


def _sec2_cache_meta(sweep_seqs: list[str]) -> dict[str, object]:
    return {
        "sequence_names": list(sweep_seqs),
        "positions_mtimes": {
            seq: (OUTPUT_DIR / f"sec1_stego_{seq}.h264.positions.json").stat().st_mtime
            if (OUTPUT_DIR / f"sec1_stego_{seq}.h264.positions.json").exists() else None
            for seq in sweep_seqs
        },
    }


# ---------------------------------------------------------------------------
# Fast PSNR sweep over pre-validated positions
# ---------------------------------------------------------------------------
def _sweep_validated_psnr(
    seq_name: str,
    video_path: Path,
    positions_path: Path,
    fractions: list[int],
    payload_scrambled: bytes,
) -> dict:
    """
    Embed at different fractions of the already-validated positions and
    measure full-video PSNR.  No re-validation — positions are trusted.
    """
    from src.core.stego import PayloadEmbedder
    from src.bitstream.bitstream_ops import BitstreamReconstructor
    from benchmark._common import psnr as _psnr

    all_positions = json.loads(positions_path.read_text())
    # positions.json stores [mb, blk, cidx] triples
    all_positions = [tuple(p) for p in all_positions]
    total_valid   = len(all_positions)

    decode_max_frames = 180 if _fast_mode_enabled() else 9999
    print(f"  [{seq_name}] {total_valid} validated positions -> sweep {fractions}%")
    coeffs, fvd, nC_map, nal_len, t1_over, _safe_positions = load_or_build_benchmark_analysis(
        video_path
    )

    orig_frames = decode_luma_frames(video_path, max_frames=decode_max_frames)

    results_bits: list[int]   = []
    results_psnr: list[float] = []

    for frac in fractions:
        n_pos   = max(1, int(total_valid * frac / 100))
        sel_pos = all_positions[:n_pos]
        n_bytes = n_pos // 8
        # Use a fixed repeating payload (same content at every fraction)
        payload_slice = (payload_scrambled * ((n_bytes // len(payload_scrambled)) + 2))[:n_bytes]

        out_path = OUTPUT_DIR / f"_sec2_{seq_name}_v{frac}.h264"
        t0 = time.perf_counter()

        embedder = PayloadEmbedder(max_modifications_per_block=1)
        modified, bits_emb = embedder.embed_payload(
            coeffs, payload_slice,
            nC_map=nC_map, nal_length_map=nal_len, t1_override_map=t1_over,
            pre_validated_positions=sel_pos,
        )

        rec2 = BitstreamReconstructor()
        rec2.reconstruct_video(
            str(video_path), modified, str(out_path),
            max_slices=None, frame_verified_data=fvd,
        )

        stego_frames = decode_luma_frames(out_path, max_frames=decode_max_frames)
        n = min(len(orig_frames), len(stego_frames))
        psnr_val = float(_psnr(orig_frames[:n], stego_frames[:n])) if n > 0 else 0.0

        results_bits.append(bits_emb)
        results_psnr.append(psnr_val)
        print(f"  [{seq_name}] {frac}% -> {bits_emb} bits, PSNR={psnr_val:.2f} dB  "
              f"({time.perf_counter()-t0:.1f}s)")

    return {
        "validated_positions": total_valid,
        "fractions_pct":       fractions,
        "bits_at_fraction":    results_bits,
        "psnr_at_fraction":    results_psnr,
    }


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------
def collect_data(force: bool = False, include_sequences: set[str] | None = None) -> dict:
    default_sweep = [
        "akiyo_q22_g1",
        "hall_monitor_q22_g1",
        "foreman_q22_g1",
        "container_q22_g1",
        "city_q22_g1",
        "coastguard_q22_g1",
        "football_q22_g1",
        "deadline_q22_g1",
        "coastguard_q22_g1_1000f",
        "deadline_q22_g1_1000f",
        "coastguard_q22_g1_3000f",
    ]
    if _fast_mode_enabled():
        default_sweep = [
            "coastguard_q22_g1",
            "deadline_q22_g1",
        ]
    sweep_seqs = default_sweep
    if include_sequences:
        sweep_seqs = [seq for seq in default_sweep if seq in include_sequences]
        extras = [seq for seq in include_sequences if seq not in sweep_seqs]
        sweep_seqs.extend(extras)

    cache_meta = _sec2_cache_meta(sweep_seqs)
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        if isinstance(cached, dict) and "__meta__" in cached and "data" in cached:
            if cached["__meta__"] == cache_meta:
                print("  [cache hit] sec2 — skipping capacity sweep")
                return cached["data"]

    # Reuse the exact SEC1 operating payload: real proof blob + same chaos key.
    from benchmark.sec1_quality import _build_real_proof_payload, CHAOS_KEY
    from src.core.chaos import ChaosTransformer

    payload_real, _ = _build_real_proof_payload()
    payload_scrambled, _ = ChaosTransformer(CHAOS_KEY).scramble(payload_real)
    zk_blob_bits = len(payload_scrambled) * 8
    fractions = [25, 100] if _fast_mode_enabled() else VALIDATED_FRACTIONS

    data: dict = {}

    import os as _os
    _os.environ["BENCHMARK_TRUSTED_IDR_PICKLE_CACHE"] = "1"

    for seq_name in sweep_seqs:
        video_path = SEQUENCES.get(seq_name)
        if not video_path or not video_path.exists():
            print(f"  [{seq_name}] video not found — skip")
            continue

        positions_path = OUTPUT_DIR / f"sec1_stego_{seq_name}.h264.positions.json"
        if not positions_path.exists():
            print(f"  [{seq_name}] positions.json not found (run sec1 first) — skip")
            continue

        caps = get_capacity_views(seq_name, video_path, force=force)
        raw_capacity = int(caps["raw_safe_bits"])
        patchable_cap = int(caps["patchable_usable_bits"] or 0)
        validated_cap = int(caps["validated_pool_bits"] or 0)
        operating_cap = int(caps["operating_bits"] or 0)
        print(f"\n  [{seq_name}] raw safe positions = {raw_capacity:,} bits")
        if patchable_cap:
            print(f"  [{seq_name}] patchable usable    = {patchable_cap:,} bits")
        if validated_cap:
            print(f"  [{seq_name}] validated pool      = {validated_cap:,} bits")
        if operating_cap:
            print(f"  [{seq_name}] operating positions = {operating_cap:,} bits")

        sweep = _sweep_validated_psnr(
            seq_name, video_path, positions_path,
            fractions, payload_scrambled,
        )

        data[seq_name] = {
            "raw_safe_bits":         raw_capacity,
            "raw_safe_bytes":        raw_capacity // 8,
            "patchable_usable_bits": patchable_cap or None,
            "validated_pool_bits":   validated_cap or sweep["validated_positions"],
            "operating_bits":        operating_cap or None,
            "ffmpeg_validated_bits": caps.get("ffmpeg_validated_bits"),
            "requested_position_bits": caps.get("requested_position_bits"),
            "applied_position_bits": caps.get("applied_position_bits"),
            "validation_mode":       caps.get("validation_mode"),
            "zk_blob_bits":          zk_blob_bits,
            "zk_payload_bits":       ZK_PAYLOAD_BITS,
            "utilization_pct":       round(100.0 * zk_blob_bits / raw_capacity, 3),
            "fractions_pct":         sweep["fractions_pct"],
            "bits_at_fraction":      sweep["bits_at_fraction"],
            "psnr_at_fraction":      sweep["psnr_at_fraction"],
        }

    cache_save(CACHE_KEY, {"__meta__": cache_meta, "data": data})
    return data


# ---------------------------------------------------------------------------
# Plot 1: PSNR vs bits embedded (validated fractions)
# ---------------------------------------------------------------------------
def plot_psnr_vs_bits(data: dict) -> None:
    setup_style()
    fig, ax = plt.subplots(figsize=(9, 5))

    colors = list(PALETTE.values())
    for i, (seq, d) in enumerate(data.items()):
        if not d.get("bits_at_fraction"):
            continue
        label = SEQ_LABELS.get(seq, seq).split(" (")[0]
        ax.plot(
            d["bits_at_fraction"], d["psnr_at_fraction"],
            color=colors[i % len(colors)],
            linewidth=2.2, label=label,
        )
        # Annotate 100% point (actual operating point)
        x100 = d["bits_at_fraction"][-1]
        y100 = d["psnr_at_fraction"][-1]
        ax.annotate(
            f"{y100:.1f} dB",
            xy=(x100, y100), xytext=(x100 + 30, y100 - 1.5),
            fontsize=9, color=colors[i % len(colors)], fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=colors[i % len(colors)], lw=1.2),
        )

    ax.axvline(ZK_PAYLOAD_BITS, color="#888888", linestyle="--", linewidth=1.5,
               label=f"ZK payload ({ZK_PAYLOAD_BITS} bits = {ZK_PAYLOAD_BYTES} B)")
    ax.axhline(40.0, color="#C62828", linestyle=":", linewidth=1.2,
               label="40 dB imperceptible threshold")

    ax.set_xlabel("Bits embedded (quality-constrained validated positions)")
    ax.set_ylabel("Full-video PSNR (dB)")
    ax.set_title("§2  PSNR vs Bits Embedded\n"
                 "(validated positions: FFmpeg hard-error + PSNR ≥ 40 dB per frame)")
    ax.legend(fontsize=9)
    ax.set_xlim(0, max(
        max(d["bits_at_fraction"][-1] for d in data.values() if d.get("bits_at_fraction")),
        ZK_PAYLOAD_BITS,
    ) * 1.15)

    save_fig(fig, "sec2_psnr_vs_bits")


# ---------------------------------------------------------------------------
# Plot 2: Three-tier capacity budget (log scale)
# ---------------------------------------------------------------------------
def plot_capacity_budget(data: dict) -> None:
    setup_style()
    fig, ax = plt.subplots(figsize=(10, 6))

    seqs   = list(data.keys())
    labels = [SEQ_LABELS.get(s, s).split(" (")[0] for s in seqs]
    n      = len(seqs)
    x      = np.arange(n)
    w      = 0.22

    raw_bits       = [data[s]["raw_safe_bits"]  for s in seqs]
    patchable_bits = [data[s].get("patchable_usable_bits") or data[s]["raw_safe_bits"] for s in seqs]
    validated_pool_bits = [
        data[s].get("validated_pool_bits")
        if "validated_pool_bits" in data[s]
        else data[s].get("validated_bits")
        for s in seqs
    ]
    operating_bits = [
        data[s].get("operating_bits")
        if "operating_bits" in data[s] and data[s].get("operating_bits") is not None
        else (
            data[s].get("validated_pool_bits")
            if "validated_pool_bits" in data[s]
            else data[s].get("validated_bits")
        )
        for s in seqs
    ]
    zk_blob_bits = data[seqs[0]]["zk_blob_bits"] if seqs else 0
    zk_bits        = [zk_blob_bits] * n

    ax.bar(x - 2.0 * w, raw_bits,       width=w, color=PALETTE["this_work"],
           alpha=0.80, label="Raw safe positions", zorder=3)
    ax.bar(x - 1.0 * w, patchable_bits, width=w, color=PALETTE["bulletproof"],
           alpha=0.85, label="Patchable usable positions", zorder=3)
    ax.bar(x + 0.0 * w, validated_pool_bits, width=w, color=PALETTE["f5"],
           alpha=0.85, label="Validated pool", zorder=3)
    ax.bar(x + 1.0 * w, operating_bits, width=w, color=PALETTE["mv"],
           alpha=0.85, label="SEC1 operating positions", zorder=3)
    ax.bar(x + 2.0 * w, zk_bits,        width=w, color=PALETTE["lsb"],
           alpha=0.85, label=f"ZK blob payload ({zk_blob_bits} bits)", zorder=3)

    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("Bits (log scale)")
    ax.set_title("§2  Embedding Capacity Budget\n"
                 "(raw safe vs patchable vs validated vs operating vs ZK payload)")
    ax.legend(fontsize=9)

    # Annotate utilization rate
    for i, s in enumerate(seqs):
        util = data[s]["utilization_pct"]
        ax.text(x[i] - 2.0 * w, raw_bits[i] * 1.3,
                f"{util:.2f}%\nof raw",
                ha="center", va="bottom", fontsize=8.5,
                color=PALETTE["this_work"], fontweight="bold")
        ax.text(x[i] - 1.0 * w, patchable_bits[i] * 1.3,
                f"{patchable_bits[i]:,}",
                ha="center", va="bottom", fontsize=8.5,
                color=PALETTE["bulletproof"], fontweight="bold")
        ax.text(x[i] + 0.0 * w, validated_pool_bits[i] * 1.3,
                f"{validated_pool_bits[i]:,}",
                ha="center", va="bottom", fontsize=8.5,
                color=PALETTE["f5"], fontweight="bold")
        ax.text(x[i] + 1.0 * w, operating_bits[i] * 1.3,
                f"{operating_bits[i]:,}",
                ha="center", va="bottom", fontsize=8.5,
                color=PALETTE["mv"], fontweight="bold")

    save_fig(fig, "sec2_capacity_budget")


# ---------------------------------------------------------------------------
# Plot 3: Raw T1 capacity bar (bits + bytes, all sequences)
# ---------------------------------------------------------------------------
def plot_capacity_bar(data: dict) -> None:
    setup_style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5))

    seqs   = list(data.keys())
    labels = [SEQ_LABELS.get(s, s).split(" (")[0] for s in seqs]
    cap_bits  = [data[s]["raw_safe_bits"]  for s in seqs]
    cap_bytes = [data[s]["raw_safe_bytes"] for s in seqs]
    colors    = [list(PALETTE.values())[i % len(PALETTE)] for i in range(len(seqs))]

    x = np.arange(len(seqs))

    bars1 = ax1.bar(x, cap_bits, color=colors, width=0.5, zorder=3)
    ax1.set_xticks(x); ax1.set_xticklabels(labels, fontsize=10)
    ax1.set_ylabel("Raw safe-position bits available")
    ax1.set_title("§2  Raw Safe-Position Capacity (bits)")
    for bar, val in zip(bars1, cap_bits):
        ax1.text(bar.get_x() + bar.get_width() / 2,
                 bar.get_height() * 1.02,
                 f"{val:,}", ha="center", va="bottom",
                 fontsize=10, fontweight="bold")

    bars2 = ax2.bar(x, cap_bytes, color=colors, width=0.5, zorder=3)
    ax2.set_xticks(x); ax2.set_xticklabels(labels, fontsize=10)
    ax2.set_ylabel("Capacity (bytes)")
    ax2.set_title("§2  Raw Safe-Position Capacity (bytes)")
    for bar, val in zip(bars2, cap_bytes):
        ax2.text(bar.get_x() + bar.get_width() / 2,
                 bar.get_height() * 1.02,
                 f"{val:,} B", ha="center", va="bottom",
                 fontsize=10, fontweight="bold")

    ax2.axhline(ZK_PAYLOAD_BYTES, color="#C62828", linestyle="--",
                linewidth=1.5, label=f"ZK payload ({ZK_PAYLOAD_BYTES} B)")
    ax2.legend(fontsize=9)

    save_fig(fig, "sec2_capacity_bar")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run(force: bool = False, include_sequences: set[str] | None = None) -> dict:
    print("\n=== §2  Capacity & PSNR vs Payload Size ===")
    data = collect_data(force=force, include_sequences=include_sequences)
    if not data:
        print("  [skip] no SEC1 sidecars available for the requested sequences")
        return {}
    plot_psnr_vs_bits(data)
    plot_capacity_budget(data)
    plot_capacity_bar(data)
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run sec2 capacity benchmark")
    parser.add_argument("--force", action="store_true", help="Ignore cache and recompute")
    parser.add_argument(
        "--sequences",
        type=str,
        default="",
        help="Comma-separated sequence names to run (e.g. foreman_q22_g1,deadline_q22_g1)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Developer fast mode: reduced sweep fractions and shorter decode window",
    )
    args = parser.parse_args()
    if args.fast:
        os.environ["SEC2_FAST_MODE"] = "1"
    selected = {s.strip() for s in args.sequences.split(",") if s.strip()} or None
    run(force=args.force, include_sequences=selected)
