"""
Section 9 — Motion-Aware GOP/Budget Auto-Selection (min PSNR 35 dB)
==================================================================

Automatically classifies video motion, chooses a GOP candidate from
available assets, validates positions with PSNR>=threshold, and embeds
full ZK payload when possible.

Outputs:
  - benchmark/results/sec9_motion_gop_data.json
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import (
    SEQUENCES,
    RESULTS_DIR,
    OUTPUT_DIR,
    decode_luma_frames,
    compute_quality_streaming,
    load_or_extract_idr_blocks,
    sort_positions_round_robin_idrs,
    CIF_MB_COUNT,
)

from benchmark.sec1_quality import _build_real_proof_payload, CHAOS_KEY
from src.core.chaos import ChaosTransformer
from src.core.stego import CAVLCSafetyFilter, PayloadEmbedder
from src.bitstream.bitstream_ops import BitstreamReconstructor

MIN_PSNR_DB = float(os.environ.get("SEC9_MIN_PSNR_DB", "35.0"))
MOTION_MAX_FRAMES = int(os.environ.get("SEC9_MOTION_MAX_FRAMES", "120"))
MOTION_STRIDE = max(1, int(os.environ.get("SEC9_MOTION_STRIDE", "4")))
MOTION_THRESHOLDS = os.environ.get("SEC9_MOTION_THRESHOLDS", "2.0,5.0")
HEADROOM_BITS = int(os.environ.get("SEC9_VALIDATION_HEADROOM_BITS", "128"))


@dataclass(frozen=True)
class MotionProfile:
    score: float
    label: str


@dataclass(frozen=True)
class TrialResult:
    sequence: str
    gop: int
    payload_bits: int
    embedded_bits: int | None
    payload_target_met: bool
    min_psnr: float | None
    avg_psnr: float | None
    full_psnr: float | None
    psnr_inf_frame_count: int
    runtime_sec: float
    note: str


def _parse_thresholds(text: str) -> tuple[float, float]:
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) != 2:
        return (2.0, 5.0)
    try:
        return (float(parts[0]), float(parts[1]))
    except ValueError:
        return (2.0, 5.0)


def _motion_score(frames: np.ndarray) -> float:
    if frames.shape[0] < 2:
        return 0.0
    indices = list(range(0, frames.shape[0], MOTION_STRIDE))
    if len(indices) < 2:
        indices = list(range(frames.shape[0]))
    diffs = []
    for i in range(1, len(indices)):
        prev_idx = indices[i - 1]
        cur_idx = indices[i]
        diff = np.mean(np.abs(frames[cur_idx] - frames[prev_idx]))
        diffs.append(float(diff))
    return float(np.mean(diffs)) if diffs else 0.0


def _classify_motion(score: float) -> str:
    low_th, mid_th = _parse_thresholds(MOTION_THRESHOLDS)
    if score < low_th:
        return "low"
    if score < mid_th:
        return "medium"
    return "high"


def _sequence_base(seq_name: str) -> str:
    if "_q" in seq_name and seq_name.endswith("_g1"):
        return seq_name.split("_q", 1)[0]
    return seq_name


def _gop_for_sequence(seq_name: str) -> int:
    if "_g1" in seq_name:
        return 1
    return 8


def _candidate_sequences(base: str) -> dict[int, str]:
    candidates: dict[int, str] = {}
    g8_key = base if base in SEQUENCES else None
    g1_key = f"{base}_q22_g1" if f"{base}_q22_g1" in SEQUENCES else None
    if g8_key:
        candidates[_gop_for_sequence(g8_key)] = g8_key
    if g1_key:
        candidates[_gop_for_sequence(g1_key)] = g1_key
    return candidates


def _gop_preference_by_motion(label: str) -> list[int]:
    if label == "low":
        return [8, 1]
    if label == "medium":
        return [8, 1]
    return [8, 1]


def _motion_profile_for_sequence(seq_name: str) -> MotionProfile:
    frames = decode_luma_frames(SEQUENCES[seq_name], max_frames=MOTION_MAX_FRAMES)
    score = _motion_score(frames)
    return MotionProfile(score=score, label=_classify_motion(score))


def _summarize_psnr(psnr_list: list[float]) -> tuple[float | None, float | None, int]:
    finite_vals = [p for p in psnr_list if np.isfinite(p)]
    inf_count = int(sum(1 for p in psnr_list if not np.isfinite(p)))
    if not finite_vals:
        return None, None, inf_count
    capped = [min(p, 60.0) for p in finite_vals] + [60.0] * inf_count
    return float(min(finite_vals)), float(np.mean(capped)), inf_count


def _validate_positions(
    video_path: Path,
    coeffs: list,
    safe_positions: list,
    fvd: dict,
    gop: int,
    target_bits: int,
) -> list:
    rec = BitstreamReconstructor()
    return rec.batch_psnr_validate(
        str(video_path),
        coeffs,
        safe_positions,
        frame_verified_data=fvd,
        psnr_threshold_db=MIN_PSNR_DB,
        max_bisect_iters=12,
        max_greedy_per_idr=128,
        min_local_mb=None,
        gop_span_frames=gop,
        gop_psnr_quantile=(0.2 if gop > 1 else 0.0),
        target_positions=target_bits + HEADROOM_BITS,
    )


def _build_positions(
    coeffs: list,
    nC_map: dict,
    nal_len: dict,
    t1_over: dict,
) -> list[tuple[int, int, int]]:
    sf = CAVLCSafetyFilter()
    safe_positions = sf.get_safe_positions(
        coeffs,
        nC_map=nC_map,
        nal_length_map=nal_len,
        t1_override_map=t1_over,
    )
    patchable_keys = {
        key for key, bit_len in nal_len.items()
        if key[1] < 16 and bit_len is not None and bit_len > 0
    }
    filtered = [
        p for p in safe_positions
        if (p[0], p[1]) in patchable_keys and p[2] >= 0
    ]
    ordered = sort_positions_round_robin_idrs(filtered, CIF_MB_COUNT)
    deduped: list[tuple[int, int, int]] = []
    seen_blocks: set[tuple[int, int]] = set()
    for mb, blk, cidx in ordered:
        key = (mb, blk)
        if key in seen_blocks:
            continue
        seen_blocks.add(key)
        deduped.append((mb, blk, cidx))
    return deduped


def _trial_sequence(seq_name: str, gop: int, payload_bits: int, payload: bytes) -> TrialResult:
    t0 = time.perf_counter()
    video_path = SEQUENCES[seq_name]
    rec = BitstreamReconstructor()
    coeffs, fvd, nC_map, nal_len, t1_over = load_or_extract_idr_blocks(video_path, rec)

    deduped_positions = _build_positions(coeffs, nC_map, nal_len, t1_over)
    validated = _validate_positions(
        video_path,
        coeffs,
        deduped_positions,
        fvd,
        gop,
        payload_bits,
    )

    if len(validated) < payload_bits:
        return TrialResult(
            sequence=seq_name,
            gop=gop,
            payload_bits=payload_bits,
            embedded_bits=None,
            payload_target_met=False,
            min_psnr=None,
            avg_psnr=None,
            full_psnr=None,
            psnr_inf_frame_count=0,
            runtime_sec=time.perf_counter() - t0,
            note=f"validated_positions={len(validated)} < payload_bits",
        )

    embed_positions = validated[:payload_bits]
    embedder = PayloadEmbedder(max_modifications_per_block=1)
    modified, bits_emb = embedder.embed_payload(
        coeffs,
        payload,
        nC_map=nC_map,
        nal_length_map=nal_len,
        t1_override_map=t1_over,
        pre_validated_positions=embed_positions,
    )

    out_path = OUTPUT_DIR / f"_sec9_{seq_name}_g{gop}.h264"
    rec2 = BitstreamReconstructor()
    rec2.reconstruct_video(
        str(video_path),
        modified,
        str(out_path),
        max_slices=None,
        frame_verified_data=fvd,
    )

    quality = compute_quality_streaming(video_path, out_path)
    min_psnr, avg_psnr, inf_count = _summarize_psnr(quality["psnr_per_frame"])
    full_psnr = float(min(quality["psnr_full_video"], 60.0))

    return TrialResult(
        sequence=seq_name,
        gop=gop,
        payload_bits=payload_bits,
        embedded_bits=int(bits_emb),
        payload_target_met=bool(int(bits_emb) >= payload_bits),
        min_psnr=min_psnr,
        avg_psnr=avg_psnr,
        full_psnr=full_psnr,
        psnr_inf_frame_count=inf_count,
        runtime_sec=time.perf_counter() - t0,
        note="ok",
    )


def _select_best(candidates: Iterable[TrialResult]) -> TrialResult | None:
    passing = [
        c for c in candidates
        if c.payload_target_met and c.min_psnr is not None and c.min_psnr >= MIN_PSNR_DB
    ]
    if passing:
        return sorted(passing, key=lambda r: (r.gop, r.min_psnr or 0.0), reverse=True)[0]
    if candidates:
        return sorted(candidates, key=lambda r: (r.min_psnr or 0.0), reverse=True)[0]
    return None


def run() -> dict:
    print("\n=== §9  Motion-Aware GOP/Budget Auto-Selection ===")
    payload_real, _ = _build_real_proof_payload()
    payload_scrambled, _ = ChaosTransformer(CHAOS_KEY).scramble(payload_real)
    payload_bits = len(payload_scrambled) * 8

    bases = ["foreman", "coastguard", "deadline"]
    results: dict[str, dict] = {}

    for base in bases:
        candidates = _candidate_sequences(base)
        if not candidates:
            print(f"  [{base}] no GOP candidates found — skip")
            continue

        motion_seq = candidates.get(8) or candidates.get(1)
        motion_profile = _motion_profile_for_sequence(motion_seq)
        gop_pref = _gop_preference_by_motion(motion_profile.label)

        ordered_candidates = []
        for gop in gop_pref:
            if gop in candidates:
                ordered_candidates.append((gop, candidates[gop]))
        if not ordered_candidates:
            ordered_candidates = list(sorted(candidates.items(), reverse=True))

        trial_results: list[TrialResult] = []
        for gop, seq_name in ordered_candidates:
            print(f"  [{base}] motion={motion_profile.label} score={motion_profile.score:.2f} -> gop={gop}")
            trial = _trial_sequence(seq_name, gop, payload_bits, payload_scrambled)
            trial_results.append(trial)
            status = "PASS" if trial.payload_target_met and (trial.min_psnr or 0.0) >= MIN_PSNR_DB else "FAIL"
            print(
                f"    - {seq_name} g{gop}: {status} min_psnr={trial.min_psnr} "
                f"full_psnr={trial.full_psnr} embedded={trial.embedded_bits}/{payload_bits}"
            )

        best = _select_best(trial_results)
        results[base] = {
            "motion": {
                "sequence": motion_seq,
                "score": motion_profile.score,
                "class": motion_profile.label,
            },
            "payload_bits": payload_bits,
            "min_psnr_db": MIN_PSNR_DB,
            "candidates": [trial.__dict__ for trial in trial_results],
            "selected": (best.__dict__ if best else None),
        }

    output_path = RESULTS_DIR / "sec9_motion_gop_data.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=True, indent=2)
    print(f"\n  [saved] {output_path}")
    return results


if __name__ == "__main__":
    run()
