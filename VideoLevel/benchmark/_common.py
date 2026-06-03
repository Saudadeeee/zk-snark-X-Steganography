"""
_common.py — Shared utilities for all benchmark sections.

Provides: path constants, matplotlib style, video decode/PSNR/SSIM helpers,
          JSON cache helpers, and figure save/close utilities.
"""

import json
import math
import os
import pickle
import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT        = Path(__file__).resolve().parent.parent
DATA_DIR    = ROOT / "data" / "encoded"
OUTPUT_DIR  = ROOT / "data" / "output"
RESULTS_DIR = Path(__file__).parent / "results"
CIRCUITS_DIR = ROOT / "circuits"
BENCHMARK_CACHE_DIR = ROOT / ".cache" / "benchmark_frames"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
BENCHMARK_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# CIF resolution used by all test sequences
WIDTH, HEIGHT = 352, 288
CIF_MB_COUNT = 396  # 22x18

# Test sequences: baseline all-intra assets + new diversified variants.
SEQUENCES = {
    # Baseline (paper / reference)
    "foreman_q22_g1": DATA_DIR / "foreman_cif_q22_g1.h264",
    "coastguard_q22_g1": DATA_DIR / "coastguard_cif_q22_g1.h264",
    "deadline_q22_g1": DATA_DIR / "deadline_cif_q22_g1.h264",
    "akiyo_q22_g1": DATA_DIR / "akiyo_cif_q22_g1.h264",
    "container_q22_g1": DATA_DIR / "container_cif_q22_g1.h264",
    "hall_monitor_q22_g1": DATA_DIR / "hall_monitor_cif_q22_g1.h264",
    "football_q22_g1": DATA_DIR / "football_cif_q22_g1.h264",
    "city_q22_g1": DATA_DIR / "city_cif_q22_g1.h264",
    # New all-intra variants (length + quality sweep)
    "foreman_q18_g1_150f": DATA_DIR / "foreman_cif_q18_g1_150f.h264",
    "foreman_q28_g1_300f": DATA_DIR / "foreman_cif_q28_g1_300f.h264",
    "coastguard_q18_g1_150f": DATA_DIR / "coastguard_cif_q18_g1_150f.h264",
    "coastguard_q22_g1_600f": DATA_DIR / "coastguard_cif_q22_g1_600f.h264",
    "coastguard_q22_g1_1000f": DATA_DIR / "coastguard_cif_q22_g1_1000f.h264",
    "coastguard_q22_g1_3000f": DATA_DIR / "coastguard_cif_q22_g1_3000f.h264",
    "coastguard_q28_g1_300f": DATA_DIR / "coastguard_cif_q28_g1_300f.h264",
    "deadline_q18_g1_150f": DATA_DIR / "deadline_cif_q18_g1_150f.h264",
    "deadline_q22_g1_600f": DATA_DIR / "deadline_cif_q22_g1_600f.h264",
    "deadline_q22_g1_1000f": DATA_DIR / "deadline_cif_q22_g1_1000f.h264",
    "deadline_q28_g1_300f": DATA_DIR / "deadline_cif_q28_g1_300f.h264",
    # GOP=8 bitrate-controlled variants (content + bitrate diversity)
    "foreman_g8_300f_b800k": DATA_DIR / "foreman_cif_g8_300f_b800k.h264",
    "coastguard_g8_300f_b800k": DATA_DIR / "coastguard_cif_g8_300f_b800k.h264",
    "deadline_g8_300f_b800k": DATA_DIR / "deadline_cif_g8_300f_b800k.h264",
}

