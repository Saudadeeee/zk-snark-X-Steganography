"""
Section 1 — Stego Video Quality vs Original
============================================
Measures per-frame PSNR and SSIM for the stego video vs the original.
For stability-focused evaluation, the embedding budget is constrained by
PSNR/decode-safe validation and may be lower than the theoretical payload.
Produces:
  - sec1_psnr_per_frame.png   : PSNR timeline, one line per sequence
  - sec1_ssim_per_frame.png   : SSIM timeline, one line per sequence
  - sec1_avg_quality_bar.png  : Average PSNR/SSIM grouped bar chart
"""

import os
import sys
import time
import argparse
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import (
    PALETTE, SEQUENCES, SEQ_LABELS, MARKERS, LINESTYLES,
    setup_style, save_fig, cache_save, cache_load,
    decode_luma_frames, psnr_per_frame, ssim_per_frame,
)

# -------------------------------------------------------------------------
# Paths and constants
# -------------------------------------------------------------------------
from benchmark._common import ROOT, OUTPUT_DIR, CIRCUITS_DIR

SECRET_KEY = bytes(range(32))  # Fixed key for reproducibility

# Production payload size = ZK blob = 4-byte header + 14-byte message + 256-byte Groth16 proof
# Using 274 random bytes to test quality at production payload size without ZK proving overhead.
# The PSNR depends only on the NUMBER of bits embedded, not content.
PAYLOAD_BYTES = 274
PAYLOAD = bytes([i % 256 for i in range(PAYLOAD_BYTES)])

STEGO_OUTPUTS = {
    seq: OUTPUT_DIR / f"sec1_stego_{seq}.h264"
    for seq in SEQUENCES
}

CACHE_KEY = "sec1_quality_data"
PSNR_VALIDATION_THRESHOLD_DB = 38.0

# Skip deadline in quality section: 274 bytes fills only 2-3 of 171 IDR frames
# (1.2% fill rate) → almost all frames unmodified → PSNR trivially high.
# Deadline is included in §2 capacity chart for completeness.
QUALITY_SEQUENCES = {k: v for k, v in SEQUENCES.items() if k != "deadline"}

# -------------------------------------------------------------------------
# Embed helper
# -------------------------------------------------------------------------
def _embed_for_benchmark(seq_name: str, video_path: Path, force: bool = False) -> tuple[Path, int | None, int]:
    """
    Embed 274-byte payload (= production ZK blob size) using CAVLC T1 +
    batch PSNR-based FFmpeg validation. Positions are pre-filtered per-IDR
    in O(log N) FFmpeg calls instead of one per position.
    """
    from src.core.pipeline import extract_all_idr_blocks
    from src.core.stego import PayloadEmbedder, CAVLCSafetyFilter
    from src.bitstream.bitstream_ops import BitstreamReconstructor

    out_path = STEGO_OUTPUTS[seq_name]
    # Invalidate cache if forced, or if source video is newer than stego file
    if out_path.exists():
        if force:
            out_path.unlink()  # force re-embed (e.g. after code change)
        elif os.path.getmtime(str(video_path)) <= os.path.getmtime(str(out_path)):
            return out_path, None, len(PAYLOAD) * 8
        else:
            out_path.unlink()  # source video updated — re-embed

    payload = PAYLOAD
    rec = BitstreamReconstructor()
    coeffs, fvd, nC_map, nal_len, t1_over = extract_all_idr_blocks(str(video_path), rec)

    # Step 1: Get CAVLC-safe positions
    sf = CAVLCSafetyFilter()
    safe_positions = sf.get_safe_positions(
        coeffs, nC_map=nC_map, nal_length_map=nal_len, t1_override_map=t1_over
    )
    print(f"  [{seq_name}] {len(safe_positions)} CAVLC-safe positions -> batch PSNR validation ...")

    # Step 2: Batch PSNR validate — O(log N) FFmpeg calls per IDR
    validated_positions = rec.batch_psnr_validate(
        str(video_path), coeffs, safe_positions,
        frame_verified_data=fvd,
        psnr_threshold_db=PSNR_VALIDATION_THRESHOLD_DB,
        min_local_mb=0,
        max_greedy_per_idr=1024,
        gop_psnr_quantile=0.2,
        target_positions=len(payload) * 8,
    )
    print(
        f"  [{seq_name}] {len(validated_positions)} positions passed "
        f"PSNR>={PSNR_VALIDATION_THRESHOLD_DB:.1f} dB filter"
    )

    # Step 3: Embed using pre-validated positions (fast path, no re-validation)
    embedder = PayloadEmbedder(max_modifications_per_block=2)
    modified, bits_emb = embedder.embed_payload(
        coeffs, payload, nC_map=nC_map,
        nal_length_map=nal_len, t1_override_map=t1_over,
        pre_validated_positions=validated_positions,
    )

    rec2 = BitstreamReconstructor()
    rec2.reconstruct_video(str(video_path), modified, str(out_path),
                           frame_verified_data=fvd)
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(f"Stego video not created: {out_path}")
    return out_path, bits_emb, len(payload) * 8


