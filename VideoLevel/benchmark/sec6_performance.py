"""
Section 6 — End-to-End Pipeline Performance
============================================
Measures wall-clock time for each stage of the full pipeline:
  1. IDR extraction + safety filter
  2. Payload embedding (CAVLC T1)
  3. Bitstream reconstruction
  4. ZK proof generation  (snarkjs Groth16)
  5. ZK verification
  6. Payload extraction (decode stego)

Produces:
  - sec6_timing_stacked_bar.png  : Stacked bar per sequence
  - sec6_timing_breakdown.png    : Pie chart (total time breakdown)
  - sec6_scalability.png         : Timing vs video length (simulated)
"""

import os
import sys
import time
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import (
    PALETTE, SEQUENCES, SEQ_LABELS,
    setup_style, save_fig, cache_save, cache_load,
    ROOT, OUTPUT_DIR, CIRCUITS_DIR, annotate_literature,
)

CACHE_KEY = "sec6_performance_data"

SECRET_KEY = bytes(range(32))
MESSAGE    = b"ZK-Stego performance benchmark!!"


def _fast_mode_enabled() -> bool:
    return os.environ.get("SEC6_FAST_MODE", "0") == "1"


# -------------------------------------------------------------------------
# Data collection: measure each stage separately
# -------------------------------------------------------------------------
def _measure_pipeline(seq_name: str, video_path: Path, *, force_extract: bool = False) -> dict:
    from src.core.pipeline import extract_bits_direct
    from src.core.stego import PayloadEmbedder, CAVLCSafetyFilter
    from src.bitstream.bitstream_ops import BitstreamReconstructor
    from src.zk_proof import ZKSnarkBridge, pack, unpack, blob_bit_length
    from benchmark._common import load_or_extract_idr_blocks

    stego_out = OUTPUT_DIR / f"_sec6_{seq_name}_stego.h264"

    timings: dict[str, float] = {}

    # --- Stage 1: IDR extraction ---
    t0 = time.perf_counter()
    rec = BitstreamReconstructor()
    coeffs, fvd, nC_map, nal_len, t1_over = load_or_extract_idr_blocks(
        str(video_path), rec, force=force_extract
    )
    timings["1_extract_idr"] = time.perf_counter() - t0

    # --- Stage 2: Safety filter (get safe positions) ---
    t0 = time.perf_counter()
    sf = CAVLCSafetyFilter()
    safe_pos = sf.get_safe_positions(
        coeffs, nC_map=nC_map, nal_length_map=nal_len, t1_override_map=t1_over
    )
    timings["2_safety_filter"] = time.perf_counter() - t0
    capacity_bits = len(safe_pos)

    # --- Stage 3: ZK proof generation ---
    t0 = time.perf_counter()
    bridge = ZKSnarkBridge(str(CIRCUITS_DIR))
    proof_dict, public_dict = bridge.generate_proof_for_payload(MESSAGE, SECRET_KEY)
    timings["3_zk_prove"] = time.perf_counter() - t0

    # --- Stage 4: Embed (pack blob + CAVLC T1) ---
    proof_bytes = bridge.proof_to_bytes(proof_dict)
    blob = pack(MESSAGE, proof_bytes)
    t0 = time.perf_counter()
    embedder = PayloadEmbedder(max_modifications_per_block=1)
    modified, bits_emb = embedder.embed_payload(
        coeffs, blob,
        nC_map=nC_map, nal_length_map=nal_len, t1_override_map=t1_over,
    )
    timings["4_embed"] = time.perf_counter() - t0

    # --- Stage 5: Bitstream reconstruction ---
    t0 = time.perf_counter()
    rec2 = BitstreamReconstructor()
    rec2.reconstruct_video(
        str(video_path),
        modified,
        str(stego_out),
        max_slices=None,
        frame_verified_data=fvd,
    )
    timings["5_reconstruct"] = time.perf_counter() - t0

    # --- Stage 6: Extract bits (decode stego using original safe positions) ---
    t0 = time.perf_counter()
    n_bits_needed = blob_bit_length(MESSAGE)
    extracted_blob = extract_bits_direct(
        str(stego_out),
        safe_pos,
        fvd,
        nC_map,
        n_bits_needed,
        max_modifications_per_block=1,
    )
    timings["6_extract_bits"] = time.perf_counter() - t0

    # --- Stage 7: ZK verification ---
    t0 = time.perf_counter()
    valid = bridge.verify(proof_dict, public_dict)
    timings["7_zk_verify"] = time.perf_counter() - t0

    total = sum(timings.values())

    return {
        "timings":        {k: round(v, 4) for k, v in timings.items()},
        "total_s":        round(total, 4),
        "capacity_bits":  capacity_bits,
        "bits_embedded":  bits_emb,
        "blob_size":      len(blob),
        "zk_valid":       valid,
    }