SEQ_FRAMES = {
    "foreman_q22_g1": 300,
    "coastguard_q22_g1": 300,
    "deadline_q22_g1": 300,
    "akiyo_q22_g1": 300,
    "container_q22_g1": 300,
    "hall_monitor_q22_g1": 300,
    "football_q22_g1": 260,
    "city_q22_g1": 300,
    "foreman_q18_g1_150f": 150,
    "foreman_q28_g1_300f": 300,
    "coastguard_q18_g1_150f": 150,
    "coastguard_q22_g1_600f": 600,
    "coastguard_q22_g1_1000f": 1000,
    "coastguard_q22_g1_3000f": 3000,
    "coastguard_q28_g1_300f": 300,
    "deadline_q18_g1_150f": 150,
    "deadline_q22_g1_600f": 600,
    "deadline_q22_g1_1000f": 1000,
    "deadline_q28_g1_300f": 300,
    "foreman_g8_300f_b800k": 300,
    "coastguard_g8_300f_b800k": 300,
    "deadline_g8_300f_b800k": 300,
}

# ---------------------------------------------------------------------------
# Professional colour palette (print-safe, colour-blind-friendly)
# ---------------------------------------------------------------------------
PALETTE = {
    "this_work": "#1565C0",   # Deep blue
    "lsb":       "#C62828",   # Deep red
    "f5":        "#2E7D32",   # Forest green
    "mv":        "#E65100",   # Burnt orange
    "ipm":       "#6A1B9A",   # Purple
    "groth16":   "#1565C0",
    "schnorr":   "#2E7D32",
    "plonk":     "#E65100",
    "stark":     "#6A1B9A",
    "bulletproof":"#00838F",
}

MARKERS = ["o", "s", "^", "D", "v", "P", "X", "*", "+", "x"]
LINESTYLES = ["-", "--", "-.", ":", (0, (3, 1, 1, 1)), (0, (5, 1))]

SEQ_LABELS = {
    "foreman_q22_g1": "Foreman all-intra QP22 (baseline)",
    "coastguard_q22_g1": "Coastguard all-intra QP22 (baseline)",
    "deadline_q22_g1": "Deadline all-intra QP22 (baseline)",
    "akiyo_q22_g1": "Akiyo all-intra QP22 (low motion)",
    "container_q22_g1": "Container all-intra QP22 (detail)",
    "hall_monitor_q22_g1": "Hall Monitor all-intra QP22 (surveillance)",
    "football_q22_g1": "Football all-intra QP22 (high motion)",
    "city_q22_g1": "City all-intra QP22 (texture-heavy)",
    "foreman_q18_g1_150f": "Foreman all-intra QP18 (150f)",
    "foreman_q28_g1_300f": "Foreman all-intra QP28 (300f)",
    "coastguard_q18_g1_150f": "Coastguard all-intra QP18 (150f)",
    "coastguard_q22_g1_600f": "Coastguard all-intra QP22 (600f)",
    "coastguard_q22_g1_1000f": "Coastguard all-intra QP22 high-motion (1000f)",
    "coastguard_q22_g1_3000f": "Coastguard all-intra QP22 high-motion (3000f, repeated)",
    "coastguard_q28_g1_300f": "Coastguard all-intra QP28 (300f)",
    "deadline_q18_g1_150f": "Deadline all-intra QP18 (150f)",
    "deadline_q22_g1_600f": "Deadline all-intra QP22 (600f)",
    "deadline_q22_g1_1000f": "Deadline all-intra QP22 mixed-motion (1000f)",
    "deadline_q28_g1_300f": "Deadline all-intra QP28 (300f)",
    "foreman_g8_300f_b800k": "Foreman GOP8 ABR 800 kbps (300f)",
    "coastguard_g8_300f_b800k": "Coastguard GOP8 ABR 800 kbps (300f)",
    "deadline_g8_300f_b800k": "Deadline GOP8 ABR 800 kbps (300f)",
}

