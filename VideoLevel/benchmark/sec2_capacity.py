"""
Section 2 — Embedding Capacity & PSNR vs Payload Rate
======================================================
Answers: "How does image quality degrade as we embed more data?"

Methodology:
  - Vary payload from 5 % to 100 % of T1 capacity
  - Measure PSNR at each level for foreman and coastguard
  - Capacity bar chart includes all three sequences (deadline capacity only, no sweep)

Produces:
  - sec2_psnr_vs_payload_rate.png   : PSNR vs embedding rate (%) per sequence
  - sec2_capacity_bar.png           : Raw T1 capacity by sequence
"""

import sys
import time
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import (
    PALETTE, SEQUENCES, SEQ_LABELS, MARKERS, LINESTYLES,
    setup_style, save_fig, cache_save, cache_load,
    decode_luma_frames, psnr_per_frame,
    ROOT, OUTPUT_DIR,
)

CACHE_KEY = "sec2_capacity_data"

# Payload rates to test (% of T1 capacity)
RATES = [5, 10, 20, 35, 50, 70, 85, 100]

# Skip deadline from PSNR sweep — 1374 frames × extract (~23 min) × 8 rates = impractical.
# Deadline is included in capacity bar chart only.
SWEEP_SEQUENCES = {k: v for k, v in SEQUENCES.items() if k != "deadline"}


# -------------------------------------------------------------------------
# Data collection
# -------------------------------------------------------------------------
def _measure_capacity_only(video_path: Path) -> dict:
    """Return T1 capacity info (fast, no embed)."""
    from src.core.pipeline import extract_all_idr_blocks
    from src.bitstream.bitstream_ops import BitstreamReconstructor
    from src.core.stego import CAVLCSafetyFilter

    rec = BitstreamReconstructor()
    coeffs, _, nC_map, nal_len, t1_over = extract_all_idr_blocks(str(video_path), rec)
    sf = CAVLCSafetyFilter()
    safe_pos = sf.get_safe_positions(coeffs, nC_map=nC_map, nal_length_map=nal_len,
                                     t1_override_map=t1_over)
    return {
        "total_t1_bits": len(safe_pos),
        "total_coeffs_blocks": len(coeffs),
    }


def _sweep_psnr(seq_name: str, video_path: Path) -> dict:
    """
    Extract IDR data ONCE, then embed at multiple rates and measure PSNR.
    Original frames decoded ONCE and reused across all rates.
    """
    from src.core.pipeline import extract_all_idr_blocks
    from src.core.stego import PayloadEmbedder, CAVLCSafetyFilter
    from src.bitstream.bitstream_ops import BitstreamReconstructor

    print(f"  [{seq_name}] extracting IDR blocks (once) …")
    t0 = time.perf_counter()
    rec = BitstreamReconstructor()
    coeffs, fvd, nC_map, nal_len, t1_over = extract_all_idr_blocks(str(video_path), rec)
    print(f"  [{seq_name}] IDR extract: {time.perf_counter()-t0:.1f}s")

    # Measure capacity
    sf = CAVLCSafetyFilter()
    safe_pos = sf.get_safe_positions(coeffs, nC_map=nC_map, nal_length_map=nal_len,
                                     t1_override_map=t1_over)
    capacity = len(safe_pos)
    print(f"  [{seq_name}] T1 capacity = {capacity} bits ({capacity//8} bytes)")

    # Decode original frames ONCE
    print(f"  [{seq_name}] decoding original frames …")
    orig_frames = decode_luma_frames(video_path)

    psnr_by_rate: list[float] = []
    for rate in RATES:
        n_bits  = max(8, int(capacity * rate / 100))
        n_bytes = (n_bits + 7) // 8
        payload = bytes([i % 256 for i in range(n_bytes)])

        out_path = OUTPUT_DIR / f"_sec2_{seq_name}_r{rate}.h264"
        print(f"  [{seq_name}] r={rate}% ({n_bits} bits / {n_bytes} B) …", end=" ", flush=True)
        t1 = time.perf_counter()

        embedder = PayloadEmbedder(max_modifications_per_block=1)
        modified, bits_emb = embedder.embed_payload(
            coeffs, payload, nC_map=nC_map,
            nal_length_map=nal_len, t1_override_map=t1_over,
            ffmpeg_validator=None,
        )

        rec2 = BitstreamReconstructor()
        rec2.reconstruct_video(str(video_path), modified, str(out_path),
                               frame_verified_data=fvd)

        stego_frames = decode_luma_frames(out_path)
        n = min(len(orig_frames), len(stego_frames))
        psnr_vals = psnr_per_frame(orig_frames[:n], stego_frames[:n])
        capped = [min(p, 60.0) for p in psnr_vals]
        avg_psnr = float(np.mean(capped)) if capped else 0.0
        psnr_by_rate.append(avg_psnr)
        print(f"PSNR={avg_psnr:.2f} dB  ({time.perf_counter()-t1:.1f}s)")

    return {
        "capacity_bits":   capacity,
        "capacity_bytes":  capacity // 8,
        "rates_pct":       RATES,
        "psnr_by_rate":    psnr_by_rate,
        "total_blocks":    len(coeffs),
    }


