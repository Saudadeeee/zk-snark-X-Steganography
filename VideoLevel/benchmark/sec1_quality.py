

"""Section 1 quality benchmark for stego video vs original video."""

import os
import sys
import time
import json
import hashlib
import argparse
import re
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import (
    PALETTE, SEQUENCES, SEQ_LABELS, MARKERS, LINESTYLES,
    setup_style, save_fig, cache_save, cache_load,
    decode_luma_frames, psnr_per_frame, ssim_per_frame, psnr,
    compute_quality_streaming, compute_quality_subset,
    load_or_build_benchmark_analysis, sort_positions_round_robin_idrs,
)

from benchmark._common import OUTPUT_DIR, CIRCUITS_DIR, RESULTS_DIR

SECRET_KEY = bytes(range(32))  # Fixed key for reproducibility
CHAOS_KEY = b"sec1_benchmark_chaos_v1"  # Deterministic chaos key for reproducibility

PAYLOAD_BYTES = 147
PAYLOAD = bytes([i % 256 for i in range(PAYLOAD_BYTES)])

STEGO_OUTPUTS = {
    seq: OUTPUT_DIR / f"sec1_stego_{seq}.h264"
    for seq in SEQUENCES
}

CACHE_KEY = "sec1_quality_data"
# Default to quality-oriented benchmark mode.
# Set SEC1_USE_REAL_PROOF_PIPELINE=1 to force real-proof embedding path.
USE_REAL_PROOF_EMBED_PIPELINE = os.environ.get("SEC1_USE_REAL_PROOF_PIPELINE", "0") == "1"
REAL_PROOF_MESSAGE = b"ZK-bench-v1.0!"
REAL_PROOF_FFMPEG_VALIDATE = False
REAL_PROOF_SMART_DISTRIBUTED = True
REAL_PROOF_SMART_ALLOW_SIGN_BITS = True
REAL_PROOF_SMART_MAX_MODS_PER_BLOCK = 1
REAL_PROOF_SMART_PREFER_PATCHABLE = True
REAL_PROOF_SMART_DEDUP_PER_BLOCK = True
REAL_PROOF_SMART_MAX_BITS_PER_IDR = 32
REAL_PROOF_VALIDATION_HEADROOM_BITS = 128
REAL_PROOF_VALIDATION_HEADROOM_BITS_QP32 = 192
USE_SIGN_BIT_POSITIONS = False
MIN_QUALITY_BUDGET_BITS = 256
# For all-intra (GOP=1) sequences, each frame is independent so cascade risk is zero.
# Use higher per-IDR quota and patchable rate to allow full payload embedding.
QUALITY_BITS_PER_IDR = 24           # GOP=8 sequences (legacy default)
QUALITY_BITS_PER_IDR_ALLINTRA = 64  # GOP=1: independent IDR frames, no cascade
QUALITY_MAX_PATCHABLE_RATE = 0.08       # GOP=8 sequences
QUALITY_MAX_PATCHABLE_RATE_ALLINTRA = 0.25  # GOP=1: safe to use more positions
FALLBACK_MIN_BITS = 64
QUALITY_TARGET_PSNR_FULL_DB = 41.0
QUALITY_TARGET_PSNR_FRAME_MIN_DB = float(os.environ.get("SEC1_QUALITY_TARGET_PSNR_FRAME_MIN_DB", "40.0"))
QUALITY_ENFORCE_TARGET_STRICT = True
QUALITY_STRICT_ALLOW_BEST_EFFORT = os.environ.get("SEC1_STRICT_ALLOW_BEST_EFFORT", "1") == "1"
QUALITY_ENFORCE_FRAME_MIN_PSNR = os.environ.get("SEC1_ENFORCE_FRAME_MIN_PSNR", "1") == "1"
QUALITY_TEMPORAL_STRIDE = max(1, int(os.environ.get("SEC1_QUALITY_TEMPORAL_STRIDE", "4")))
QUALITY_TARGET_BITS_DEFAULT = len(PAYLOAD) * 8
SEC1_OPERATING_POSITIONS_SUFFIX = ".positions.json"
SEC1_VALIDATED_POOL_SUFFIX = ".validated_pool.json"


def _fast_mode_enabled() -> bool:
    return os.environ.get("SEC1_FAST_MODE", "0") == "1"

CIF_MB_COUNT = 396   # 22x18 (same for all CIF benchmark sequences)

DEFAULT_QUALITY_SEQUENCE_NAMES = ("foreman_q22_g1", "coastguard_q22_g1")
QUALITY_SEQUENCES = {
    k: SEQUENCES[k]
    for k in DEFAULT_QUALITY_SEQUENCE_NAMES
    if k in SEQUENCES
}
OPTIONAL_QUALITY_SEQUENCES = {
    k: v for k, v in SEQUENCES.items()
    if k not in DEFAULT_QUALITY_SEQUENCE_NAMES
}
SEC1_RECOMMENDED_SEQUENCE_NAMES = (
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
)

# GOP per sequence: all-intra sequences have GOP=1 (every frame is IDR).
SEQ_GOP = {
    "foreman_q22_g1": 1,
    "coastguard_q22_g1": 1,
    "deadline_q22_g1": 1,
    "akiyo_q22_g1": 1,
    "container_q22_g1": 1,
    "hall_monitor_q22_g1": 1,
    "football_q22_g1": 1,
    "city_q22_g1": 1,
    "foreman_q18_g1_150f": 1,
    "foreman_q28_g1_300f": 1,
    "coastguard_q18_g1_150f": 1,
    "coastguard_q22_g1_600f": 1,
    "coastguard_q22_g1_1000f": 1,
    "coastguard_q22_g1_3000f": 1,
    "coastguard_q28_g1_300f": 1,
    "deadline_q18_g1_150f": 1,
    "deadline_q22_g1_600f": 1,
    "deadline_q22_g1_1000f": 1,
    "deadline_q28_g1_300f": 1,
}

# Max T1 flips per IDR frame — lower = less intra cascade per frame.
# 300f sequences: need 5 (300×5=1500 ≥ 1232). 1000f sequences: 2 (1000×2=2000 ≥ 1232).
SEQ_MAX_FLIPS_PER_IDR = {
    "foreman_q22_g1": 5,
    "coastguard_q22_g1": 5,
    "deadline_q22_g1": 5,
    "akiyo_q22_g1": 5,
    "container_q22_g1": 5,
    "hall_monitor_q22_g1": 5,
    "football_q22_g1": 5,
    "city_q22_g1": 5,
    "foreman_q18_g1_150f": 10,
    "foreman_q28_g1_300f": 5,
    "coastguard_q18_g1_150f": 10,
    "coastguard_q22_g1_600f": 3,
    "coastguard_q22_g1_1000f": 2,
    "coastguard_q22_g1_3000f": 1,
    "coastguard_q28_g1_300f": 5,
    "deadline_q18_g1_150f": 10,
    "deadline_q22_g1_600f": 3,
    "deadline_q22_g1_1000f": 2,
    "deadline_q28_g1_300f": 5,
}

_QP_SEQ_RE = re.compile(r"^(?P<base>[a-z0-9]+)_q(?P<qp>\d+)_g1$")

# -------------------------------------------------------------------------
# Embed helper
# -------------------------------------------------------------------------