# ---------------------------------------------------------------------------
# Matplotlib style
# ---------------------------------------------------------------------------
def setup_style() -> None:
    """Apply a clean, publication-quality matplotlib style."""
    plt.rcParams.update({
        "figure.dpi":               150,
        "figure.facecolor":         "white",
        "font.family":              "DejaVu Sans",
        "font.size":                11,
        "axes.titlesize":           13,
        "axes.titleweight":         "bold",
        "axes.labelsize":           11,
        "axes.labelweight":         "normal",
        "axes.facecolor":           "#F8F8F8",
        "axes.grid":                True,
        "axes.spines.top":          False,
        "axes.spines.right":        False,
        "axes.spines.left":         True,
        "axes.spines.bottom":       True,
        "grid.linestyle":           "--",
        "grid.color":               "#CCCCCC",
        "lines.linewidth":          2.2,
        "legend.framealpha":        0.92,
        "legend.fontsize":          10,
        "legend.edgecolor":         "#BBBBBB",
        "xtick.labelsize":          10,
        "ytick.labelsize":          10,
        "figure.constrained_layout.use": True,
    })

# ---------------------------------------------------------------------------
# Video decode helpers
# ---------------------------------------------------------------------------
FRAME_CACHE_SCHEMA_VERSION = "v1-2026-05-04"


def _frame_cache_enabled() -> bool:
    return os.environ.get("BENCHMARK_DISABLE_FRAME_CACHE", "0") != "1"


def _frame_cache_paths(h264_path: str | Path, max_frames: int) -> tuple[Path, Path]:
    p = Path(h264_path)
    try:
        resolved = str(p.resolve()).encode("utf-8")
    except OSError:
        resolved = str(p).encode("utf-8")
    key = hashlib.sha1(
        resolved + b"|" + str(int(max_frames)).encode("ascii") + b"|" + f"{WIDTH}x{HEIGHT}".encode("ascii")
    ).hexdigest()[:16]
    stem = f"{p.stem}_{key}_{int(max_frames)}f"
    return BENCHMARK_CACHE_DIR / f"{stem}.npy", BENCHMARK_CACHE_DIR / f"{stem}.json"


def _frame_cache_meta(h264_path: str | Path, max_frames: int) -> dict[str, object]:
    p = Path(h264_path)
    stat = p.stat()
    return {
        "schema": FRAME_CACHE_SCHEMA_VERSION,
        "path": str(p.resolve()),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "max_frames": int(max_frames),
        "width": WIDTH,
        "height": HEIGHT,
    }


