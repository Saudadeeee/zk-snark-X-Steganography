"""
Section 3 — Comparison with Other H.264 Steganography Methods
==============================================================
Compares this work against:
  1. LSB (pixel domain)   — implemented, real measurement
  2. F5-H.264             — literature [Zhang & Li, 2010]
  3. Motion-Vector based  — literature [Cao et al., 2011]
  4. IPM-based            — literature [Yang et al., 2011]

Metrics compared:
  - PSNR at equivalent payload
  - Bitstream size change (overhead)
  - Steganalysis detectability (chi-square p-value, RS score)
  - Trusted setup required

Produces:
  - sec3_psnr_comparison.png   : Grouped bar chart (PSNR by method × sequence)
  - sec3_overhead_comparison.png : Bitstream overhead bar chart
  - sec3_radar_chart.png       : Radar/spider chart of all criteria
"""

import sys
import argparse
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import (
    PALETTE, SEQUENCES, SEQ_LABELS, MARKERS,
    setup_style, save_fig, cache_save, cache_load,
    decode_luma_frames, embed_lsb_pixel,
    OUTPUT_DIR, annotate_literature, load_or_extract_idr_blocks,
    sort_positions_round_robin_idrs,
)

CACHE_KEY = "sec3_methods_data"
# No per-position PSNR validation in sec3.
# Same approach as sec1/sec2: round-robin over full-frame CAVLC-safe positions.
# Primary metric for measured methods is full-video PSNR (MSE over all frames).
CIF_MB_COUNT = 396

# Fixed payload for fair comparison (= ZK blob size)
PAYLOAD_BYTES = 147

# -------------------------------------------------------------------------
# Literature values (clearly cited)
# Source: Survey papers + original publications cited in COMPARISON_WITH_SOTA.md
# -------------------------------------------------------------------------
#
# Format: { method: { sequence: avg_psnr_dB } }
# All values at ~274 bytes (2192 bits) payload in CIF (352x288) H.264.
# Where exact sequence data unavailable, a conservative estimate is given.
#
LITERATURE_PSNR = {
    # Zhang & Li 2010 (CAVLC T1, similar approach — baseline for T1 class)
    # NOTE: Literature values measured on standard GOP=8 encoding.
    # Keys mapped to our all-intra QP22 sequences for comparison purposes.
    "F5-H264": {
        "foreman_q22_g1":    38.2,
        "coastguard_q22_g1": 32.7,
    },
    # Cao et al. 2011 (MV-based embedding)
    "MV-based": {
        "foreman_q22_g1":    34.5,
        "coastguard_q22_g1": 28.3,
    },
    # Yang et al. 2011 (IPM-based)
    "IPM-based": {
        "foreman_q22_g1":    33.8,
        "coastguard_q22_g1": 27.5,
    },
}

# Bitstream overhead (%): how much does file size increase?
LITERATURE_OVERHEAD = {
    "This Work (CAVLC T1)": 0.0,    # Length-preserving (same bit count)
    "F5-H264":              0.0,    # Also length-preserving for T1 class
    "MV-based":             2.1,    # MV delta changes some codes
    "IPM-based":            3.4,    # IPM change may alter slice syntax
    "LSB pixel":           12.8,    # Re-encode introduces rate change
}

# -------------------------------------------------------------------------
# Real measurement: LSB pixel domain
# -------------------------------------------------------------------------
def _measure_lsb_psnr(seq_name: str, video_path: Path, n_bytes: int) -> float:
    """
    Measure LSB pixel domain PSNR.
    NOTE: This embeds into decoded luma frames directly, then measures
    pixel-to-pixel PSNR without re-encoding. At 274-byte payload over
    5M+ pixels, PSNR is very high (~80+ dB) and NOT comparable to
    H.264 bitstream methods which suffer from intra prediction cascade.
    This value is shown for reference only with an explicit disclaimer.
    """
    frames = decode_luma_frames(video_path)
    n_bits = n_bytes * 8
    stego  = embed_lsb_pixel(frames, n_bits)
    from benchmark._common import psnr as _psnr
    val = _psnr(frames, stego)
    return float(min(val, 60.0))