def collect_data(force: bool = False,
                 include_sequences: set[str] | None = None) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        print("  [cache hit] sec6 — skipping pipeline timing")
        return cached

    data: dict = {}
    # Default: all-intra q22_g1 sequences (fast, representative)
    DEFAULT_PERF = {"foreman_q22_g1"} if _fast_mode_enabled() else {"foreman_q22_g1", "coastguard_q22_g1"}
    active = include_sequences if include_sequences else DEFAULT_PERF
    PERF_SEQUENCES = {k: v for k, v in SEQUENCES.items()
                      if k in active}
    if not PERF_SEQUENCES:
        PERF_SEQUENCES = {k: v for k, v in SEQUENCES.items() if k != "deadline"}
    for seq_name, video_path in PERF_SEQUENCES.items():
        print(f"  [{seq_name}] measuring pipeline …")
        result = _measure_pipeline(seq_name, video_path, force_extract=force and not _fast_mode_enabled())
        data[seq_name] = result
        print(f"  [{seq_name}] total = {result['total_s']:.1f} s  "
              f"(ZK prove = {result['timings']['3_zk_prove']:.1f} s)")

    cache_save(CACHE_KEY, data)
    return data


# -------------------------------------------------------------------------
# Stage classification: one-time pre-processing vs per-embed operational
# -------------------------------------------------------------------------
PREPROCESS_STAGES = {"1_extract_idr", "2_safety_filter"}
OPERATIONAL_STAGES = {"3_zk_prove", "4_embed", "5_reconstruct", "6_extract_bits", "7_zk_verify"}

STAGE_LABELS = {
    "1_extract_idr":   "IDR Extraction (one-time)",
    "2_safety_filter": "Safety Filter (one-time)",
    "3_zk_prove":      "ZK Prove (Groth16)",
    "4_embed":         "CAVLC T1 Embed",
    "5_reconstruct":   "Bitstream Reconstruct",
    "6_extract_bits":  "Extract & Verify",
    "7_zk_verify":     "ZK Verify",
}

PREPROCESS_COLORS = {"1_extract_idr": "#78909C", "2_safety_filter": "#90A4AE"}
OPERATIONAL_COLORS = {
    "3_zk_prove":     "#FF6F00",
    "4_embed":        "#2E7D32",
    "5_reconstruct":  "#4CAF50",
    "6_extract_bits": "#0288D1",
    "7_zk_verify":    "#FF8F00",
}
STAGE_COLORS_MAP = {**PREPROCESS_COLORS, **OPERATIONAL_COLORS}


# -------------------------------------------------------------------------
# Plot 1a: Two-phase timing breakdown — pre-processing vs operational
# -------------------------------------------------------------------------
def plot_two_phase(data: dict) -> None:
    """Side-by-side: one-time pre-processing cost vs per-embed operational cost."""
    setup_style()
    seqs   = list(data.keys())
    labels = [SEQ_LABELS.get(s, s).split(" (")[0] for s in seqs]
    n      = len(seqs)

    pre_stages = ["1_extract_idr", "2_safety_filter"]
    op_stages  = ["3_zk_prove", "4_embed", "5_reconstruct", "6_extract_bits", "7_zk_verify"]

    fig, (ax_pre, ax_op) = plt.subplots(1, 2, figsize=(13, 6),
                                         gridspec_kw={"width_ratios": [1.4, 1]})

    # --- Left: pre-processing (one-time) ---
    x_pre   = np.arange(n)
    bot_pre = np.zeros(n)
    for stage in pre_stages:
        vals = [data[s]["timings"].get(stage, 0.0) for s in seqs]
        bars = ax_pre.bar(x_pre, vals, bottom=bot_pre,
                          color=STAGE_COLORS_MAP[stage],
                          label=STAGE_LABELS[stage], width=0.5, zorder=3)
        for b, v, bot in zip(bars, vals, bot_pre):
            if v > 5:
                ax_pre.text(b.get_x() + b.get_width() / 2, bot + v / 2,
                            f"{v:.0f}s", ha="center", va="center",
                            fontsize=9, color="white", fontweight="bold")
        bot_pre += np.array(vals)

    for xi, seq in zip(x_pre, seqs):
        total_pre = sum(data[seq]["timings"].get(s, 0) for s in pre_stages)
        ax_pre.text(xi, total_pre + 8, f"{total_pre:.0f} s",
                    ha="center", va="bottom", fontsize=10, fontweight="bold")

    ax_pre.set_xticks(x_pre)
    ax_pre.set_xticklabels(labels, fontsize=10)
    ax_pre.set_ylabel("Time (seconds)")
    ax_pre.set_title("Pre-processing\n(one-time per video)", fontweight="bold")
    ax_pre.legend(fontsize=8, loc="upper right")
    ax_pre.text(0.02, 0.02,
                "Run once; results cached\nfor all subsequent embeddings.",
                transform=ax_pre.transAxes, fontsize=8, color="#555",
                verticalalignment="bottom")

    # --- Right: operational (per-embed) ---
    x_op   = np.arange(n)
    bot_op = np.zeros(n)
    for stage in op_stages:
        vals = [data[s]["timings"].get(stage, 0.0) for s in seqs]
        bars = ax_op.bar(x_op, vals, bottom=bot_op,
                         color=STAGE_COLORS_MAP[stage],
                         label=STAGE_LABELS[stage], width=0.5, zorder=3)
        for b, v, bot in zip(bars, vals, bot_op):
            if v > 0.5:
                ax_op.text(b.get_x() + b.get_width() / 2, bot + v / 2,
                           f"{v:.1f}s", ha="center", va="center",
                           fontsize=8.5, color="white", fontweight="bold")
        bot_op += np.array(vals)

    for xi, seq in zip(x_op, seqs):
        total_op = sum(data[seq]["timings"].get(s, 0) for s in op_stages)
        ax_op.text(xi, total_op + 0.5, f"{total_op:.1f} s",
                   ha="center", va="bottom", fontsize=10, fontweight="bold")

    ax_op.set_xticks(x_op)
    ax_op.set_xticklabels(labels, fontsize=10)
    ax_op.set_ylabel("Time (seconds)")
    ax_op.set_title("Operational\n(per-embed)", fontweight="bold")
    ax_op.legend(fontsize=8, loc="upper right")

    fig.suptitle("§6  Pipeline Timing: Pre-processing vs Operational Cost",
                 fontweight="bold", fontsize=13)
    plt.tight_layout()
    save_fig(fig, "sec6_timing_two_phase")