def _decode_luma_frames_uncached(h264_path: str | Path, max_frames: int = 9999) -> np.ndarray:
    """
    Decode H.264 -> array of Y (luma) frames, shape (N, H, W), dtype float32.
    Uses ffmpeg subprocess. float32 halves memory vs float64 (sufficient for PSNR/SSIM).
    """
    h264_path = str(h264_path)
    cmd = [
        "ffmpeg", "-i", h264_path,
        "-f", "rawvideo", "-pix_fmt", "yuv420p",
        "-vf", f"scale={WIDTH}:{HEIGHT}",
        "pipe:1", "-loglevel", "quiet",
    ]
    result = subprocess.run(cmd, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()}")
    frame_size_420 = WIDTH * HEIGHT * 3 // 2
    raw = result.stdout
    n_frames = min(len(raw) // frame_size_420, max_frames)
    out = np.empty((n_frames, HEIGHT, WIDTH), dtype=np.float32)
    for i in range(n_frames):
        start = i * frame_size_420
        out[i] = np.frombuffer(raw[start: start + WIDTH * HEIGHT], dtype=np.uint8).reshape(HEIGHT, WIDTH)
    return out


def decode_luma_frames(h264_path: str | Path, max_frames: int = 9999) -> np.ndarray:
    """
    Decode H.264 -> array of Y (luma) frames, shape (N, H, W), dtype float32.
    Uses a disk-backed cache keyed by file fingerprint and max_frames to avoid
    repeated ffmpeg decode across benchmark sections and validation passes.
    """
    if max_frames <= 0:
        return np.empty((0, HEIGHT, WIDTH), dtype=np.float32)

    p = Path(h264_path)
    if not _frame_cache_enabled():
        return _decode_luma_frames_uncached(p, max_frames=max_frames)

    npy_path, meta_path = _frame_cache_paths(p, max_frames)
    try:
        expected_meta = _frame_cache_meta(p, max_frames)
        if npy_path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta == expected_meta:
                return np.load(npy_path, mmap_mode="r")
    except (OSError, ValueError, json.JSONDecodeError):
        pass

    frames = _decode_luma_frames_uncached(p, max_frames=max_frames)
    try:
        np.save(npy_path, frames, allow_pickle=False)
        meta_path.write_text(json.dumps(expected_meta, ensure_ascii=True, indent=2), encoding="utf-8")
    except OSError:
        pass
    return frames


def benchmark_analysis_cache_enabled() -> bool:
    """Allow benchmark sections to reuse runtime video-analysis cache."""
    return os.environ.get("BENCHMARK_DISABLE_ANALYSIS_CACHE", "0") != "1"


def load_or_build_benchmark_analysis(
    video_path: str | Path,
    *,
    force: bool = False,
):
    """
    Return cached cover-video analysis for benchmark sections.

    Reuses the runtime analysis cache so sec1/sec2/sec3/sec4 can share the same
    expensive IDR extraction and safety-filter output across repeated runs.
    """
    vp = Path(video_path)
    if benchmark_analysis_cache_enabled():
        from src.core.analysis_cache import load_or_build_video_analysis

        return load_or_build_video_analysis(
            vp,
            use_cache=True,
            force_refresh=force,
        )

    from src.bitstream.bitstream_ops import BitstreamReconstructor
    from src.core.stego import CAVLCSafetyFilter

    rec = BitstreamReconstructor()
    coefficients, frame_verified_data, nC_map, nal_length_map, t1_override_map = (
        load_or_extract_idr_blocks(vp, rec, force=force)
    )
    safety = CAVLCSafetyFilter()
    safe_positions = safety.get_safe_positions(
        coefficients,
        nC_map=nC_map,
        nal_length_map=nal_length_map,
        t1_override_map=t1_override_map,
    )
    return (
        coefficients,
        frame_verified_data,
        nC_map,
        nal_length_map,
        t1_override_map,
        safe_positions,
    )


def load_sec1_positions(
    seq_name: str,
    *,
    validated_pool: bool = False,
) -> list[tuple[int, int, int]]:
    """Load SEC1 operating positions or validated pool for a sequence."""
    suffix = ".validated_pool.json" if validated_pool else ".positions.json"
    path = OUTPUT_DIR / f"sec1_stego_{seq_name}.h264{suffix}"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [tuple(int(v) for v in row) for row in raw]
    except Exception:
        return []


def load_sec1_meta(seq_name: str) -> dict | None:
    """Load SEC1 meta sidecar for a sequence when available."""
    path = OUTPUT_DIR / f"sec1_stego_{seq_name}.h264.meta.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_capacity_views(
    seq_name: str,
    video_path: str | Path,
    *,
    force: bool = False,
) -> dict[str, int | None]:
    """
    Return harmonized capacity counts for benchmark reporting.

    Terms:
      - raw_safe_bits: CAVLC-safe positions before patchability / quality validation
      - validated_pool_bits: SEC1 validated candidate pool
      - operating_bits: exact positions used by the SEC1 operating point
      - bits_embedded / bits_required: taken from SEC1 meta when available
    """
    _coeffs, _fvd, _nC_map, _nal_len, _t1_over, safe_positions = load_or_build_benchmark_analysis(
        video_path,
        force=force,
    )
    validated_positions = load_sec1_positions(seq_name, validated_pool=True)
    operating_positions = load_sec1_positions(seq_name, validated_pool=False)
    meta = load_sec1_meta(seq_name) or {}
    bits_embedded = meta.get("bits_embedded")
    bits_required = meta.get("bits_required")
    ffmpeg_validated_bits = meta.get("ffmpeg_validated_bits")
    requested_position_bits = meta.get("requested_position_bits")
    applied_position_bits = meta.get("applied_position_bits")
    validation_mode = meta.get("validation_mode")

    patchable = measure_patchable_usable_bits(video_path, force=force, max_positions=2000)

    return {
        "raw_safe_bits": len(safe_positions),
        "patchable_usable_bits": int(patchable["patchable_usable_bits"]),
        "validated_pool_bits": len(validated_positions) if validated_positions else None,
        "operating_bits": len(operating_positions) if operating_positions else None,
        "bits_embedded": int(bits_embedded) if isinstance(bits_embedded, (int, float)) else None,
        "bits_required": int(bits_required) if isinstance(bits_required, (int, float)) else None,
        "ffmpeg_validated_bits": int(ffmpeg_validated_bits) if isinstance(ffmpeg_validated_bits, (int, float)) else None,
        "requested_position_bits": int(requested_position_bits) if isinstance(requested_position_bits, (int, float)) else None,
        "applied_position_bits": int(applied_position_bits) if isinstance(applied_position_bits, (int, float)) else None,
        "validation_mode": str(validation_mode) if isinstance(validation_mode, str) else None,
    }