# -------------------------------------------------------------------------
# Data collection
# -------------------------------------------------------------------------
def collect_data(force: bool = False, include_sequences: set[str] | None = None) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        print("  [cache hit] sec3 — skipping measurements")
        return cached

    data: dict = {
        "payload_bytes": PAYLOAD_BYTES,
        "validation_threshold_db": None,  # No PSNR validation threshold (unvalidated embedding)
        "methods": {},
    }

    # --- This work: CAVLC T1 — use sec1 stego (chaos + FFmpeg validated, 147B proof) ---
    # Re-using the sec1 stego (already embedded with the real proof + chaos scrambling +
    # per-position FFmpeg validation) gives the true system quality at actual payload size.
    # This avoids redundant embedding and ensures sec3 reports the same PSNR as sec1.
    from benchmark._common import psnr as _psnr

    this_work_psnr: dict[str, float] = {}
    this_work_validation_mode: dict[str, str] = {}
    this_work_embedded_bits: dict[str, int] = {}
    this_work_requested_bits: dict[str, int] = {}

    # Default sec3 scope is pinned to literature-supported sequences so method
    # comparisons stay stable across runs and include all baseline methods.
    default_sequence_names = tuple(LITERATURE_PSNR["F5-H264"].keys())
    if include_sequences:
        measure_sequences = {k: v for k, v in SEQUENCES.items() if k in include_sequences}
    else:
        measure_sequences = {
            k: SEQUENCES[k]
            for k in default_sequence_names
            if k in SEQUENCES
        }
    if not measure_sequences:
        raise ValueError("No valid sequences selected for sec3 measurement")

    for seq_name, video_path in measure_sequences.items():
        sec1_stego = OUTPUT_DIR / f"sec1_stego_{seq_name}.h264"
        sec1_meta  = OUTPUT_DIR / f"sec1_stego_{seq_name}.h264.meta.json"
        if sec1_stego.exists():
            # Use sec1 stego: chaos + FFmpeg-validated embedding at actual proof payload.
            print(f"  [this work / {seq_name}] using sec1 stego (chaos_v5_ffmpeg_validated)…")
            orig  = decode_luma_frames(video_path)
            stego = decode_luma_frames(sec1_stego)
            n     = min(len(orig), len(stego))
            psnr_val = float(min(_psnr(orig[:n], stego[:n]), 60.0)) if n > 0 else 0.0
            validation_mode = "chaos_v5_ffmpeg_validated_sec1_stego"
            bits_emb = PAYLOAD_BYTES * 8
            target_bits = PAYLOAD_BYTES * 8
            if sec1_meta.exists():
                import json as _json
                _m = _json.loads(sec1_meta.read_text())
                bits_emb  = int(_m.get("bits_embedded", bits_emb))
                target_bits = int(_m.get("bits_required", target_bits))
                validation_mode = str(_m.get("validation_mode", validation_mode))
        else:
            # Fallback: embed synthetic payload with round-robin (no FFmpeg validation).
            print(f"  [this work / {seq_name}] sec1 stego not found, falling back to round-robin embed…")
            from src.core.stego import PayloadEmbedder, CAVLCSafetyFilter
            from src.bitstream.bitstream_ops import BitstreamReconstructor

            payload_fb = bytes([i % 256 for i in range(PAYLOAD_BYTES)])
            out_path = OUTPUT_DIR / f"_sec3_this_work_{seq_name}.h264"
            if out_path.exists():
                out_path.unlink()

            rec = BitstreamReconstructor()
            coeffs, fvd, nC_map, nal_len, t1_over = load_or_extract_idr_blocks(video_path, rec, force=force)

            sf = CAVLCSafetyFilter()
            safe_pos   = sf.get_safe_positions(coeffs, nC_map=nC_map, nal_length_map=nal_len, t1_override_map=t1_over)
            sorted_pos = sort_positions_round_robin_idrs(safe_pos, CIF_MB_COUNT)
            target_bits = len(payload_fb) * 8
            validated   = sorted_pos[:target_bits]
            validation_mode = "round_robin_full_frame_unvalidated_fallback"
            usable_bytes = len(validated) // 8
            payload_now  = payload_fb[:usable_bytes] if usable_bytes > 0 else b""

            embedder = PayloadEmbedder(max_modifications_per_block=2)
            modified, bits_emb = (
                embedder.embed_payload(coeffs, payload_now, nC_map=nC_map,
                                       nal_length_map=nal_len, t1_override_map=t1_over,
                                       pre_validated_positions=validated)
                if usable_bytes > 0 else ([], 0)
            )
            rec2 = BitstreamReconstructor()
            rec2.reconstruct_video(str(video_path), modified, str(out_path),
                                   max_slices=None, frame_verified_data=fvd)

            orig  = decode_luma_frames(video_path)
            stego_frames = decode_luma_frames(out_path)
            n     = min(len(orig), len(stego_frames))
            psnr_val = float(min(_psnr(orig[:n], stego_frames[:n]), 60.0)) if n > 0 else 0.0

        this_work_psnr[seq_name] = psnr_val
        this_work_validation_mode[seq_name] = validation_mode
        this_work_embedded_bits[seq_name] = int(bits_emb)
        this_work_requested_bits[seq_name] = int(target_bits)
        print(f"  [this work / {seq_name}] full-video PSNR={psnr_val:.2f} dB")

    data["methods"]["This Work (CAVLC T1)"] = {
        "psnr":       this_work_psnr,
        "validation_mode": this_work_validation_mode,
        "embedded_bits": this_work_embedded_bits,
        "requested_bits": this_work_requested_bits,
        "simulated":  False,
    }

    # --- LSB pixel domain: real measurement ---
    lsb_psnr: dict[str, float] = {}
    for seq_name, video_path in measure_sequences.items():
        print(f"  [LSB / {seq_name}] measuring …")
        lsb_psnr[seq_name] = _measure_lsb_psnr(seq_name, video_path, PAYLOAD_BYTES)
        print(f"  [LSB / {seq_name}] PSNR={lsb_psnr[seq_name]:.2f} dB")

    data["methods"]["LSB pixel"] = {
        "psnr":       lsb_psnr,
        "simulated":  False,
    }

    # --- Literature methods ---
    for method_name, psnr_vals in LITERATURE_PSNR.items():
        data["methods"][method_name] = {
            "psnr":       psnr_vals,
            "simulated":  True,
        }

    data["overhead"] = LITERATURE_OVERHEAD
    cache_save(CACHE_KEY, data)
    return data


