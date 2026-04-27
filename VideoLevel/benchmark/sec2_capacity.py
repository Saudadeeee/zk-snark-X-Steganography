"""
Section 2 — Embedding Capacity & PSNR vs Payload Size
======================================================
Answers: "How much data can we embed while maintaining quality?"

Methodology:
  1. Raw T1 capacity: total CAVLC T1 sign positions in the video.
  2. Quality-constrained capacity: positions surviving per-position FFmpeg
     hard-error filter + batch PSNR validation (≥ 40 dB per frame).
     Loaded from the positions.json file saved by SEC1.
  3. PSNR vs bits embedded: embed increasing fractions of the validated
     positions (25 / 50 / 75 / 100 %) and measure full-video PSNR.
     No additional FFmpeg validation needed — positions are pre-verified.

Produces:
  - sec2_psnr_vs_bits.png      : PSNR vs bits embedded (validated positions)
  - sec2_capacity_budget.png   : Three-tier capacity chart (raw / validated / payload)
  - sec2_capacity_bar.png      : Raw T1 capacity per sequence (bits + bytes)
"""

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
    OUTPUT_DIR, load_or_extract_idr_blocks,
)

CACHE_KEY   = "sec2_capacity_data"
CIF_MB_COUNT = 396

# Fractions of validated positions to test (in %)
VALIDATED_FRACTIONS = [25, 50, 75, 100]

# ZK payload size embedded in SEC1
ZK_PAYLOAD_BYTES    = 147
ZK_PAYLOAD_BITS     = ZK_PAYLOAD_BYTES * 8   # 1176 bits
ZK_BLOB_BITS        = 1232                    # chaos-expanded size (154 bytes × 8)


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

    print(f"  [{seq_name}] {total_valid} validated positions -> sweep {fractions}%")
    rec = BitstreamReconstructor()
    coeffs, fvd, nC_map, nal_len, t1_over = load_or_extract_idr_blocks(
        video_path, rec
    )

    orig_frames = decode_luma_frames(video_path)

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

        stego_frames = decode_luma_frames(out_path)
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
# Raw T1 capacity (fast, no embed)
# ---------------------------------------------------------------------------
def _raw_t1_capacity(video_path: Path) -> int:
    from src.bitstream.bitstream_ops import BitstreamReconstructor
    from src.core.stego import CAVLCSafetyFilter
    rec = BitstreamReconstructor()
    coeffs, _, nC_map, nal_len, t1_over = load_or_extract_idr_blocks(video_path, rec)
    sf = CAVLCSafetyFilter()
    return len(sf.get_safe_positions(coeffs, nC_map=nC_map,
                                     nal_length_map=nal_len, t1_override_map=t1_over))


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------
def collect_data(force: bool = False) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        print("  [cache hit] sec2 — skipping capacity sweep")
        return cached

    # Build a synthetic scrambled payload (same chaos key as SEC1)
    from src.core.chaos import ChaosTransformer
    _chaos = ChaosTransformer(b"\x00" * 32)    # deterministic placeholder
    _dummy_payload = bytes(ZK_PAYLOAD_BYTES)
    payload_scrambled, _ = _chaos.scramble(_dummy_payload)

    SWEEP_SEQS = ["foreman_q22_g1", "coastguard_q22_g1"]
    data: dict = {}

    import os as _os
    _os.environ["BENCHMARK_TRUSTED_IDR_PICKLE_CACHE"] = "1"

    for seq_name in SWEEP_SEQS:
        video_path = SEQUENCES.get(seq_name)
        if not video_path or not video_path.exists():
            print(f"  [{seq_name}] video not found — skip")
            continue

        positions_path = OUTPUT_DIR / f"sec1_stego_{seq_name}.h264.positions.json"
        if not positions_path.exists():
            print(f"  [{seq_name}] positions.json not found (run sec1 first) — skip")
            continue

        print(f"\n  [{seq_name}] measuring raw T1 capacity ...")
        raw_capacity = _raw_t1_capacity(video_path)
        print(f"  [{seq_name}] raw T1 = {raw_capacity:,} bits")

        sweep = _sweep_validated_psnr(
            seq_name, video_path, positions_path,
            VALIDATED_FRACTIONS, payload_scrambled,
        )

        # Validated capacity = number of positions saved from SEC1
        validated_cap = sweep["validated_positions"]

        data[seq_name] = {
            "raw_t1_bits":          raw_capacity,
            "raw_t1_bytes":         raw_capacity // 8,
            "validated_bits":       validated_cap,
            "zk_blob_bits":         ZK_BLOB_BITS,
            "zk_payload_bits":      ZK_PAYLOAD_BITS,
            "utilization_pct":      round(100.0 * ZK_BLOB_BITS / raw_capacity, 3),
            "fractions_pct":        sweep["fractions_pct"],
            "bits_at_fraction":     sweep["bits_at_fraction"],
            "psnr_at_fraction":     sweep["psnr_at_fraction"],
        }

    cache_save(CACHE_KEY, data)
    return data