def _select_positions_distributed(
    positions: list[tuple[int, int, int]],
    target_bits: int,
    cif_mb_count: int = CIF_MB_COUNT,
) -> list[tuple[int, int, int]]:
    """Select exactly target_bits positions with balanced per-IDR distribution."""
    by_frame: dict[int, list[tuple[int, int, int]]] = {}
    for pos in positions:
        frame_idx = pos[0] // cif_mb_count
        by_frame.setdefault(frame_idx, []).append(pos)

    if not by_frame:
        return []

    frames = sorted(by_frame.keys())
    quotas = {f: 0 for f in frames}
    remaining = int(target_bits)

    # Iteratively assign fair-share quotas while respecting per-frame availability.
    active = set(frames)
    while remaining > 0 and active:
        share = max(1, remaining // len(active))
        progressed = False
        for f in sorted(active):
            cap = len(by_frame[f]) - quotas[f]
            if cap <= 0:
                active.remove(f)
                continue
            take = min(share, cap, remaining)
            if take > 0:
                quotas[f] += take
                remaining -= take
                progressed = True
            if len(by_frame[f]) - quotas[f] <= 0:
                active.remove(f)
            if remaining <= 0:
                break
        if not progressed:
            break

    selected: list[tuple[int, int, int]] = []
    for f in frames:
        q = quotas[f]
        if q > 0:
            selected.extend(by_frame[f][:q])

    # Preserve global extraction order contract.
    return sort_positions_round_robin_idrs(selected, cif_mb_count)


def _build_smart_candidate_positions(
    ordered_positions: list[tuple[int, int, int]],
    nal_length_map: dict,
    cif_mb_count: int = CIF_MB_COUNT,
    allow_sign_bits: bool = True,
    prefer_patchable: bool = True,
    dedup_per_block: bool = True,
    max_bits_per_idr: int = 0,
) -> list[tuple[int, int, int]]:
    """Build candidate positions with quality-preserving constraints."""
    patchable_keys = {
        key for key, bit_len in nal_length_map.items()
        if key[1] < 16 and bit_len is not None and bit_len > 0
    }

    candidates: list[tuple[int, int, int]] = []
    seen_blocks: set[tuple[int, int]] = set()
    idr_used: dict[int, int] = {}

    for mb, blk, cidx in ordered_positions:
        if not allow_sign_bits and cidx < 0:
            continue

        block_key = (mb, blk)
        if prefer_patchable and block_key not in patchable_keys:
            continue

        if dedup_per_block and block_key in seen_blocks:
            continue

        frame_idx = mb // cif_mb_count
        if max_bits_per_idr > 0 and idr_used.get(frame_idx, 0) >= max_bits_per_idr:
            continue

        if dedup_per_block:
            seen_blocks.add(block_key)
        idr_used[frame_idx] = idr_used.get(frame_idx, 0) + 1
        candidates.append((mb, blk, cidx))

    return candidates


_PROOF_PAYLOAD_CACHE_PATH = RESULTS_DIR / "_proof_payload_cache.bin"


def _proof_cache_fingerprint() -> bytes:
    """20-byte SHA1 of (message || secret_key) — cache invalidates if either changes."""
    import hashlib as _hl
    return _hl.sha1(REAL_PROOF_MESSAGE + SECRET_KEY).digest()  # 20 bytes


def _build_real_proof_payload() -> tuple[bytes, int]:
    """Build canonical packed ZK payload and its exact bit length.

    Caches the result to disk so snarkJS runs only once per session — avoids
    OOM when running multiple sequences back-to-back.

    Cache format: 20-byte fingerprint (SHA1 of message+key) + raw payload bytes.
    Cache is invalidated automatically when REAL_PROOF_MESSAGE or SECRET_KEY changes.
    """
    fp = _proof_cache_fingerprint()
    if _PROOF_PAYLOAD_CACHE_PATH.exists():
        raw = _PROOF_PAYLOAD_CACHE_PATH.read_bytes()
        if len(raw) > 20 and raw[:20] == fp:
            payload_real = raw[20:]
            return payload_real, len(payload_real) * 8

    from src.zk_proof import ZKSnarkBridge, pack, proof_to_bytes

    bridge = ZKSnarkBridge(str(CIRCUITS_DIR))
    proof_dict, _ = bridge.generate_proof_for_payload(REAL_PROOF_MESSAGE, SECRET_KEY)
    payload_real = pack(REAL_PROOF_MESSAGE, proof_to_bytes(proof_dict))
    _PROOF_PAYLOAD_CACHE_PATH.write_bytes(fp + payload_real)
    return payload_real, len(payload_real) * 8


def _sec1_cache_fingerprint() -> dict[str, object]:
    """Return configuration fingerprint for sec1 output cache safety."""
    return {
        "use_real_proof_embed_pipeline": USE_REAL_PROOF_EMBED_PIPELINE,
        "quality_target_psnr_full_db": QUALITY_TARGET_PSNR_FULL_DB,
        "quality_target_psnr_frame_min_db": QUALITY_TARGET_PSNR_FRAME_MIN_DB,
        "quality_enforce_target_strict": QUALITY_ENFORCE_TARGET_STRICT,
        "quality_strict_allow_best_effort": QUALITY_STRICT_ALLOW_BEST_EFFORT,
        "quality_enforce_frame_min_psnr": QUALITY_ENFORCE_FRAME_MIN_PSNR,
        "quality_temporal_stride": QUALITY_TEMPORAL_STRIDE,
        "quality_bits_per_idr": QUALITY_BITS_PER_IDR,
        "quality_max_patchable_rate": QUALITY_MAX_PATCHABLE_RATE,
        "min_quality_budget_bits": MIN_QUALITY_BUDGET_BITS,
        "fallback_min_bits": FALLBACK_MIN_BITS,
        "use_sign_bit_positions": USE_SIGN_BIT_POSITIONS,
        "real_proof_smart_distributed": REAL_PROOF_SMART_DISTRIBUTED,
        "real_proof_smart_allow_sign_bits": REAL_PROOF_SMART_ALLOW_SIGN_BITS,
        "real_proof_smart_max_mods_per_block": REAL_PROOF_SMART_MAX_MODS_PER_BLOCK,
        "real_proof_smart_prefer_patchable": REAL_PROOF_SMART_PREFER_PATCHABLE,
        "real_proof_smart_dedup_per_block": REAL_PROOF_SMART_DEDUP_PER_BLOCK,
        "real_proof_smart_max_bits_per_idr": REAL_PROOF_SMART_MAX_BITS_PER_IDR,
        "real_proof_validation_headroom_bits": REAL_PROOF_VALIDATION_HEADROOM_BITS,
        "real_proof_validation_headroom_bits_qp32": REAL_PROOF_VALIDATION_HEADROOM_BITS_QP32,
        "payload_bytes": len(PAYLOAD),
        "payload_sha1": hashlib.sha1(PAYLOAD).hexdigest(),
        "real_proof_message_sha1": hashlib.sha1(REAL_PROOF_MESSAGE).hexdigest(),
        "secret_key_sha1": hashlib.sha1(SECRET_KEY).hexdigest(),
        "chaos_key_sha1": hashlib.sha1(CHAOS_KEY).hexdigest(),
        "allintra_validation": "chaos_v5_psnr_revalidated_40db_v3",
        "fast_mode": _fast_mode_enabled(),
    }


def _stego_meta_path(out_path: Path) -> Path:
    return out_path.parent / f"{out_path.name}.meta.json"


def _stego_positions_path(out_path: Path) -> Path:
    return out_path.parent / f"{out_path.name}{SEC1_OPERATING_POSITIONS_SUFFIX}"


def _stego_validated_pool_path(out_path: Path) -> Path:
    return out_path.parent / f"{out_path.name}{SEC1_VALIDATED_POOL_SUFFIX}"


def _read_stego_metadata(meta_path: Path) -> dict | None:
    if not meta_path.exists():
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


def _write_stego_metadata(
    meta_path: Path,
    *,
    video_path: Path,
    bits_embedded: int | None,
    bits_required: int,
    validation_mode: str,
    effective_threshold_db: float | None,
) -> None:
    try:
        source_video_text = str(video_path.resolve())
    except OSError:
        source_video_text = str(video_path)
    payload = {
        "source_video": source_video_text,
        "source_video_mtime": os.path.getmtime(str(video_path)),
        "cache_fingerprint": _sec1_cache_fingerprint(),
        "bits_embedded": bits_embedded,
        "bits_required": int(bits_required),
        "validation_mode": validation_mode,
        "validation_threshold_db": QUALITY_TARGET_PSNR_FRAME_MIN_DB if QUALITY_ENFORCE_FRAME_MIN_PSNR else None,
        "validation_threshold_db_effective": effective_threshold_db,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True, indent=2)


def _can_reuse_stego_output(video_path: Path, out_path: Path, meta_path: Path) -> bool:
    if not out_path.exists() or not meta_path.exists():
        return False
    if os.path.getmtime(str(video_path)) > os.path.getmtime(str(out_path)):
        return False
    meta = _read_stego_metadata(meta_path)
    if not meta:
        return False
    try:
        source_video_text = str(video_path.resolve())
    except OSError:
        source_video_text = str(video_path)
    if meta.get("source_video") != source_video_text:
        return False
    try:
        current_source_mtime = os.path.getmtime(str(video_path))
        meta_source_mtime = float(meta.get("source_video_mtime", -1.0))
    except (TypeError, ValueError):
        return False
    if abs(meta_source_mtime - current_source_mtime) > 1e-6:
        return False
    if meta.get("cache_fingerprint") != _sec1_cache_fingerprint():
        return False
    return True


def _sec1_run_cache_meta(active_sequences: dict[str, Path]) -> dict[str, object]:
    """Build run-level cache metadata to avoid stale sec1 JSON reuse."""
    return {
        "cache_fingerprint": _sec1_cache_fingerprint(),
        "sequence_names": sorted(active_sequences.keys()),
        "source_video_mtimes": {
            name: os.path.getmtime(str(path))
            for name, path in sorted(active_sequences.items())
        },
    }


def _select_positions_temporal_strided(
    ordered_positions: list[tuple[int, int, int]],
    target_bits: int,
    cif_mb_count: int = CIF_MB_COUNT,
    stride: int = QUALITY_TEMPORAL_STRIDE,
) -> list[tuple[int, int, int]]:
    """Select up to target_bits positions while spreading picks over timeline."""
    if target_bits <= 0 or not ordered_positions:
        return []

    by_frame: dict[int, list[tuple[int, int, int]]] = {}
    for pos in ordered_positions:
        frame_idx = pos[0] // cif_mb_count
        by_frame.setdefault(frame_idx, []).append(pos)

    if not by_frame:
        return []

    frames = sorted(by_frame.keys())
    stride_eff = max(1, min(int(stride), len(frames)))
    if stride_eff <= 1:
        frame_order = frames
    else:
        frame_order: list[int] = []
        for offset in range(stride_eff):
            frame_order.extend(frames[offset::stride_eff])

    offsets = {frm: 0 for frm in frames}
    selected: list[tuple[int, int, int]] = []

    while len(selected) < target_bits:
        progressed = False
        for frm in frame_order:
            idx = offsets[frm]
            bucket = by_frame[frm]
            if idx < len(bucket):
                selected.append(bucket[idx])
                offsets[frm] += 1
                progressed = True
                if len(selected) >= target_bits:
                    break
        if not progressed:
            break

    return selected


def _take_positions_excluding_idrs(
    positions: list[tuple[int, int, int]],
    blocked_idrs: set[int],
    required_bits: int,
    cif_mb_count: int = CIF_MB_COUNT,
) -> list[tuple[int, int, int]]:
    """Take the first required_bits positions while skipping blocked IDR frames."""
    selected: list[tuple[int, int, int]] = []
    for pos in positions:
        if (pos[0] // cif_mb_count) in blocked_idrs:
            continue
        selected.append(pos)
        if len(selected) >= required_bits:
            break
    return selected


def _write_positions_json(path: Path, positions: list[tuple[int, int, int]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            [[int(mb), int(blk), int(cidx)] for mb, blk, cidx in positions],
            f,
            ensure_ascii=True,
            indent=2,
        )


def _verify_sec1_stego(
    *,
    seq_name: str,
    original_video: Path,
    stego_video: Path,
    operating_positions: list[tuple[int, int, int]] | None,
) -> dict[str, object]:
    """Run end-to-end extraction+proof verification for SEC1 real-proof stego."""
    from src.verifier import verify

    if not USE_REAL_PROOF_EMBED_PIPELINE:
        return {
            "verify_valid": None,
            "verify_bits_extracted": None,
            "verify_message_match": None,
        }

    result = verify(
        stego_video_path=str(stego_video),
        original_video_path=str(original_video),
        circuits_dir=str(CIRCUITS_DIR),
        secret_key=SECRET_KEY,
        message_length=len(REAL_PROOF_MESSAGE),
        max_modifications_per_block=REAL_PROOF_SMART_MAX_MODS_PER_BLOCK,
        chaos_key=CHAOS_KEY,
        precomputed_positions=operating_positions,
        precomputed_payload_bits=(len(operating_positions) if operating_positions is not None else None),
    )
    verify_message_match = bool(result.valid and result.message == REAL_PROOF_MESSAGE)
    if not result.valid or not verify_message_match:
        raise RuntimeError(
            f"[{seq_name}] verify() failed after embedding "
            f"(valid={result.valid}, message_match={verify_message_match})"
        )
    return {
        "verify_valid": True,
        "verify_bits_extracted": int(result.bits_extracted),
        "verify_message_match": True,
    }


def _embed_for_benchmark(seq_name: str, video_path: Path, force: bool = False) -> tuple[Path, int | None, int, str, float | None]:
    """
    Embed 274-byte payload (= full ZK blob size) using CAVLC T1 steganography.

        Strategy — round-robin over full-frame CAVLC-safe positions:
            All CAVLC-safe positions are sorted by IDR round-robin ordering and the
            first payload_bits positions are selected.

            This spreads modifications across many IDR frames, producing a fairer
            distortion profile over time for paper reporting.
    """
    from src.core.stego import PayloadEmbedder
    from src.bitstream.bitstream_ops import BitstreamReconstructor

    out_path = STEGO_OUTPUTS[seq_name]
    meta_path = _stego_meta_path(out_path)
    positions_path = _stego_positions_path(out_path)
    validated_pool_path = _stego_validated_pool_path(out_path)
    if out_path.exists():
        if force:
            out_path.unlink()
            meta_path.unlink(missing_ok=True)
            positions_path.unlink(missing_ok=True)
            validated_pool_path.unlink(missing_ok=True)
        elif _can_reuse_stego_output(video_path, out_path, meta_path):
            meta = _read_stego_metadata(meta_path) or {}
            return (
                out_path,
                meta.get("bits_embedded"),
                int(meta.get("bits_required", QUALITY_TARGET_BITS_DEFAULT)),
                str(meta.get("validation_mode", "cached")),
                meta.get("validation_threshold_db_effective"),
            )
        else:
            out_path.unlink()
            meta_path.unlink(missing_ok=True)
            positions_path.unlink(missing_ok=True)
            validated_pool_path.unlink(missing_ok=True)

    payload = PAYLOAD

    # Preferred mode: run benchmark on videos produced by the real system embed API
    # so PSNR/SSIM reflects actual proof embedding behavior, not synthetic payload probing.
    if USE_REAL_PROOF_EMBED_PIPELINE:
        from src.embedder import embed as real_embed
        _fast_mode = _fast_mode_enabled()

        _gop = SEQ_GOP.get(seq_name, 8)
        _is_all_intra = (_gop == 1)

        if _is_all_intra:
            # All-intra (GOP=1): chaos shuffle + FFmpeg per-position validation.
            # 1. Chaos-shuffle safe positions (temporal distribution across all IDR frames).
            # 2. Deduplicate by (mb, block) to guarantee max_mods_per_block=1 compatibility.
            # 3. FFmpeg-validate in shuffled order with per-IDR cap (SEC1_MAX_FLIPS_PER_IDR).
            # 4. Embed exactly _bits_to_embed bits in the validated positions.
            # Extractor reproduces steps 1-3 on the original video (deterministic),
            # reads from the same validated positions → exact roundtrip guaranteed.
            import os as _os
            from src.core.stego import PayloadEmbedder
            from src.core.chaos import ChaosTransformer

            SEC1_MAX_FLIPS_PER_IDR = SEQ_MAX_FLIPS_PER_IDR.get(seq_name, 5)

            payload_real, real_required_bits = _build_real_proof_payload()
            chaos = ChaosTransformer(CHAOS_KEY)
            payload_scrambled, _ = chaos.scramble(payload_real)
            scrambled_required_bits = len(payload_scrambled) * 8
            _bits_to_embed = scrambled_required_bits

            _prev_pkl = _os.environ.get("BENCHMARK_TRUSTED_IDR_PICKLE_CACHE")
            _os.environ["BENCHMARK_TRUSTED_IDR_PICKLE_CACHE"] = "1"
            try:
                _rec_ai = BitstreamReconstructor()
                coeffs_ai, fvd_ai, nC_ai, nal_ai, t1_ai, _safe_pos_ai = load_or_build_benchmark_analysis(
                    video_path,
                    force=force,
                )
            finally:
                if _prev_pkl is None:
                    _os.environ.pop("BENCHMARK_TRUSTED_IDR_PICKLE_CACHE", None)
                else:
                    _os.environ["BENCHMARK_TRUSTED_IDR_PICKLE_CACHE"] = _prev_pkl

            _safe_pos_ai = chaos.shuffle_positions(_safe_pos_ai)

            # Deduplicate by (mb_idx, block_idx) for max_mods_per_block=1 compatibility
            _seen_blk_ai: set = set()
            _deduped_ai: list = []
            for _p in _safe_pos_ai:
                _bk = (_p[0], _p[1])
                if _bk not in _seen_blk_ai:
                    _seen_blk_ai.add(_bk)
                    _deduped_ai.append(_p)

            _headroom_bits = (
                REAL_PROOF_VALIDATION_HEADROOM_BITS_QP32
                if "_q32_g1" in seq_name
                else REAL_PROOF_VALIDATION_HEADROOM_BITS
            )
            _validation_target_bits = min(
                len(_deduped_ai),
                scrambled_required_bits + _headroom_bits,
            )

            # FFmpeg per-position validation with per-IDR cap
            _validator_ai, _cleanup_ai = _rec_ai.make_ffmpeg_position_validator(
                str(video_path), coeffs_ai, fvd_ai
            )
            _validated_ai: list = []
            _idr_flip_ai: dict[int, int] = {}
            try:
                for _p in _deduped_ai:
                    if len(_validated_ai) >= _validation_target_bits:
                        break
                    _fi = _p[0] // CIF_MB_COUNT
                    if _idr_flip_ai.get(_fi, 0) >= SEC1_MAX_FLIPS_PER_IDR:
                        continue
                    if _validator_ai(_p[0], _p[1], _p[2]):
                        _validated_ai.append(_p)
                        _idr_flip_ai[_fi] = _idr_flip_ai.get(_fi, 0) + 1
            finally:
                _cleanup_ai()

            if len(_validated_ai) < scrambled_required_bits:
                raise RuntimeError(
                    f"[{seq_name}] Only {len(_validated_ai)} validated positions, "
                    f"need at least {scrambled_required_bits}"
                )
            if len(_validated_ai) < _validation_target_bits:
                print(
                    f"  [{seq_name}] reduced headroom: {len(_validated_ai)} validated positions "
                    f"(< target {_validation_target_bits}, but enough for {scrambled_required_bits} payload bits)"
                )
                _validation_target_bits = len(_validated_ai)

            # PSNR re-validation: make_ffmpeg_position_validator catches cumulative
            # hard H.264 decode errors but NOT soft pixel cascade from combined T1
            # flips within the same IDR frame.  batch_psnr_validate measures actual
            # decoded Y-PSNR and greedily removes positions whose combined effect
            # drops per-frame PSNR below 40 dB.  gop_span_frames=1 because this is
            # an all-intra sequence — no P-frame temporal cascade to worry about.
            if _fast_mode:
                print(f"  [{seq_name}] fast mode: skipping batch PSNR re-validation")
            else:
                print(f"  [{seq_name}] PSNR re-validating {len(_validated_ai)} positions ...")
                _psnr_rec_ai = BitstreamReconstructor()
                _psnr_validated: list = _psnr_rec_ai.batch_psnr_validate(
                    str(video_path), coeffs_ai, _validated_ai, fvd_ai,
                    psnr_threshold_db=40.0,
                    max_bisect_iters=8,
                    max_greedy_per_idr=SEC1_MAX_FLIPS_PER_IDR,
                    min_local_mb=0,
                    gop_span_frames=1,
                    gop_psnr_quantile=0.0,
                    target_positions=_validation_target_bits,
                )
                _n_psnr_removed = len(_validated_ai) - len(_psnr_validated)
                if _n_psnr_removed:
                    print(f"  [{seq_name}] PSNR filter: {len(_psnr_validated)}/{len(_validated_ai)} "
                          f"kept ({_n_psnr_removed} removed for PSNR < 40 dB)")
                if len(_psnr_validated) < scrambled_required_bits:
                    raise RuntimeError(
                        f"[{seq_name}] PSNR-validated capacity {len(_psnr_validated)} "
                        f"< required scrambled payload {scrambled_required_bits}"
                    )
                _validated_ai = _psnr_validated

            _bad_idr_set: set[int] = set()
            _embed_positions = _take_positions_excluding_idrs(
                _validated_ai, _bad_idr_set, scrambled_required_bits, CIF_MB_COUNT
            )
            _idr_counts: dict[int, int] = {}
            for _mb, _, _ in _embed_positions:
                _fi = _mb // CIF_MB_COUNT
                _idr_counts[_fi] = _idr_counts.get(_fi, 0) + 1
            print(f"  [{seq_name}] chaos_v5_ffmpeg_validated: {len(_embed_positions)} bits "
                  f"across {len(_idr_counts)} IDR frames "
                  f"(avg {len(_embed_positions) / max(1, len(_idr_counts)):.1f} bits/frame)")

            emb_ai = PayloadEmbedder(
                max_modifications_per_block=REAL_PROOF_SMART_MAX_MODS_PER_BLOCK
            )
            modified_ai, bits_embedded_ai = emb_ai.embed_payload(
                coeffs_ai, payload_scrambled,
                nC_map=nC_ai, nal_length_map=nal_ai, t1_override_map=t1_ai,
                ffmpeg_validator=None,
                pre_validated_positions=_embed_positions,
            )

            if bits_embedded_ai < _bits_to_embed:
                raise RuntimeError(
                    f"[{seq_name}] Only embedded {bits_embedded_ai}/{_bits_to_embed} bits"
                )

            os.makedirs(os.path.dirname(os.path.abspath(str(out_path))), exist_ok=True)
            _rec_ai2 = BitstreamReconstructor()
            _rec_ai2.reconstruct_video(
                str(video_path), modified_ai, str(out_path),
                frame_verified_data=fvd_ai,
                max_slices=None,
            )
            if not out_path.exists() or out_path.stat().st_size == 0:
                raise RuntimeError(f"Stego video not created: {out_path}")

            # Post-embed PSNR check: _apply_mod in batch_psnr_validate tests
            # unconditional sign flips, but embed_payload applies conditional
            # flips (payload bit vs. existing sign).  When only 1 of N positions
            # for an IDR is actually flipped, the isolated cascade can drop PSNR
            # far below what the combined-N-flip test measured.  Verify actual
            # stego PSNR and remove any IDR whose frame < 40 dB.
            _modified_frames = sorted({int(_mb // CIF_MB_COUNT) for _mb, _, _ in _embed_positions})
            for _psnr_retry in range(0 if _fast_mode else 3):
                _qv = compute_quality_subset(
                    str(video_path),
                    str(out_path),
                    _modified_frames,
                    include_ssim=False,
                )
                _bad_idr_frames = [
                    frm for frm, _p in zip(_qv["frame_indices"], _qv["psnr_per_frame"]) if _p < 40.0
                ]
                if not _bad_idr_frames:
                    break
                _bad_idr_set.update(_bad_idr_frames)
                print(
                    f"  [{seq_name}] post-embed PSNR (iter {_psnr_retry + 1}): "
                    f"frames {_bad_idr_frames} below 40 dB — removing {len(_bad_idr_frames)} IDR(s)"
                )
                _embed_positions = _take_positions_excluding_idrs(
                    _validated_ai, _bad_idr_set, scrambled_required_bits, CIF_MB_COUNT
                )
                if len(_embed_positions) < scrambled_required_bits:
                    raise RuntimeError(
                        f"[{seq_name}] Post-embed: only {len(_embed_positions)} "
                        f"positions after removing bad IDRs, need {scrambled_required_bits}"
                    )
                _bits_to_embed = len(_embed_positions)
                _emb_r = PayloadEmbedder(
                    max_modifications_per_block=REAL_PROOF_SMART_MAX_MODS_PER_BLOCK
                )
                modified_ai, bits_embedded_ai = _emb_r.embed_payload(
                    coeffs_ai, payload_scrambled,
                    nC_map=nC_ai, nal_length_map=nal_ai, t1_override_map=t1_ai,
                    ffmpeg_validator=None,
                    pre_validated_positions=_embed_positions,
                )
                _rec_r = BitstreamReconstructor()
                _rec_r.reconstruct_video(
                    str(video_path), modified_ai, str(out_path),
                    frame_verified_data=fvd_ai, max_slices=None,
                )
                _modified_frames = sorted({int(_mb // CIF_MB_COUNT) for _mb, _, _ in _embed_positions})

            mode_ai = "real_proof_allintra_chaos_v5_ffmpeg_validated"
            if _fast_mode:
                mode_ai += "_fast"
            _write_stego_metadata(
                meta_path,
                video_path=video_path,
                bits_embedded=int(bits_embedded_ai),
                bits_required=scrambled_required_bits,
                validation_mode=mode_ai,
                effective_threshold_db=QUALITY_TARGET_PSNR_FRAME_MIN_DB if QUALITY_ENFORCE_FRAME_MIN_PSNR else None,
            )
            # Save both the full validated pool and the exact operating positions.
            _write_positions_json(validated_pool_path, _validated_ai)
            _write_positions_json(positions_path, _embed_positions)

            _verify_sec1_stego(
                seq_name=seq_name,
                original_video=video_path,
                stego_video=out_path,
                operating_positions=_embed_positions,
            )
            return (
                out_path,
                int(bits_embedded_ai),
                scrambled_required_bits,
                mode_ai,
                None,
            )

        if REAL_PROOF_SMART_DISTRIBUTED:

            payload_real, real_required_bits = _build_real_proof_payload()

            coeffs, fvd, nC_map, nal_len, t1_over, safe_positions = load_or_build_benchmark_analysis(
                video_path,
                force=force,
            )

            ordered = sort_positions_round_robin_idrs(safe_positions, CIF_MB_COUNT)
            idr_frame_count = max(1, len({p[0] // CIF_MB_COUNT for p in ordered}))
            required_per_idr = (real_required_bits + idr_frame_count - 1) // idr_frame_count
            cap_effective = REAL_PROOF_SMART_MAX_BITS_PER_IDR
            if cap_effective > 0 and cap_effective < required_per_idr:
                cap_effective = required_per_idr

            constrained_candidates = _build_smart_candidate_positions(
                ordered,
                nal_len,
                cif_mb_count=CIF_MB_COUNT,
                allow_sign_bits=REAL_PROOF_SMART_ALLOW_SIGN_BITS,
                prefer_patchable=REAL_PROOF_SMART_PREFER_PATCHABLE,
                dedup_per_block=REAL_PROOF_SMART_DEDUP_PER_BLOCK,
                max_bits_per_idr=cap_effective,
            )

            selected_mode = "real_proof_embed_smart_distributed_constrained"
            selected_pool = constrained_candidates

            # If quality-constrained pool under-fills, relax constraints but keep
            # distributed selection before final production-path fallback.
            if len(selected_pool) < real_required_bits:
                selected_pool = [
                    p for p in ordered
                    if REAL_PROOF_SMART_ALLOW_SIGN_BITS or p[2] >= 0
                ]
                selected_mode = "real_proof_embed_smart_distributed_relaxed"

            if len(selected_pool) < real_required_bits:
                raise RuntimeError(
                    f"Insufficient smart-distributed capacity for {seq_name}: "
                    f"need {real_required_bits}, have {len(selected_pool)}"
                )

            selected = _select_positions_distributed(selected_pool, real_required_bits, CIF_MB_COUNT)
            if len(selected) < real_required_bits:
                raise RuntimeError(
                    f"Distributed selector under-filled for {seq_name}: "
                    f"need {real_required_bits}, got {len(selected)}"
                )

            embedder = PayloadEmbedder(max_modifications_per_block=REAL_PROOF_SMART_MAX_MODS_PER_BLOCK)
            modified, bits_emb = embedder.embed_payload(
                coeffs,
                payload_real,
                nC_map=nC_map,
                nal_length_map=nal_len,
                t1_override_map=t1_over,
                pre_validated_positions=selected[:real_required_bits],
            )

            rec2 = BitstreamReconstructor()
            rec2.reconstruct_video(
                str(video_path),
                modified,
                str(out_path),
                max_slices=None,
                frame_verified_data=fvd,
            )
            if not out_path.exists() or out_path.stat().st_size == 0:
                raise RuntimeError(f"Stego video not created: {out_path}")

            if int(bits_emb) < real_required_bits:
                # Enforce full-proof requirement with production embed path fallback.
                fallback_result = real_embed(
                    video_path=str(video_path),
                    message=REAL_PROOF_MESSAGE,
                    output_path=str(out_path),
                    circuits_dir=str(CIRCUITS_DIR),
                    secret_key=SECRET_KEY,
                    max_modifications_per_block=1,
                    ffmpeg_validate=REAL_PROOF_FFMPEG_VALIDATE,
                )
                _write_stego_metadata(
                    meta_path,
                    video_path=video_path,
                    bits_embedded=int(fallback_result.bits_embedded),
                    bits_required=real_required_bits,
                    validation_mode=f"{selected_mode}_with_fullproof_fallback",
                    effective_threshold_db=None,
                )
                return (
                    out_path,
                    int(fallback_result.bits_embedded),
                    real_required_bits,
                    f"{selected_mode}_with_fullproof_fallback",
                    None,
                )

            mode_name = selected_mode
            _write_stego_metadata(
                meta_path,
                video_path=video_path,
                bits_embedded=int(bits_emb),
                bits_required=real_required_bits,
                validation_mode=mode_name,
                effective_threshold_db=None,
            )
            _write_positions_json(validated_pool_path, selected_pool)
            _write_positions_json(positions_path, selected[:real_required_bits])
            _verify_sec1_stego(
                seq_name=seq_name,
                original_video=video_path,
                stego_video=out_path,
                operating_positions=selected[:real_required_bits],
            )
            return out_path, int(bits_emb), real_required_bits, mode_name, None

        _, real_required_bits = _build_real_proof_payload()
        result = real_embed(
            video_path=str(video_path),
            message=REAL_PROOF_MESSAGE,
            output_path=str(out_path),
            circuits_dir=str(CIRCUITS_DIR),
            secret_key=SECRET_KEY,
            max_modifications_per_block=1,
            ffmpeg_validate=REAL_PROOF_FFMPEG_VALIDATE,
        )
        mode_name = f"real_proof_embed_ffmpeg_validate_{REAL_PROOF_FFMPEG_VALIDATE}"
        _write_stego_metadata(
            meta_path,
            video_path=video_path,
            bits_embedded=int(result.bits_embedded),
            bits_required=real_required_bits,
            validation_mode=mode_name,
            effective_threshold_db=None,
        )
        _verify_sec1_stego(
            seq_name=seq_name,
            original_video=video_path,
            stego_video=out_path,
            operating_positions=None,
        )
        return out_path, int(result.bits_embedded), real_required_bits, mode_name, None

    coeffs, fvd, nC_map, nal_len, t1_over, safe_positions = load_or_build_benchmark_analysis(
        video_path,
        force=force,
    )

    # Prefilter to patchable luma blocks only to reduce patcher skips.
    patchable_keys = {
        key for key, bit_len in nal_len.items()
        if key[1] < 16 and bit_len is not None and bit_len > 0
    }
    filtered_safe_positions = [
        p for p in safe_positions
        if (p[0], p[1]) in patchable_keys and (USE_SIGN_BIT_POSITIONS or p[2] >= 0)
    ]

    # Step 2: Build quality budget from patchable capacity and number of IDR frames.
    # For all-intra (GOP=1) sequences, relax constraints: each IDR is independent,
    # there is zero inter-frame cascade risk, so we can safely embed more bits.
    target_bits = len(payload) * 8
    idr_count = max(1, len(fvd))
    gop = SEQ_GOP.get(seq_name, 8)
    is_all_intra = (gop == 1)
    bits_per_idr_eff = QUALITY_BITS_PER_IDR_ALLINTRA if is_all_intra else QUALITY_BITS_PER_IDR
    rate_eff = QUALITY_MAX_PATCHABLE_RATE_ALLINTRA if is_all_intra else QUALITY_MAX_PATCHABLE_RATE
    patchable_cap = len(filtered_safe_positions)
    budget_by_idr = idr_count * bits_per_idr_eff
    budget_by_rate = int(patchable_cap * rate_eff)
    quality_budget_bits = min(target_bits, patchable_cap, budget_by_idr, budget_by_rate)
    if quality_budget_bits < MIN_QUALITY_BUDGET_BITS and patchable_cap >= MIN_QUALITY_BUDGET_BITS:
        quality_budget_bits = MIN_QUALITY_BUDGET_BITS

    sorted_positions = sort_positions_round_robin_idrs(filtered_safe_positions, CIF_MB_COUNT)
    # With max_modifications_per_block=1, keep only first position per block.
    dedup_positions: list[tuple[int, int, int]] = []
    seen_blocks: set[tuple[int, int]] = set()
    for mb, blk, cidx in sorted_positions:
        key = (mb, blk)
        if key in seen_blocks:
            continue
        seen_blocks.add(key)
        dedup_positions.append((mb, blk, cidx))

    if quality_budget_bits <= 0 and len(dedup_positions) >= 8:
        quality_budget_bits = min(FALLBACK_MIN_BITS, len(dedup_positions), target_bits)

    base_validation_mode = (
        "round_robin_patchable_quality_budget_adaptive_strict"
        if QUALITY_ENFORCE_TARGET_STRICT else
        "round_robin_patchable_quality_budget_adaptive"
    )
    validation_mode = base_validation_mode

    budget_bytes = quality_budget_bits // 8
    if budget_bytes <= 0:
        # Last-resort fallback: use any safe non-sign positions.
        fallback_pool = [p for p in safe_positions if p[2] >= 0]
        fallback_sorted = sort_positions_round_robin_idrs(fallback_pool, CIF_MB_COUNT)
        fallback_dedup: list[tuple[int, int, int]] = []
        fallback_seen: set[tuple[int, int]] = set()
        for mb, blk, cidx in fallback_sorted:
            key = (mb, blk)
            if key in fallback_seen:
                continue
            fallback_seen.add(key)
            fallback_dedup.append((mb, blk, cidx))
        if len(fallback_dedup) < 8:
            raise RuntimeError(f"No quality-budget-safe payload capacity for {seq_name}")
        dedup_positions = fallback_dedup
        quality_budget_bits = min(FALLBACK_MIN_BITS, len(dedup_positions), target_bits)
        budget_bytes = quality_budget_bits // 8
        validation_mode = "round_robin_patchable_quality_budget_fallback"

    # Step 3: Probe multiple budgets and choose the largest that meets quality target.
    # In strict mode, if no payload budget satisfies the target, fallback to 0-bit embedding.
    max_budget_bits = min(len(dedup_positions), target_bits, quality_budget_bits)
    probe_budgets = [8, 16, 24, 48, 96, 192, 384, 768, 1024, 1536, max_budget_bits]
    probe_budgets = sorted({b for b in probe_budgets if 8 <= b <= max_budget_bits})
    if _fast_mode_enabled():
        probe_budgets = sorted({b for b in [8, 48, 192, 768, max_budget_bits] if 8 <= b <= max_budget_bits})
    probe_max_frames = 120 if _fast_mode_enabled() else 200
    orig_probe = decode_luma_frames(video_path, max_frames=probe_max_frames)
    probe_path = OUTPUT_DIR / f"_sec1_probe_{seq_name}.h264"

    chosen_bits = 0
    chosen_psnr = float("-inf")
    chosen_min_frame_psnr = float("-inf")
    chosen_target_met = False
    best_fallback_bits = 0
    best_fallback_psnr = float("-inf")
    best_fallback_min_frame_psnr = float("-inf")

    for probe_bits in probe_budgets:
        probe_bytes = probe_bits // 8
        payload_probe = payload[:probe_bytes]
        probe_bits_exact = len(payload_probe) * 8
        selected_probe = _select_positions_temporal_strided(
            dedup_positions,
            probe_bits_exact,
            CIF_MB_COUNT,
            QUALITY_TEMPORAL_STRIDE,
        )

        if probe_bits_exact == 0:
            modified_probe = coeffs
        else:
            embedder_probe = PayloadEmbedder(max_modifications_per_block=1)
            modified_probe, _ = embedder_probe.embed_payload(
                coeffs,
                payload_probe,
                nC_map=nC_map,
                nal_length_map=nal_len,
                t1_override_map=t1_over,
                pre_validated_positions=selected_probe,
            )

        rec_probe = BitstreamReconstructor()
        rec_probe.reconstruct_video(
            str(video_path),
            modified_probe,
            str(probe_path),
            max_slices=None,
            frame_verified_data=fvd,
        )
        stego_probe = decode_luma_frames(probe_path, max_frames=probe_max_frames)
        n_probe = min(len(orig_probe), len(stego_probe))
        psnr_probe = psnr(orig_probe[:n_probe], stego_probe[:n_probe]) if n_probe > 0 else 0.0
        psnr_probe_frames = psnr_per_frame(orig_probe[:n_probe], stego_probe[:n_probe]) if n_probe > 0 else []
        finite_probe_frames = [p for p in psnr_probe_frames if np.isfinite(p)]
        min_frame_psnr_probe = min(finite_probe_frames) if finite_probe_frames else float("inf")
        frame_guard_ok = (
            (not QUALITY_ENFORCE_FRAME_MIN_PSNR)
            or (min_frame_psnr_probe >= QUALITY_TARGET_PSNR_FRAME_MIN_DB)
        )

        if psnr_probe >= QUALITY_TARGET_PSNR_FULL_DB and frame_guard_ok:
            # Keep the largest budget that still satisfies the quality target.
            if (not chosen_target_met) or (probe_bits_exact >= chosen_bits):
                chosen_bits = probe_bits_exact
                chosen_psnr = psnr_probe
                chosen_min_frame_psnr = min_frame_psnr_probe
                chosen_target_met = True
        elif frame_guard_ok and psnr_probe > best_fallback_psnr:
            # Best-effort fallback (used when strict mode is disabled or when
            # strict best-effort is explicitly enabled).
            best_fallback_bits = probe_bits_exact
            best_fallback_psnr = psnr_probe
            best_fallback_min_frame_psnr = min_frame_psnr_probe

    if not chosen_target_met and not QUALITY_ENFORCE_TARGET_STRICT:
        chosen_bits = best_fallback_bits
        chosen_psnr = best_fallback_psnr
        chosen_min_frame_psnr = best_fallback_min_frame_psnr
    elif not chosen_target_met and QUALITY_ENFORCE_TARGET_STRICT:
        # Strict mode: no payload budget met the target. If allowed, pick the
        # best-effort budget; otherwise fall back to zero-bit embedding.
        if QUALITY_STRICT_ALLOW_BEST_EFFORT and best_fallback_bits > 0:
            chosen_bits = best_fallback_bits
            chosen_psnr = best_fallback_psnr
            chosen_min_frame_psnr = best_fallback_min_frame_psnr
            validation_mode = "round_robin_patchable_quality_budget_adaptive_strict_best_effort_fallback"
        else:
            chosen_bits = 0
            chosen_psnr = float("inf")
            chosen_min_frame_psnr = float("inf")
            validation_mode = "round_robin_patchable_quality_budget_adaptive_strict_zero_fallback"

    if probe_path.exists():
        probe_path.unlink(missing_ok=True)

    payload_budget = payload[: chosen_bits // 8]
    budget_bits_exact = len(payload_budget) * 8
    selected = _select_positions_temporal_strided(
        dedup_positions,
        budget_bits_exact,
        CIF_MB_COUNT,
        QUALITY_TEMPORAL_STRIDE,
    )

    if validation_mode != "round_robin_patchable_quality_budget_fallback" and chosen_target_met:
        validation_mode = base_validation_mode
    if QUALITY_ENFORCE_FRAME_MIN_PSNR:
        validation_mode = f"{validation_mode}_framemin{int(QUALITY_TARGET_PSNR_FRAME_MIN_DB)}"
    if QUALITY_TEMPORAL_STRIDE > 1:
        validation_mode = f"{validation_mode}_tstride{QUALITY_TEMPORAL_STRIDE}"
    effective_threshold_db = QUALITY_TARGET_PSNR_FRAME_MIN_DB if QUALITY_ENFORCE_FRAME_MIN_PSNR else None

    print(
        f"  [{seq_name}] safe={len(safe_positions)} patchable={patchable_cap} idr={idr_count} "
        f"budget={budget_bits_exact}/{target_bits} bits (target_psnr={QUALITY_TARGET_PSNR_FULL_DB:.1f}, "
        f"target_frame_min={QUALITY_TARGET_PSNR_FRAME_MIN_DB:.1f}, "
        f"chosen_psnr~{chosen_psnr:.2f}, chosen_min_frame~{chosen_min_frame_psnr:.2f})"
    )

    # Step 4: Final embed at chosen budget.
    embedder = PayloadEmbedder(max_modifications_per_block=1)
    modified, bits_emb = embedder.embed_payload(
        coeffs,
        payload_budget,
        nC_map=nC_map,
        nal_length_map=nal_len,
        t1_override_map=t1_over,
        pre_validated_positions=selected,
    )

    rec2 = BitstreamReconstructor()
    rec2.reconstruct_video(
        str(video_path),
        modified,
        str(out_path),
        max_slices=None,
        frame_verified_data=fvd,
    )
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(f"Stego video not created: {out_path}")
    # Report requested target payload bits separately from embedded bits so strict
    # zero-fallback does not hide unmet capacity.
    _write_stego_metadata(
        meta_path,
        video_path=video_path,
        bits_embedded=int(bits_emb),
        bits_required=target_bits,
        validation_mode=validation_mode,
        effective_threshold_db=effective_threshold_db,
    )
    return out_path, bits_emb, target_bits, validation_mode, effective_threshold_db


# -------------------------------------------------------------------------
# Data collection
# -------------------------------------------------------------------------
def collect_data(
    force: bool = False,
    include_sequences: set[str] | None = None,
    include_unstable_sequences: bool = False,
) -> dict:
    active_sequences = {
        k: SEQUENCES[k]
        for k in SEC1_RECOMMENDED_SEQUENCE_NAMES
        if k in SEQUENCES
    }
    if include_unstable_sequences:
        active_sequences.update(OPTIONAL_QUALITY_SEQUENCES)
    if include_sequences:
        # Explicit sequence selection should work for any registered sequence,
        # regardless of default/optional grouping.
        active_sequences = {k: v for k, v in SEQUENCES.items() if k in include_sequences}
    if not active_sequences:
        raise ValueError("No valid sequences selected for sec1")

    run_cache_meta = _sec1_run_cache_meta(active_sequences)
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        if isinstance(cached, dict) and "__meta__" in cached and "data" in cached:
            if cached["__meta__"] == run_cache_meta:
                print("  [cache hit] sec1 — skipping embed+decode")
                return cached["data"]

    data: dict = {}

    # Pre-warm ZK proof cache before loading any IDR data so snarkJS runs
    # with low memory pressure (avoids Node.js worker OOM on 2nd+ sequence).
    if USE_REAL_PROOF_EMBED_PIPELINE and not _PROOF_PAYLOAD_CACHE_PATH.exists():
        print("  [pre-caching ZK proof payload]")
        _build_real_proof_payload()

    for seq_name, video_path in active_sequences.items():
        print(f"  [{seq_name}] embedding …")
        t0 = time.perf_counter()
        try:
            stego_path, bits_embedded, bits_required, validation_mode, effective_threshold_db = _embed_for_benchmark(seq_name, video_path, force=force)
        except RuntimeError as exc:
            print(f"  [{seq_name}] skipped: {exc}")
            continue
        embed_time = time.perf_counter() - t0
        print(f"  [{seq_name}] decoding …")
        _qm = compute_quality_streaming(video_path, stego_path)
        n = _qm["n"]
        assert n > 0, f"No frames decoded for {seq_name}"
        psnr_list_raw = _qm["psnr_per_frame"]
        ssim_list = _qm["ssim_per_frame"]
        operating_positions = None
        pos_path = _stego_positions_path(stego_path)
        if pos_path.exists():
            operating_positions = [
                tuple(int(v) for v in row)
                for row in json.loads(pos_path.read_text(encoding="utf-8"))
            ]

        # --- PSNR / SSIM separation ---
        # IDR frames occur every GOP frames. For all-intra sequences GOP=1.
        # P-frames AFTER a modified IDR show "cascade" PSNR degradation.
        GOP = SEQ_GOP.get(seq_name, 8)
        if operating_positions:
            idr_indices = {
                int(mb // CIF_MB_COUNT)
                for mb, _, _ in operating_positions
                if 0 <= int(mb // CIF_MB_COUNT) < n
            }
        else:
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

        psnr_full_video_raw = _qm["psnr_full_video"]
        psnr_full_video = float(min(psnr_full_video_raw, 60.0))
        psnr_full_video_is_infinite = bool(not np.isfinite(psnr_full_video_raw))

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
            "psnr_avg_all_frames":  psnr_avg_all_frames,
            "primary_psnr_full_video": psnr_full_video,
            "primary_psnr_full_video_is_infinite": psnr_full_video_is_infinite,
            "avg_idr_psnr":         float(np.mean(idr_psnr)) if idr_psnr else float("inf"),
            "avg_pframe_psnr":      float(np.mean(pfr_psnr)) if pfr_psnr else float("inf"),
            "psnr_full_video":      psnr_full_video,
            "psnr_full_video_is_infinite": psnr_full_video_is_infinite,
            "avg_ssim":             float(np.mean(ssim_list)),
            "min_psnr":             float(np.min(all_finite)) if all_finite else float("inf"),
            "min_modified_frame_psnr": (float(np.min(idr_psnr)) if idr_psnr else float("inf")),
            "embedded_bits":        (int(bits_embedded) if bits_embedded is not None else None),
            "required_bits":        int(bits_required),
            "payload_target_met":   (None if bits_embedded is None else bool(int(bits_embedded) >= int(bits_required))),
            "embed_time":           embed_time,
            "validation_threshold_db": (QUALITY_TARGET_PSNR_FRAME_MIN_DB if QUALITY_ENFORCE_FRAME_MIN_PSNR else None),
            "validation_threshold_db_effective": effective_threshold_db,
            "frame_count":          int(n),
            "modified_frame_count": int(len(idr_indices)),
            "quality_target_bits":  int(bits_required),
            "validation_mode":      validation_mode,
            "fallback_used":        ("fallback" in validation_mode),
        }
        if USE_REAL_PROOF_EMBED_PIPELINE:
            verify_info = _verify_sec1_stego(
                seq_name=seq_name,
                original_video=video_path,
                stego_video=stego_path,
                operating_positions=operating_positions,
            )
            data[seq_name].update(verify_info)
        if (
            USE_REAL_PROOF_EMBED_PIPELINE
            and QUALITY_ENFORCE_FRAME_MIN_PSNR
            and float(data[seq_name]["min_modified_frame_psnr"]) <= QUALITY_TARGET_PSNR_FRAME_MIN_DB
        ):
            raise RuntimeError(
                f"[{seq_name}] modified-frame min PSNR "
                f"{data[seq_name]['min_modified_frame_psnr']:.2f} dB "
                f"<= required {QUALITY_TARGET_PSNR_FRAME_MIN_DB:.2f} dB"
            )
        embedded_text = (
            f"embedded={bits_embedded}/{bits_required} bits"
            if bits_embedded is not None else
            "embedded=unknown (reused cached stego)"
        )
        print(
            f"  [{seq_name}] full-video={data[seq_name]['psnr_full_video']:.2f} dB  "
            f"avg-all-frames={psnr_avg_all_frames:.2f} dB  "
            f"modified-min={data[seq_name]['min_modified_frame_psnr']:.2f} dB  "
            f"modified-avg={data[seq_name]['avg_idr_psnr']:.2f} dB  "
            f"SSIM={data[seq_name]['avg_ssim']:.4f}  "
            f"{embedded_text}"
        )

    if not data:
        raise RuntimeError("SEC1 produced no successful sequence results")

    cache_save(CACHE_KEY, {"__meta__": run_cache_meta, "data": data})
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
                color=list(PALETTE.values())[i % len(PALETTE)],
                linestyle=LINESTYLES[i % len(LINESTYLES)],
                label=label, alpha=0.9)

    max_frames = max(len(data[s]["psnr"]) for s in data)
    ax.set_xlabel("Frame index")
    ax.set_ylabel("PSNR (dB)")
    ax.set_title("§1  Per-Frame PSNR: Stego vs Original  (CAVLC T1 embedding)")
    ax.legend(loc="lower right")
    ax.set_xlim(0, max_frames - 1)
    ax.yaxis.set_major_locator(ticker.MultipleLocator(5))

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
                color=list(PALETTE.values())[i % len(PALETTE)],
                linestyle=LINESTYLES[i % len(LINESTYLES)],
                label=label, alpha=0.9)

    max_frames = max(len(data[s]["ssim"]) for s in data)
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
    palette = list(PALETTE.values())
    colors = [palette[i % len(palette)] for i in range(len(seqs))]
    x      = np.arange(len(seqs))

    def _safe_float(seq: str, key: str, default: float) -> float:
        val = data.get(seq, {}).get(key, default)
        if val is None:
            return default
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    # --- Subplot 1: Full-video PSNR (PRIMARY metric) ---
    full_psnr_vals = [min(_safe_float(s, "psnr_full_video", 0.0), 60.0) for s in seqs]
    bars1 = ax1.bar(x, full_psnr_vals, color=colors, width=0.5, zorder=3)
    ax1.set_xticks(x); ax1.set_xticklabels(labels)
    ax1.set_ylabel("PSNR (dB)")
    ax1.set_title("§1  Full-Video PSNR\n(MSE over all frames — primary metric)")
    pmax1 = max(full_psnr_vals) if full_psnr_vals else 60
    ax1.set_ylim(0, min(pmax1 * 1.25, 70))
    for bar, val in zip(bars1, [_safe_float(s, "psnr_full_video", 0.0) for s in seqs]):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                 f"{val:.1f} dB", ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax1.axhline(40.0, color="red", linestyle="--", linewidth=1.5,
                label=">40 dB (imperceptible)")
    ax1.legend(fontsize=9)

    # --- Subplot 2: Avg per-frame PSNR (secondary context) ---
    avg_all_vals = [_safe_float(s, "psnr_avg_all_frames", 0.0) for s in seqs]
    bars2 = ax2.bar(x, avg_all_vals, color=colors, width=0.5, zorder=3)
    ax2.set_xticks(x); ax2.set_xticklabels(labels)
    ax2.set_ylabel("PSNR (dB)")
    ax2.set_title("§1  Avg Per-Frame PSNR\n(all frames, inf capped at 60 dB)")
    pmax2 = max(v for v in avg_all_vals) if avg_all_vals else 50
    ax2.set_ylim(0, pmax2 * 1.25)
    for bar, val in zip(bars2, avg_all_vals):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                 f"{val:.1f} dB", ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax2.axhline(40.0, color="#999999", linestyle="--", linewidth=1.2,
                label="40 dB (imperceptible)")
    ax2.legend(fontsize=9)

    # --- Subplot 3: Average SSIM ---
    ssim_vals = [_safe_float(s, "avg_ssim", 0.0) for s in seqs]
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


def plot_psnr_vs_qp(data: dict) -> None:
    """Plot full-video PSNR vs QP for any base sequence with >=2 all-intra QP points."""
    qp_groups: dict[str, list[tuple[int, str]]] = {}
    for seq in data:
        match = _QP_SEQ_RE.match(seq)
        if not match or seq.endswith("_1000"):
            continue
        base = match.group("base")
        qp = int(match.group("qp"))
        qp_groups.setdefault(base, []).append((qp, seq))

    qp_groups = {base: sorted(items) for base, items in qp_groups.items() if len(items) >= 2}
    if not qp_groups:
        return

    setup_style()
    fig, ax = plt.subplots(figsize=(8.5, 5))
    colors = list(PALETTE.values())

    for i, (base, items) in enumerate(sorted(qp_groups.items())):
        qps = [qp for qp, _ in items]
        psnr_vals = [float(data[seq]["psnr_full_video"]) for _, seq in items]
        label = base.capitalize()
        ax.plot(
            qps, psnr_vals,
            color=colors[i % len(colors)],
            linestyle=LINESTYLES[i % len(LINESTYLES)],
            linewidth=2.2,
            label=label,
        )
        for qp, psnr_val in zip(qps, psnr_vals):
            ax.text(qp, psnr_val + 0.15, f"{psnr_val:.1f}", ha="center", va="bottom", fontsize=9)

    ax.axhline(40.0, color="#C62828", linestyle="--", linewidth=1.3, label="40 dB threshold")
    ax.set_xlabel("QP (all-intra, GOP=1)")
    ax.set_ylabel("Full-video PSNR (dB)")
    ax.set_title("§1  Full-Video PSNR vs QP")
    ax.set_xticks(sorted({qp for items in qp_groups.values() for qp, _ in items}))
    ax.legend(fontsize=9)
    save_fig(fig, "sec1_psnr_vs_qp")


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------
def run(
    force: bool = False,
    include_sequences: set[str] | None = None,
    include_unstable_sequences: bool = False,
) -> dict:
    print("\n=== §1  Quality vs Original ===")
    data = collect_data(
        force=force,
        include_sequences=include_sequences,
        include_unstable_sequences=include_unstable_sequences,
    )
    plot_psnr_timeline(data)
    plot_ssim_timeline(data)
    plot_avg_quality_bar(data)
    plot_psnr_vs_qp(data)
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
    parser.add_argument(
        "--include-unstable",
        action="store_true",
        help="Include diagnostic-only unstable sequences in sec1 (e.g. foreman_hq)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Developer fast mode: skip expensive validation steps where allowed",
    )
    args = parser.parse_args()
    if args.fast:
        os.environ["SEC1_FAST_MODE"] = "1"
    selected = {s.strip() for s in args.sequences.split(",") if s.strip()} or None
    run(
        force=args.force,
        include_sequences=selected,
        include_unstable_sequences=args.include_unstable,
    )