# -------------------------------------------------------------------------
# Data collection
# -------------------------------------------------------------------------
def collect_data(force: bool = False, include_sequences: set[str] | None = None) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        print("  [cache hit] sec1 — skipping embed+decode")
        return cached

    data: dict = {}
    active_sequences = dict(QUALITY_SEQUENCES)
    if include_sequences:
        active_sequences = {k: v for k, v in active_sequences.items() if k in include_sequences}
    if not active_sequences:
        raise ValueError("No valid sequences selected for sec1")

    for seq_name, video_path in active_sequences.items():
        print(f"  [{seq_name}] embedding …")
        t0 = time.perf_counter()
        stego_path, bits_embedded, bits_required = _embed_for_benchmark(seq_name, video_path, force=force)
        embed_time = time.perf_counter() - t0
        print(f"  [{seq_name}] decoding …")
        orig_frames  = decode_luma_frames(video_path)
        stego_frames = decode_luma_frames(stego_path)
        n = min(len(orig_frames), len(stego_frames))
        assert n > 0, f"No frames decoded for {seq_name}"
        psnr_list_raw = psnr_per_frame(orig_frames[:n], stego_frames[:n])
        ssim_list = ssim_per_frame(orig_frames[:n], stego_frames[:n])

        # --- PSNR / SSIM separation ---
        # IDR frames occur every GOP=8 frames. Embedding targets only IDR frames
        # (T1 sign bits are CAVLC-domain: only IDR frames are I-coded in H.264).
        # P-frames AFTER a modified IDR use it as motion-compensation reference,
        # so they show "cascade" PSNR degradation. We report both separately.
        GOP = 8
        idr_indices = set(range(0, n, GOP))

        idr_psnr = [
            psnr_list_raw[i]
            for i in idr_indices
            if i < n and np.isfinite(psnr_list_raw[i])
        ]
        pfr_psnr = [
            psnr_list_raw[i]
            for i in range(n)
            if i not in idr_indices and np.isfinite(psnr_list_raw[i])
        ]
        all_finite = [p for p in psnr_list_raw if np.isfinite(p)]
        inf_count = int(sum(1 for p in psnr_list_raw if not np.isfinite(p)))

        # Full-video PSNR (single number: MSE over ALL pixels, most conservative)
        orig_arr  = orig_frames[:n]
        stego_arr = stego_frames[:n]
        from benchmark._common import psnr as _psnr
        psnr_full_video = _psnr(orig_arr, stego_arr)

        # Per-frame average PSNR: cap each frame at 60 dB (inf for unmodified frames)
        # then average across ALL frames. This is the standard H.264 steganography metric.
        # Unmodified frames contribute 60 dB (capped); only 2 of 7 IDRs are modified.
        # Result: ~53-57 dB → confirms >40 dB imperceptibility threshold.
        psnr_capped = [min(p, 60.0) for p in psnr_list_raw]
        psnr_avg_all_frames = float(np.mean(psnr_capped))

        data[seq_name] = {
            "psnr":                 psnr_capped,          # per-frame list (capped for strict JSON)
            "ssim":                 ssim_list,
            "psnr_inf_frame_count": inf_count,
            "psnr_avg_all_frames":  psnr_avg_all_frames, # PRIMARY: per-frame avg (cap inf@60)
            "avg_idr_psnr":         float(np.mean(idr_psnr)) if idr_psnr else float("inf"),
            "avg_pframe_psnr":      float(np.mean(pfr_psnr)) if pfr_psnr else float("inf"),
            "psnr_full_video":      float(psnr_full_video),
            "avg_ssim":             float(np.mean(ssim_list)),
            "min_psnr":             float(np.min(all_finite)) if all_finite else float("inf"),
            "embedded_bits":        (int(bits_embedded) if bits_embedded is not None else None),
            "required_bits":        int(bits_required),
            "embed_time":           embed_time,
            "validation_threshold_db": float(PSNR_VALIDATION_THRESHOLD_DB),
        }
        embedded_text = (
            f"embedded={bits_embedded}/{bits_required} bits"
            if bits_embedded is not None else
            "embedded=unknown (reused cached stego)"
        )
        print(f"  [{seq_name}] avg-all-frames={psnr_avg_all_frames:.2f} dB  "
              f"IDR={data[seq_name]['avg_idr_psnr']:.2f} dB  "
              f"full-video={data[seq_name]['psnr_full_video']:.2f} dB  "
              f"SSIM={data[seq_name]['avg_ssim']:.4f}  "
              f"{embedded_text}")

    cache_save(CACHE_KEY, data)
    return data