# ---------------------------------------------------------------------------
# Plot 1: PSNR vs bits embedded (validated fractions)
# ---------------------------------------------------------------------------
def plot_psnr_vs_bits(data: dict) -> None:
    setup_style()
    fig, ax = plt.subplots(figsize=(9, 5))

    colors = list(PALETTE.values())
    markers = ["o", "s", "^", "D"]

    for i, (seq, d) in enumerate(data.items()):
        if not d.get("bits_at_fraction"):
            continue
        label = SEQ_LABELS.get(seq, seq).split(" (")[0]
        ax.plot(
            d["bits_at_fraction"], d["psnr_at_fraction"],
            color=colors[i], marker=markers[i % len(markers)],
            linewidth=2.2, markersize=8, label=label,
        )
        # Annotate 100% point (actual operating point)
        x100 = d["bits_at_fraction"][-1]
        y100 = d["psnr_at_fraction"][-1]
        ax.annotate(
            f"{y100:.1f} dB",
            xy=(x100, y100), xytext=(x100 + 30, y100 - 1.5),
            fontsize=9, color=colors[i], fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=colors[i], lw=1.2),
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

    raw_bits       = [data[s]["raw_t1_bits"]    for s in seqs]
    validated_bits = [data[s]["validated_bits"] for s in seqs]
    zk_bits        = [ZK_BLOB_BITS] * n

    ax.bar(x - w,     raw_bits,       width=w, color=PALETTE["this_work"],
           alpha=0.80, label="Raw T1 capacity (unvalidated)", zorder=3)
    ax.bar(x,         validated_bits, width=w, color=PALETTE["f5"],
           alpha=0.85, label="Quality-constrained capacity (PSNR ≥ 40 dB)", zorder=3)
    ax.bar(x + w,     zk_bits,        width=w, color=PALETTE["lsb"],
           alpha=0.85, label=f"ZK blob payload ({ZK_BLOB_BITS} bits)", zorder=3)

    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("Bits (log scale)")
    ax.set_title("§2  Embedding Capacity Budget\n"
                 "(raw T1 positions vs quality-constrained vs ZK payload requirement)")
    ax.legend(fontsize=9)

    # Annotate utilization rate
    for i, s in enumerate(seqs):
        util = data[s]["utilization_pct"]
        ax.text(x[i] - w / 2, raw_bits[i] * 1.3,
                f"{util:.2f}%\nof raw",
                ha="center", va="bottom", fontsize=8.5,
                color=PALETTE["this_work"], fontweight="bold")
        ax.text(x[i], validated_bits[i] * 1.3,
                f"{validated_bits[i]:,}",
                ha="center", va="bottom", fontsize=8.5,
                color=PALETTE["f5"], fontweight="bold")

    save_fig(fig, "sec2_capacity_budget")


# ---------------------------------------------------------------------------
# Plot 3: Raw T1 capacity bar (bits + bytes, all sequences)
# ---------------------------------------------------------------------------
def plot_capacity_bar(data: dict) -> None:
    setup_style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5))

    seqs   = list(data.keys())
    labels = [SEQ_LABELS.get(s, s).split(" (")[0] for s in seqs]
    cap_bits  = [data[s]["raw_t1_bits"]  for s in seqs]
    cap_bytes = [data[s]["raw_t1_bytes"] for s in seqs]
    colors    = list(PALETTE.values())[:len(seqs)]

    x = np.arange(len(seqs))

    bars1 = ax1.bar(x, cap_bits, color=colors, width=0.5, zorder=3)
    ax1.set_xticks(x); ax1.set_xticklabels(labels, fontsize=10)
    ax1.set_ylabel("Raw T1 bits available")
    ax1.set_title("§2  Raw T1 Capacity (bits)")
    for bar, val in zip(bars1, cap_bits):
        ax1.text(bar.get_x() + bar.get_width() / 2,
                 bar.get_height() * 1.02,
                 f"{val:,}", ha="center", va="bottom",
                 fontsize=10, fontweight="bold")

    bars2 = ax2.bar(x, cap_bytes, color=colors, width=0.5, zorder=3)
    ax2.set_xticks(x); ax2.set_xticklabels(labels, fontsize=10)
    ax2.set_ylabel("Capacity (bytes)")
    ax2.set_title("§2  Raw T1 Capacity (bytes)")
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
def run(force: bool = False) -> dict:
    print("\n=== §2  Capacity & PSNR vs Payload Size ===")
    data = collect_data(force=force)
    plot_psnr_vs_bits(data)
    plot_capacity_budget(data)
    plot_capacity_bar(data)
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run sec2 capacity benchmark")
    parser.add_argument("--force", action="store_true", help="Ignore cache and recompute")
    args = parser.parse_args()
    run(force=args.force)