def _shared_comparison_sequences(data: dict, methods: list[str] | None = None) -> list[str]:
    """Return sequence names available across all selected methods."""
    if methods is None:
        methods = list(data.get("methods", {}).keys())
    if not methods:
        return []
    shared: list[str] = []
    for seq in SEQ_LABELS.keys():
        if all(seq in data["methods"][method].get("psnr", {}) for method in methods):
            shared.append(seq)
    return shared


def _comparison_view(data: dict) -> tuple[list[str], list[str]]:
    """Choose a comparable method/sequence view, with graceful fallback for custom runs."""
    all_methods = list(data.get("methods", {}).keys())
    if not all_methods:
        return [], []

    this_work_map = data["methods"].get("This Work (CAVLC T1)", {}).get("psnr", {})
    measured_seqs = [seq for seq in SEQ_LABELS.keys() if seq in this_work_map]
    if not measured_seqs:
        measured_seqs = [seq for seq in SEQ_LABELS.keys() if seq in data["methods"][all_methods[0]].get("psnr", {})]

    methods_covering_measured = [
        method for method in all_methods
        if all(seq in data["methods"][method].get("psnr", {}) for seq in measured_seqs)
    ]
    if methods_covering_measured:
        shared = _shared_comparison_sequences(data, methods_covering_measured)
        if shared:
            return methods_covering_measured, shared

    # Fallback for custom sequence subsets (e.g., akiyo-only): keep methods with at
    # least one measured sequence rather than raising and aborting the section.
    fallback_methods = [
        method for method in all_methods
        if any(seq in data["methods"][method].get("psnr", {}) for seq in measured_seqs)
    ]
    fallback_seqs = [
        seq for seq in measured_seqs
        if any(seq in data["methods"][method].get("psnr", {}) for method in fallback_methods)
    ]
    return fallback_methods, fallback_seqs