def collect_data(force: bool = False) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        print("  [cache hit] sec2 — skipping heavy embed loops")
        return cached

    data: dict = {}

    # Capacity measurement for ALL sequences (including deadline)
    for seq_name, video_path in SEQUENCES.items():
        if seq_name in SWEEP_SEQUENCES:
            # Full sweep (capacity + PSNR) — extract_all_idr_blocks called once internally
            data[seq_name] = _sweep_psnr(seq_name, video_path)
        else:
            # Capacity-only for deadline (too large for full sweep)
            print(f"  [{seq_name}] measuring capacity only (large video) …")
            cap = _measure_capacity_only(video_path)
            print(f"  [{seq_name}] T1 capacity = {cap['total_t1_bits']} bits")
            data[seq_name] = {
                "capacity_bits":   cap["total_t1_bits"],
                "capacity_bytes":  cap["total_t1_bits"] // 8,
                "rates_pct":       [],
                "psnr_by_rate":    [],
                "total_blocks":    cap["total_coeffs_blocks"],
            }

    cache_save(CACHE_KEY, data)
    return data


# -------------------------------------------------------------------------
# Plot 1: PSNR vs payload rate (sweep sequences only)
# -------------------------------------------------------------------------
def plot_psnr_vs_rate(data: dict) -> None:
    setup_style()
    fig, ax = plt.subplots(figsize=(9, 5))

    for i, (seq, label) in enumerate(SEQ_LABELS.items()):
        d = data.get(seq, {})
        if not d.get("psnr_by_rate"):
            continue  # skip capacity-only sequences
        ax.plot(d["rates_pct"], d["psnr_by_rate"],
                color=list(PALETTE.values())[i],
                marker=MARKERS[i], linestyle=LINESTYLES[i],
                label=label, alpha=0.9)

    ax.axhline(40.0, color="#888888", linestyle="--", linewidth=1.2,
               label="40 dB (imperceptible threshold)")
    ax.axhline(35.0, color="#BBBBBB", linestyle=":", linewidth=1.0,
               label="35 dB (acceptable quality)")

    ax.set_xlabel("Payload rate (% of T1 capacity)")
    ax.set_ylabel("Average PSNR (dB, unmod. frames capped at 60)")
    ax.set_title("§2  PSNR vs Embedding Rate  (CAVLC T1, descending order)")
    ax.legend(loc="lower left")
    ax.set_xlim(0, 105)
    ax.xaxis.set_major_locator(ticker.MultipleLocator(10))

    fig.text(0.5, -0.03,
             "T1 sign bits are length-preserving → bitstream size unchanged at all rates",
             ha="center", fontsize=9, color="#555555", style="italic")

    save_fig(fig, "sec2_psnr_vs_payload_rate")


# -------------------------------------------------------------------------
# Plot 2: Capacity bar chart (all sequences)
# -------------------------------------------------------------------------
def plot_capacity_bar(data: dict) -> None:
    setup_style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5))

    seqs   = list(SEQ_LABELS.keys())
    labels = [SEQ_LABELS[s].split(" ")[0] for s in seqs]
    cap_bits  = [data[s]["capacity_bits"]  for s in seqs]
    cap_bytes = [data[s]["capacity_bytes"] for s in seqs]
    colors    = [list(PALETTE.values())[i] for i in range(len(seqs))]

    x = np.arange(len(seqs))

    bars1 = ax1.bar(x, cap_bits, color=colors, width=0.5, zorder=3)
    ax1.set_xticks(x); ax1.set_xticklabels(labels)
    ax1.set_ylabel("T1 bits available")
    ax1.set_title("§2  Embedding Capacity (bits)")
    for bar, val in zip(bars1, cap_bits):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 50,
                 f"{val:,}", ha="center", va="bottom", fontsize=10, fontweight="bold")

    bars2 = ax2.bar(x, cap_bytes, color=colors, width=0.5, zorder=3)
    ax2.set_xticks(x); ax2.set_xticklabels(labels)
    ax2.set_ylabel("Capacity (bytes)")
    ax2.set_title("§2  Embedding Capacity (bytes)")
    for bar, val in zip(bars2, cap_bytes):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2,
                 f"{val:,} B", ha="center", va="bottom", fontsize=10, fontweight="bold")

    ax2.axhline(274, color="#C62828", linestyle="--", linewidth=1.5,
                label="ZK blob size (274 B)")
    ax2.legend(fontsize=9)

    save_fig(fig, "sec2_capacity_bar")


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------
def run(force: bool = False) -> dict:
    print("\n=== §2  Capacity & PSNR vs Payload Rate ===")
    data = collect_data(force=force)
    plot_psnr_vs_rate(data)
    plot_capacity_bar(data)
    return data


if __name__ == "__main__":
    run(force="--force" in sys.argv)