# -------------------------------------------------------------------------
# Plot 1b: Stacked bar — full pipeline per sequence (log scale for honesty)
# -------------------------------------------------------------------------
def plot_stacked_bar(data: dict) -> None:
    setup_style()
    fig, ax = plt.subplots(figsize=(11, 6))

    seqs   = list(data.keys())
    stages = list(STAGE_LABELS.keys())
    labels = [SEQ_LABELS.get(s, s).split(" (")[0] for s in seqs]

    x      = np.arange(len(seqs))
    bottom = np.zeros(len(seqs))

    for stage in stages:
        vals = [data[seq]["timings"].get(stage, 0.0) for seq in seqs]
        bars = ax.bar(x, vals, bottom=bottom,
                      color=STAGE_COLORS_MAP[stage],
                      label=STAGE_LABELS[stage],
                      width=0.5, zorder=3)
        for b, v, bot in zip(bars, vals, bottom):
            if v > 5:
                ax.text(b.get_x() + b.get_width() / 2, bot + v / 2,
                        f"{v:.0f}s", ha="center", va="center",
                        fontsize=8.5, color="white", fontweight="bold")
        bottom += np.array(vals)

    op_stages = list(OPERATIONAL_STAGES)
    for b_x, seq in zip(x, seqs):
        total   = data[seq]["total_s"]
        op_cost = sum(data[seq]["timings"].get(s, 0) for s in op_stages)
        ax.text(b_x, total + 5, f"Total {total:.0f}s",
                ha="center", va="bottom", fontsize=9, fontweight="bold")
        ax.annotate(f"Operational\n{op_cost:.1f}s", xy=(b_x, op_cost),
                    xytext=(b_x + 0.35, op_cost + 30),
                    fontsize=8, color="#C62828", ha="left",
                    arrowprops=dict(arrowstyle="->", color="#C62828", lw=1.0))

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("Time (seconds)")
    ax.set_title("§6  Full Pipeline Timing (all stages)", fontweight="bold")
    ax.legend(loc="upper right", fontsize=8.5, ncol=2)
    ax.text(0.01, 0.01,
            "Grey bars = one-time pre-processing (IDR extraction + safety filter).\n"
            "Coloured bars = operational cost repeated per embedding run.",
            transform=ax.transAxes, fontsize=8, color="#555555",
            verticalalignment="bottom")

    save_fig(fig, "sec6_timing_stacked_bar")