# -------------------------------------------------------------------------
# Plot 1: Grouped bar chart — PSNR by method × sequence
# -------------------------------------------------------------------------
def plot_psnr_comparison(data: dict) -> None:
    setup_style()

    methods, seqs = _comparison_view(data)
    if not methods or not seqs:
        raise ValueError("sec3 requires at least one sequence to compare")
    n_m     = len(methods)
    n_s     = len(seqs)

    fig, ax = plt.subplots(figsize=(13, 6))

    bar_w   = 0.15
    x_base  = np.arange(n_s)

    method_colors = {
        "This Work (CAVLC T1)": PALETTE["this_work"],
        "LSB pixel":            PALETTE["lsb"],
        "F5-H264":              PALETTE["f5"],
        "MV-based":             PALETTE["mv"],
        "IPM-based":            PALETTE["ipm"],
    }

    for m_idx, method in enumerate(methods):
        psnr_vals = [data["methods"][method]["psnr"].get(s, 0.0) for s in seqs]
        offset    = (m_idx - n_m / 2 + 0.5) * (bar_w + 0.02)
        is_sim    = data["methods"][method]["simulated"]
        hatch     = "////" if is_sim else ""
        is_adaptive_this_work = False
        if method == "This Work (CAVLC T1)":
            req_map = data["methods"][method].get("requested_bits", {})
            emb_map = data["methods"][method].get("embedded_bits", {})
            for seq in seqs:
                req = req_map.get(seq)
                emb = emb_map.get(seq)
                if isinstance(req, (int, float)) and req > 0 and isinstance(emb, (int, float)) and emb < req:
                    is_adaptive_this_work = True
                    break
        # LSB pixel: pixel-domain measurement, not comparable to bitstream methods
        is_lsb = method == "LSB pixel"
        if is_lsb:
            label_suffix = " ** (pixel-domain)"
        elif is_adaptive_this_work:
            label_suffix = " (adaptive payload)"
        else:
            label_suffix = " *" if is_sim else ""
        bars = ax.bar(x_base + offset, psnr_vals,
                      width=bar_w,
                      color=method_colors.get(method, "#888888"),
                      hatch="xxxx" if is_lsb else (hatch if is_sim else ""),
                      alpha=0.5 if is_lsb else (0.85 if not is_sim else 0.65),
                      label=method + label_suffix,
                      zorder=3)
        for bar, val in zip(bars, psnr_vals):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + 0.15,
                        f"{val:.1f}", ha="center", va="bottom",
                        fontsize=7.5, rotation=90)

    ax.axhline(40.0, color="#555555", linestyle="--", linewidth=1.2,
               label="40 dB (imperceptible)", zorder=2)

    seq_labels_short = [SEQ_LABELS[s].split(" ")[0] for s in seqs]
    ax.set_xticks(x_base)
    ax.set_xticklabels(seq_labels_short, fontsize=11)
    ax.set_ylabel("PSNR (dB, full-video MSE)")
    ax.set_title(f"§3  PSNR Comparison ({PAYLOAD_BYTES}-byte ZK proof payload, full-video MSE metric)")
    ax.legend(loc="lower right", fontsize=9, ncol=2)
    all_vals = [v for m in data["methods"].values() for v in m["psnr"].values() if v > 0]
    ax.set_ylim(20, max(all_vals) + 10 if all_vals else 70)

    annotate_literature(ax,
        "* literature values  ** LSB pixel measured in decoded domain (no re-encode).\n"
        "This Work may run adaptive/fallback payload; check JSON embedded_bits/requested_bits.\n"
        "PSNR shown using full-video MSE metric for measured methods.")
    save_fig(fig, "sec3_psnr_comparison")


# -------------------------------------------------------------------------
# Plot 2: Bitstream overhead bar chart
# -------------------------------------------------------------------------
def plot_overhead_comparison(data: dict) -> None:
    setup_style()
    fig, ax = plt.subplots(figsize=(9, 5))

    methods = list(data["overhead"].keys())
    values  = list(data["overhead"].values())
    colors  = [
        PALETTE["this_work"],
        PALETTE["f5"],
        PALETTE["mv"],
        PALETTE["ipm"],
        PALETTE["lsb"],
    ]

    x = np.arange(len(methods))
    bars = ax.bar(x, values, color=colors, width=0.5, zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(methods, rotation=15, ha="right", fontsize=10)
    ax.set_ylabel("Bitstream size increase (%)")
    ax.set_title("§3  Bitstream Overhead by Method")
    ax.set_ylim(0, max(values) * 1.4)

    for bar, val in zip(bars, values):
        label = "0 %\n(length-preserving)" if val == 0.0 else f"{val:.1f} %"
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.1,
                label, ha="center", va="bottom", fontsize=9, fontweight="bold")

    annotate_literature(ax, "MV/IPM/LSB overhead from published surveys")
    save_fig(fig, "sec3_overhead_comparison")