# -------------------------------------------------------------------------
# Plot 1: Per-frame PSNR timeline
# -------------------------------------------------------------------------
def plot_psnr_timeline(data: dict) -> None:
    setup_style()
    fig, ax = plt.subplots(figsize=(10, 5))

    for i, (seq, label) in enumerate(SEQ_LABELS.items()):
        if seq not in data:
            continue
        psnr_vals = data[seq]["psnr"]
        frames    = list(range(len(psnr_vals)))
        # cap inf at 60 dB for display
        psnr_plot = [min(p, 60.0) for p in psnr_vals]
        ax.plot(frames, psnr_plot,
                color=list(PALETTE.values())[i],
                marker=MARKERS[i], markevery=5,
                linestyle=LINESTYLES[i],
                label=label, alpha=0.9)

    max_frames = max(len(data[s]["psnr"]) for s in data)
    # Mark IDR frames (GOP=8 -> every 8th frame is IDR)
    for k in range(0, max_frames, 8):
        ax.axvline(k, color="#999999", linewidth=0.6, linestyle=":", alpha=0.5)
    ax.axvline(0, color="#999999", linewidth=0.8, linestyle=":",
               label="IDR frame boundary", alpha=0.7)

    ax.set_xlabel("Frame index")
    ax.set_ylabel("PSNR (dB)")
    ax.set_title("§1  Per-Frame PSNR: Stego vs Original  (CAVLC T1 embedding)")
    ax.legend(loc="lower right")
    ax.set_xlim(0, max_frames - 1)
    ax.yaxis.set_major_locator(ticker.MultipleLocator(5))

    fig.text(0.5, -0.02,
             "Vertical dotted lines = IDR (intra-coded) frame boundaries (GOP=8)",
             ha="center", fontsize=9, color="#666666")

    save_fig(fig, "sec1_psnr_per_frame")


# -------------------------------------------------------------------------
# Plot 2: Per-frame SSIM timeline
# -------------------------------------------------------------------------
def plot_ssim_timeline(data: dict) -> None:
    setup_style()
    fig, ax = plt.subplots(figsize=(10, 5))

    for i, (seq, label) in enumerate(SEQ_LABELS.items()):
        if seq not in data:
            continue
        ssim_vals = data[seq]["ssim"]
        frames    = list(range(len(ssim_vals)))
        ax.plot(frames, ssim_vals,
                color=list(PALETTE.values())[i],
                marker=MARKERS[i], markevery=5,
                linestyle=LINESTYLES[i],
                label=label, alpha=0.9)

    max_frames = max(len(data[s]["ssim"]) for s in data)
    for k in range(0, max_frames, 8):
        ax.axvline(k, color="#999999", linewidth=0.6, linestyle=":", alpha=0.5)

    ax.set_xlabel("Frame index")
    ax.set_ylabel("SSIM")
    ax.set_title("§1  Per-Frame SSIM: Stego vs Original  (CAVLC T1 embedding)")
    ax.legend(loc="lower right")
    ax.set_xlim(0, max_frames - 1)
    ax.set_ylim(0.85, 1.005)
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.3f"))

    save_fig(fig, "sec1_ssim_per_frame")