def measure_patchable_usable_bits(
    video_path: str | Path,
    *,
    force: bool = False,
    max_positions: int | None = None,
    max_modifications_per_block: int = 1,
) -> dict[str, object]:
    """
    Measure how many candidate positions survive the patchability flow used by embed().

    Returns:
      {
        "raw_safe_bits": int,
        "patchable_usable_bits": int,
        "positions": list[tuple[int,int,int]],
      }
    """
    from src.embedder import _limit_positions_per_block, _prune_patchable_positions

    (
        _coeffs,
        frame_verified_data,
        _nC_map,
        _nal_length_map,
        _t1_override_map,
        safe_positions,
    ) = load_or_build_benchmark_analysis(video_path, force=force)

    target_bits = len(safe_positions) if max_positions is None else min(len(safe_positions), int(max_positions))
    usable_positions = _prune_patchable_positions(
        list(safe_positions),
        frame_verified_data,
        required_bits=target_bits,
    )
    usable_positions = _limit_positions_per_block(
        usable_positions,
        max_modifications_per_block=max_modifications_per_block,
    )
    return {
        "raw_safe_bits": len(safe_positions),
        "patchable_usable_bits": len(usable_positions),
        "positions": usable_positions,
    }


def select_best_sec1_operating_asset(
    *,
    required_bits: int,
    preferred_sequences: list[str] | None = None,
) -> tuple[str | None, str | None]:
    """
    Pick the best asset that already has an SEC1 operating-point sidecar meeting required_bits.

    Returns:
      (sequence_name, video_path)
    """
    seq_names = preferred_sequences or list(SEQUENCES.keys())
    best_seq = None
    best_path = None
    best_score = (-1, -1)

    for seq_name in seq_names:
        video_path = SEQUENCES.get(seq_name)
        if video_path is None or not Path(video_path).exists():
            continue
        caps = get_capacity_views(seq_name, video_path, force=False)
        operating_bits = int(caps.get("operating_bits") or 0)
        validated_bits = int(caps.get("validated_pool_bits") or 0)
        if operating_bits >= required_bits:
            score = (operating_bits, validated_bits)
            if score > best_score:
                best_score = score
                best_seq = seq_name
                best_path = str(video_path)

    return best_seq, best_path

# ---------------------------------------------------------------------------
# Quality metrics
# ---------------------------------------------------------------------------
def psnr(orig: np.ndarray, stego: np.ndarray) -> float:
    """PSNR in dB between two same-shape arrays (luma frames or full video)."""
    o = orig.astype(np.float32) if orig.dtype != np.float32 else orig
    s = stego.astype(np.float32) if stego.dtype != np.float32 else stego
    mse = np.mean((o - s) ** 2)
    if mse < 1e-12:
        return float("inf")
    return 20.0 * np.log10(255.0 / np.sqrt(mse))