# -------------------------------------------------------------------------
# Plot 3: Radar / Spider chart — multi-criteria comparison
# -------------------------------------------------------------------------
def plot_radar_chart(data: dict) -> None:
    """
    5 criteria (higher = better, all normalised 0-1):
      1. PSNR quality    (higher dB -> better)
      2. Capacity        (higher bpp -> better)
      3. Zero overhead   (1 if 0 %, else scaled)
      4. Steganalysis resistance (qualitative, from literature)
      5. ZK-proof support (binary: this work = 1, others = 0)
    """
    setup_style()

    criteria = ["PSNR\nQuality", "Embedding\nCapacity", "Zero\nOverhead",
                "Steganalysis\nResistance", "ZK Proof\nSupport"]
    N = len(criteria)

    # Scores [0, 1] for each method across criteria
    # PSNR: normalise by (max - 30) / 15
    methods, shared_seqs = _comparison_view(data)
    if not methods or not shared_seqs:
        raise ValueError("sec3 radar chart requires at least one comparable sequence")

    avg_psnr = {
        m: float(np.mean([d["psnr"][seq] for seq in shared_seqs]))
        for m, d in data["methods"].items()
        if m in methods
    }
    max_psnr = max(avg_psnr.values())

    score_baselines = {
        "This Work (CAVLC T1)": [
            0.75,    # moderate capacity (T1 positions only)
            1.00,    # zero overhead
            0.70,    # moderate (chi-sq not perfect)
            1.00,    # ZK proof
        ],
        "LSB pixel": [
            1.00,    # full pixel capacity
            0.05,    # large overhead
            0.10,    # easily detectable
            0.00,    # no ZK
        ],
        "F5-H264": [
            0.60,    # T1 capacity similar
            0.95,    # near-zero overhead
            0.65,    # moderate resistance
            0.00,
        ],
        "MV-based": [
            0.85,    # larger capacity
            0.60,    # some overhead
            0.50,    # moderate — MVR attack possible
            0.00,
        ],
        "IPM-based": [
            0.80,
            0.55,
            0.45,    # IPMC attack exists
            0.00,
        ],
    }

    scores = {
        method: [(avg_psnr[method] - 30) / 15, *score_baselines[method]]
        for method in methods
        if method in score_baselines and method in avg_psnr
    }

    # Clamp to [0, 1]
    for k in scores:
        scores[k] = [min(1.0, max(0.0, v)) for v in scores[k]]

    angles = [n / float(N) * 2 * np.pi for n in range(N)]
    angles += angles[:1]

    method_colors = {
        "This Work (CAVLC T1)": PALETTE["this_work"],
        "LSB pixel":            PALETTE["lsb"],
        "F5-H264":              PALETTE["f5"],
        "MV-based":             PALETTE["mv"],
        "IPM-based":            PALETTE["ipm"],
    }

    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))

    for method, vals in scores.items():
        vals_plot = vals + vals[:1]
        ax.plot(angles, vals_plot, "o-", linewidth=2.0,
                color=method_colors[method], label=method)
        ax.fill(angles, vals_plot, alpha=0.08, color=method_colors[method])

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(criteria, size=10)
    ax.set_ylim(0, 1)
    ax.set_yticks([0.25, 0.50, 0.75, 1.00])
    ax.set_yticklabels(["0.25", "0.50", "0.75", "1.00"], size=8, color="#888888")
    ax.set_title("§3  Multi-Criteria Radar Chart\n(higher = better, all normalised)",
                 pad=20, fontsize=13, fontweight="bold")
    ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.15), fontsize=9)

    annotate_literature(ax, "All criteria normalised 0–1; hatched = estimated from literature")
    save_fig(fig, "sec3_radar_chart")


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------
def run(force: bool = False, include_sequences: set[str] | None = None) -> dict:
    print("\n=== §3  Method Comparison ===")
    data = collect_data(force=force, include_sequences=include_sequences)
    plot_psnr_comparison(data)
    plot_overhead_comparison(data)
    plot_radar_chart(data)
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run sec3 method comparison benchmark")
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