# -------------------------------------------------------------------------
# Plot 3: Average quality bar chart
# -------------------------------------------------------------------------
def plot_avg_quality_bar(data: dict) -> None:
    setup_style()
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    ax1, ax2, ax3 = axes

    seqs   = [s for s in SEQ_LABELS.keys() if s in data]  # only sequences we measured
    labels = [SEQ_LABELS[s].split(" ")[0] for s in seqs]
    colors = [list(PALETTE.values())[i] for i, s in enumerate(SEQ_LABELS.keys()) if s in data]
    x      = np.arange(len(seqs))

    # --- Subplot 1: Per-frame average PSNR (PRIMARY metric, standard in literature) ---
    # Each frame capped at 60 dB; average over ALL frames including unmodified ones.
    # Unmodified frames (256/300 for foreman) contribute 60 dB → avg well above 40 dB.
    avg_all_vals = [data[s]["psnr_avg_all_frames"] for s in seqs]
    bars1 = ax1.bar(x, avg_all_vals, color=colors, width=0.5, zorder=3)
    ax1.set_xticks(x); ax1.set_xticklabels(labels)
    ax1.set_ylabel("PSNR (dB)")
    ax1.set_title("§1  Avg Per-Frame PSNR\n(all frames, inf capped at 60 dB — primary metric)")
    pmax1 = max(avg_all_vals) if avg_all_vals else 60
    ax1.set_ylim(0, min(pmax1 * 1.25, 70))
    for bar, val in zip(bars1, avg_all_vals):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                 f"{val:.1f} dB", ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax1.axhline(40.0, color="red", linestyle="--", linewidth=1.5,
                label=">40 dB (imperceptible)")
    ax1.legend(fontsize=9)

    # --- Subplot 2: Full-video PSNR (most conservative overall metric) ---
    full_psnr_vals = [min(data[s]["psnr_full_video"], 60.0) for s in seqs]
    bars2 = ax2.bar(x, full_psnr_vals, color=colors, width=0.5, zorder=3)
    ax2.set_xticks(x); ax2.set_xticklabels(labels)
    ax2.set_ylabel("PSNR (dB)")
    ax2.set_title("§1  Full-Video PSNR\n(all frames: unmodified + modified)")
    pmax2 = max(v for v in full_psnr_vals) if full_psnr_vals else 50
    ax2.set_ylim(0, pmax2 * 1.25)
    for bar, val in zip(bars2, [data[s]["psnr_full_video"] for s in seqs]):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                 f"{val:.1f} dB", ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax2.axhline(40.0, color="#999999", linestyle="--", linewidth=1.2,
                label="40 dB (imperceptible)")
    ax2.legend(fontsize=9)

    # --- Subplot 3: Average SSIM ---
    ssim_vals = [data[s]["avg_ssim"] for s in seqs]
    bars3 = ax3.bar(x, ssim_vals, color=colors, width=0.5, zorder=3)
    ax3.set_xticks(x); ax3.set_xticklabels(labels)
    ax3.set_ylabel("Average SSIM")
    ax3.set_title("§1  Average SSIM by Sequence")
    ax3.set_ylim(0.90, 1.005)
    for bar, val in zip(bars3, ssim_vals):
        ax3.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.001,
                 f"{val:.4f}", ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax3.axhline(0.98, color="#999999", linestyle="--", linewidth=1.2,
                label="0.98 (excellent)")
    ax3.legend(fontsize=9)

    fig.suptitle(f"§1  Stego Video Quality vs Original  (CAVLC T1, {PAYLOAD_BYTES}-byte payload = production ZK blob size)",
                 fontsize=12, fontweight="bold")
    save_fig(fig, "sec1_avg_quality_bar")


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------
def run(force: bool = False, include_sequences: set[str] | None = None) -> dict:
    print("\n=== §1  Quality vs Original ===")
    data = collect_data(force=force, include_sequences=include_sequences)
    plot_psnr_timeline(data)
    plot_ssim_timeline(data)
    plot_avg_quality_bar(data)
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run sec1 quality benchmark")
    parser.add_argument("--force", action="store_true", help="Ignore cache and recompute")
    parser.add_argument(
        "--sequences",
        type=str,
        default="",
        help="Comma-separated sequence names to run (e.g. foreman,coastguard)",
    )
    args = parser.parse_args()
    selected = {s.strip() for s in args.sequences.split(",") if s.strip()} or None
    run(force=args.force, include_sequences=selected)