def ssim_frame(orig: np.ndarray, stego: np.ndarray) -> float:
    """SSIM for a single 2-D luma frame."""
    from skimage.metrics import structural_similarity
    return structural_similarity(
        orig.astype(np.uint8), stego.astype(np.uint8), data_range=255
    )

def psnr_per_frame(orig_frames: np.ndarray, stego_frames: np.ndarray) -> list[float]:
    n = min(len(orig_frames), len(stego_frames))
    return [psnr(orig_frames[i], stego_frames[i]) for i in range(n)]

def ssim_per_frame(orig_frames: np.ndarray, stego_frames: np.ndarray) -> list[float]:
    n = min(len(orig_frames), len(stego_frames))
    return [ssim_frame(orig_frames[i], stego_frames[i]) for i in range(n)]


def compute_quality_streaming(
    orig_path: str | Path,
    stego_path: str | Path,
    max_frames: int = 9999,
) -> dict:
    """
    Compute per-frame and full-video PSNR/SSIM without holding large frame arrays.

    Uses cached luma decode when available, then processes one frame pair at a
    time. This avoids repeated ffmpeg decode across benchmark passes.

    Returns dict with keys:
      psnr_per_frame, ssim_per_frame, psnr_full_video, n
    """
    from skimage.metrics import structural_similarity

    orig_frames = decode_luma_frames(orig_path, max_frames=max_frames)
    stego_frames = decode_luma_frames(stego_path, max_frames=max_frames)
    n = min(len(orig_frames), len(stego_frames))

    psnr_list: list[float] = []
    ssim_list: list[float] = []
    total_ssd = 0.0
    total_pixels = 0

    for i in range(n):
        o = np.asarray(orig_frames[i], dtype=np.uint8)
        s = np.asarray(stego_frames[i], dtype=np.uint8)

        diff = o.astype(np.float32) - s.astype(np.float32)
        ssd = float(np.dot(diff.ravel(), diff.ravel()))
        total_ssd += ssd
        total_pixels += WIDTH * HEIGHT

        frame_mse = ssd / (WIDTH * HEIGHT)
        psnr_list.append(
            float("inf") if frame_mse < 1e-12
            else 20.0 * math.log10(255.0 / math.sqrt(frame_mse))
        )
        ssim_list.append(structural_similarity(o, s, data_range=255))

    full_mse = total_ssd / total_pixels if total_pixels > 0 else 0.0
    full_psnr = (
        float("inf") if full_mse < 1e-12
        else 20.0 * math.log10(255.0 / math.sqrt(full_mse))
    )

    return {
        "psnr_per_frame": psnr_list,
        "ssim_per_frame": ssim_list,
        "psnr_full_video": full_psnr,
        "n": n,
    }


def compute_quality_subset(
    orig_path: str | Path,
    stego_path: str | Path,
    frame_indices: list[int] | set[int] | tuple[int, ...],
    *,
    include_ssim: bool = False,
    max_frames: int = 9999,
) -> dict[str, object]:
    """
    Compute quality only for the selected frame indices.

    This is primarily used by sec1 validation loops so all-intra retries do not
    need a full-video quality pass when only a small set of IDR frames changed.
    """
    orig_frames = decode_luma_frames(orig_path, max_frames=max_frames)
    stego_frames = decode_luma_frames(stego_path, max_frames=max_frames)
    n = min(len(orig_frames), len(stego_frames))
    selected = sorted({int(i) for i in frame_indices if 0 <= int(i) < n})

    psnr_vals: list[float] = []
    ssim_vals: list[float] = []
    for idx in selected:
        o = orig_frames[idx]
        s = stego_frames[idx]
        psnr_vals.append(psnr(o, s))
        if include_ssim:
            ssim_vals.append(ssim_frame(o, s))

    return {
        "frame_indices": selected,
        "psnr_per_frame": psnr_vals,
        "ssim_per_frame": ssim_vals,
        "n": len(selected),
    }