# -------------------------------------------------------------------------
# Plot 2: Pie chart — time breakdown (average across sequences)
# -------------------------------------------------------------------------
def plot_timing_pie(data: dict) -> None:
    """Pie chart of operational (per-embed) stages only — excludes one-time pre-processing."""
    setup_style()
    fig, ax = plt.subplots(figsize=(8, 7))

    op_stage_keys = ["3_zk_prove", "4_embed", "5_reconstruct", "6_extract_bits", "7_zk_verify"]
    seqs = list(data.keys())

    avg_timings = {
        stage: float(np.mean([data[seq]["timings"].get(stage, 0.0) for seq in seqs]))
        for stage in op_stage_keys
    }

    vals    = [avg_timings[s] for s in op_stage_keys]
    labels  = [f"{STAGE_LABELS[s]}\n({avg_timings[s]:.1f} s)" for s in op_stage_keys]
    colors  = [OPERATIONAL_COLORS[s] for s in op_stage_keys]
    explode = [0.05 if "zk_prove" in s else 0.0 for s in op_stage_keys]

    wedges, texts, autotexts = ax.pie(
        vals, labels=labels, colors=colors,
        autopct="%1.1f%%", pctdistance=0.78,
        startangle=140, explode=explode,
        textprops={"fontsize": 9},
    )
    for at in autotexts:
        at.set_fontsize(8.5)
        at.set_color("white")
        at.set_fontweight("bold")

    op_total = sum(vals)
    ax.set_title(f"§6  Operational Pipeline Breakdown\n"
                 f"(per-embed cost ~ {op_total:.1f} s avg; excludes one-time pre-processing)",
                 fontweight="bold")

    save_fig(fig, "sec6_timing_pie")


# -------------------------------------------------------------------------
# Plot 3: Scalability — total time vs video length (simulated)
# Based on observed linear scaling of embedding stage +
# fixed cost of ZK proof (constant regardless of video length)
# -------------------------------------------------------------------------
def plot_scalability(data: dict) -> None:
    """
    Projects timing to longer videos.
    ZK prove is constant (circuit is fixed);
    extract/embed/reconstruct scale linearly with frames.
    """
    setup_style()
    fig, ax = plt.subplots(figsize=(9, 5))

    # Use foreman_q22_g1 as baseline (300-frame all-intra clip)
    from benchmark._common import SEQ_FRAMES
    seq = next((k for k in data if "foreman" in k), list(data.keys())[0])
    d   = data[seq]
    n_frames_base = SEQ_FRAMES.get(seq, 300)

    fixed_cost  = d["timings"]["3_zk_prove"] + d["timings"]["7_zk_verify"]
    linear_cost = (d["total_s"] - fixed_cost)  # per 50 frames

    frame_counts = [25, 50, 100, 200, 300, 500, 750, 1000]
    total_times  = [
        fixed_cost + linear_cost * (f / n_frames_base)
        for f in frame_counts
    ]
    zk_only = [fixed_cost] * len(frame_counts)
    embed_only = [linear_cost * (f / n_frames_base) for f in frame_counts]

    ax.fill_between(frame_counts,
                    [0] * len(frame_counts), zk_only,
                    alpha=0.3, color=PALETTE["this_work"], label="ZK prove (fixed)")
    ax.fill_between(frame_counts, zk_only, total_times,
                    alpha=0.3, color=PALETTE["f5"],
                    label="Extract/embed/reconstruct (linear)")
    ax.plot(frame_counts, total_times, "-",
            color=PALETTE["this_work"], linewidth=2.5, label="Total time")
    ax.plot(frame_counts, zk_only, "--",
            color="#888888", linewidth=1.5, label="ZK time only (constant)")

    ax.axvline(n_frames_base, color="#555555", linestyle=":", linewidth=1.0,
               label=f"Benchmark point ({n_frames_base} frames)")

    ax.set_xlabel("Video length (frames)")
    ax.set_ylabel("Estimated total time (seconds)")
    ax.set_title("§6  Pipeline Scalability vs Video Length\n"
                 "(ZK proof cost is constant; embed/recon cost scales linearly)")
    ax.legend(fontsize=9)
    ax.set_xlim(0, 1050)

    annotate_literature(ax, f"Projected via linear extrapolation from {n_frames_base}-frame foreman measurements")
    save_fig(fig, "sec6_scalability")


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------
def run(force: bool = False,
        include_sequences: set[str] | None = None) -> dict:
    print("\n=== §6  Pipeline Performance ===")
    data = collect_data(force=force, include_sequences=include_sequences)
    plot_two_phase(data)
    plot_stacked_bar(data)
    plot_timing_pie(data)
    plot_scalability(data)
    return data


if __name__ == "__main__":
    import argparse as _ap
    _parser = _ap.ArgumentParser()
    _parser.add_argument("--force", action="store_true")
    _parser.add_argument("--sequences", type=str, default=None)
    _parser.add_argument("--fast", action="store_true")
    _args = _parser.parse_args()
    if _args.fast:
        os.environ["SEC6_FAST_MODE"] = "1"
    _seqs = set(_args.sequences.split(",")) if _args.sequences else None
    run(force=_args.force, include_sequences=_seqs)