# ---------------------------------------------------------------------------
# LSB pixel-domain baseline
# ---------------------------------------------------------------------------
def embed_lsb_pixel(frames: np.ndarray, n_bits: int, seed: int = 42) -> np.ndarray:
    """
    Embed n_bits random payload into LSB of Y channel.
    Returns modified frames (float32, same shape).
    Simulates 'naive LSB substitution in decoded pixel domain'.
    """
    rng = np.random.default_rng(seed)
    result = frames.copy()
    payload = rng.integers(0, 2, size=n_bits, dtype=np.uint8)
    flat = result.reshape(-1).astype(np.int16)
    indices = rng.choice(len(flat), size=n_bits, replace=False)
    indices.sort()
    for idx, bit in zip(indices, payload):
        flat[idx] = (int(flat[idx]) & ~1) | int(bit)
    result = np.clip(flat, 0, 255).reshape(frames.shape).astype(np.float32)
    return result

# ---------------------------------------------------------------------------
# JSON cache
# ---------------------------------------------------------------------------
def _json_safe(value):
    """Recursively convert runtime values to strict-JSON-safe values."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]

    # Normalize numpy scalar types first
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        value = value.item()

    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value

    return value


def cache_save(name: str, data: dict) -> None:
    path = RESULTS_DIR / f"{name}.json"
    safe = _json_safe(data)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(safe, f, indent=2, ensure_ascii=False, allow_nan=False)

def cache_load(name: str) -> Optional[dict]:
    path = RESULTS_DIR / f"{name}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None

# ---------------------------------------------------------------------------
# Figure helpers
# ---------------------------------------------------------------------------
def save_fig(fig: plt.Figure, name: str) -> None:
    path = RESULTS_DIR / f"{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [saved] {path.name}")

def annotate_literature(ax: plt.Axes, text: str = "Simulated / literature values") -> None:
    """Add a small footnote on axes indicating simulated data."""
    ax.annotate(
        f"* {text}",
        xy=(0.01, 0.01), xycoords="axes fraction",
        fontsize=8, color="#888888", style="italic",
    )


def sort_positions_round_robin_idrs(
    positions: list[tuple[int, int, int]],
    cif_mb_count: int = CIF_MB_COUNT,
) -> list[tuple[int, int, int]]:
    """Sort positions in strict IDR round-robin with in-frame row interleaving."""
    if not positions:
        return []

    mb_width = 22
    mb_height = max(1, cif_mb_count // mb_width)
    preferred_rows = [r for r in (mb_height - 1, mb_height - 2, mb_height - 3, mb_height - 4) if r >= 0]
    remaining_rows = [r for r in range(mb_height - 1, -1, -1) if r not in preferred_rows]

    by_frame: dict[int, list[tuple[int, int, int]]] = {}
    for pos in positions:
        frame_idx = pos[0] // cif_mb_count
        by_frame.setdefault(frame_idx, []).append(pos)

    for frm in by_frame:
        row_buckets: dict[int, list[tuple[int, int, int]]] = {r: [] for r in range(mb_height)}
        for item in by_frame[frm]:
            local_mb = item[0] % cif_mb_count
            row = local_mb // mb_width
            row_buckets[row].append(item)

        for row in row_buckets:
            row_buckets[row].sort(key=lambda t: (-((t[0] % cif_mb_count) % mb_width), -t[1]))

        def _consume_round_robin(rows: list[int], out: list[tuple[int, int, int]]) -> None:
            if not rows:
                return
            offsets = {r: 0 for r in rows}
            while True:
                progressed = False
                for row in rows:
                    idx = offsets[row]
                    bucket = row_buckets[row]
                    if idx < len(bucket):
                        out.append(bucket[idx])
                        offsets[row] += 1
                        progressed = True
                if not progressed:
                    break

        interleaved_rows: list[tuple[int, int, int]] = []
        # First spread over bottom-4 rows to keep cascade bounded and avoid single-row hotspots.
        _consume_round_robin(preferred_rows, interleaved_rows)
        # Then include the rest of the frame when needed for larger payloads.
        _consume_round_robin(remaining_rows, interleaved_rows)

        by_frame[frm] = interleaved_rows

    frames_asc = sorted(by_frame.keys())
    max_len = max(len(lst) for lst in by_frame.values())
    result: list[tuple[int, int, int]] = []
    for k in range(max_len):
        for frm in frames_asc:
            lst = by_frame[frm]
            if k < len(lst):
                result.append(lst[k])
    return result


# ---------------------------------------------------------------------------
# IDR extraction cache (sec1/sec2/sec3/sec4 runtime accelerator)
# ---------------------------------------------------------------------------
IDR_CACHE_SCHEMA_VERSION = "v2-2026-04-16"


def _idr_cache_enabled() -> bool:
    return (
        os.environ.get("BENCHMARK_TRUSTED_PICKLE_CACHE", "0") == "1"
        or os.environ.get("BENCHMARK_TRUSTED_IDR_PICKLE_CACHE", "0") == "1"
    )


# Backwards-compat alias evaluated at import time (for callers that set env
# before importing _common).  New code should call _idr_cache_enabled().
ENABLE_TRUSTED_IDR_PICKLE_CACHE = _idr_cache_enabled()


def _idr_cache_path(video_path: str | Path) -> Path:
    p = Path(video_path)
    try:
        resolved = str(p.resolve()).encode("utf-8")
    except OSError:
        resolved = str(p).encode("utf-8")
    path_hash = hashlib.sha1(resolved).hexdigest()[:10]
    return RESULTS_DIR / f"_idr_cache_{p.stem}_{path_hash}.pkl"


def _idr_code_fingerprint() -> dict[str, int | str]:
    """Track extractor-dependent source mtimes so cache auto-invalidates on code changes."""
    files = [
        ROOT / "src" / "core" / "pipeline.py",
        ROOT / "src" / "core" / "stego.py",
    ]
    fp: dict[str, int | str] = {"schema": IDR_CACHE_SCHEMA_VERSION}
    for f in files:
        key = f.relative_to(ROOT).as_posix()
        try:
            fp[key] = int(f.stat().st_mtime_ns)
        except OSError:
            fp[key] = "missing"
    return fp


def load_or_extract_idr_blocks(
    video_path: str | Path,
    reconstructor,
    force: bool = False,
) -> tuple:
    """
    Load cached output of extract_all_idr_blocks() when source video is unchanged.

    Cache payload:
      - video_path / size / mtime fingerprint
      - extracted tuple:
        (coeffs, frame_verified_data, nC_map, nal_length_map, t1_override_map)
    """
    from src.core.pipeline import extract_all_idr_blocks

    vp = Path(video_path)
    cp = _idr_cache_path(vp)
    try:
        stat = vp.stat()
        fingerprint = {
            "path": str(vp.resolve()),
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "code": _idr_code_fingerprint(),
        }
    except OSError:
        return extract_all_idr_blocks(str(vp), reconstructor)

    if _idr_cache_enabled() and not force and cp.exists():
        try:
            with open(cp, "rb") as f:
                payload = pickle.load(f)
            if payload.get("fingerprint") == fingerprint and "data" in payload:
                return payload["data"]
        except (OSError, pickle.PickleError, EOFError, AttributeError, ValueError):
            pass

    data = extract_all_idr_blocks(str(vp), reconstructor)
    if _idr_cache_enabled():
        try:
            with open(cp, "wb") as f:
                pickle.dump({"fingerprint": fingerprint, "data": data}, f, protocol=pickle.HIGHEST_PROTOCOL)
        except OSError:
            pass
    return data
