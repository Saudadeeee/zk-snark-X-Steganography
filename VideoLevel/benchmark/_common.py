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

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# CIF resolution used by all test sequences
WIDTH, HEIGHT = 352, 288
CIF_MB_COUNT = 396  # 22x18

# Test sequences: full-length + additional CIF variants from encoded assets.
# foreman=300f (6x loop of 50f source), coastguard=300f, deadline=1374f.
# Added short/variant clips to broaden benchmark coverage.
SEQUENCES = {
    "foreman":    DATA_DIR / "foreman_cif_300_g8.h264",
    "coastguard": DATA_DIR / "coastguard_cif_full_g8.h264",
    "deadline":   DATA_DIR / "deadline_cif_full_g8.h264",
    "foreman_long": DATA_DIR / "foreman_cif_1200_g8.h264",
    "coastguard_long": DATA_DIR / "coastguard_cif_1200_g8.h264",
    "akiyo": DATA_DIR / "akiyo_cif_g8.h264",
    "foreman_hq": DATA_DIR / "foreman_cif_hq.h264",
    "coastguard_short": DATA_DIR / "coastguard_cif_g8.h264",
    # All-intra (GOP=1) QP=22 — eliminates P-frame cascade for high-quality stego
    "foreman_q22_g1": DATA_DIR / "foreman_cif_q22_g1.h264",
    "coastguard_q22_g1": DATA_DIR / "coastguard_cif_q22_g1.h264",
    # 1000-frame all-intra QP=22 — lower flips/IDR → better per-frame min PSNR
    "foreman_q22_g1_1000": DATA_DIR / "foreman_cif_q22_g1_1000.h264",
    "coastguard_q22_g1_1000": DATA_DIR / "coastguard_cif_q22_g1_1000.h264",
}

SEQ_FRAMES = {
    "foreman":    300,
    "coastguard": 300,
    "deadline":   1374,
    "foreman_long": 1200,
    "coastguard_long": 1200,
    "akiyo": 50,
    "foreman_hq": 50,
    "coastguard_short": 50,
    "foreman_q22_g1": 300,
    "coastguard_q22_g1": 300,
    "foreman_q22_g1_1000": 1000,
    "coastguard_q22_g1_1000": 1000,
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

MARKERS = ["o", "s", "^", "D", "v", "P"]
LINESTYLES = ["-", "--", "-.", ":", (0,(3,1,1,1)), (0,(5,1))]

SEQ_LABELS = {
    "foreman":    "Foreman (low motion)",
    "coastguard": "Coastguard (high motion)",
    "deadline":   "Deadline (mixed)",
    "foreman_long": "Foreman long (1200f)",
    "coastguard_long": "Coastguard long (1200f)",
    "akiyo": "Akiyo (very low motion)",
    "foreman_hq": "Foreman HQ (short)",
    "coastguard_short": "Coastguard short (50f)",
    "foreman_q22_g1": "Foreman all-intra QP22",
    "coastguard_q22_g1": "Coastguard all-intra QP22",
    "foreman_q22_g1_1000": "Foreman all-intra QP22 (1000f)",
    "coastguard_q22_g1_1000": "Coastguard all-intra QP22 (1000f)",
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
        "lines.markersize":         7,
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
def decode_luma_frames(h264_path: str | Path, max_frames: int = 9999) -> np.ndarray:
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


def _decode_raw_bytes(h264_path: str | Path) -> bytes:
    """Run ffmpeg and return raw yuv420p bytes (no frame array allocation)."""
    cmd = [
        "ffmpeg", "-i", str(h264_path),
        "-f", "rawvideo", "-pix_fmt", "yuv420p",
        "-vf", f"scale={WIDTH}:{HEIGHT}",
        "pipe:1", "-loglevel", "quiet",
    ]
    result = subprocess.run(cmd, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()}")
    return result.stdout


def compute_quality_streaming(
    orig_path: str | Path,
    stego_path: str | Path,
    max_frames: int = 9999,
) -> dict:
    """
    Compute per-frame and full-video PSNR/SSIM without holding large frame arrays.

    Decodes both videos to raw bytes (~145 MB each), then processes one frame
    pair at a time.  Peak memory ~290 MB vs ~774 MB for float32 full arrays.

    Returns dict with keys:
      psnr_per_frame, ssim_per_frame, psnr_full_video, n
    """
    from skimage.metrics import structural_similarity

    orig_raw = _decode_raw_bytes(orig_path)
    stego_raw = _decode_raw_bytes(stego_path)

    frame_size_420 = WIDTH * HEIGHT * 3 // 2
    luma_size = WIDTH * HEIGHT
    n = min(
        len(orig_raw) // frame_size_420,
        len(stego_raw) // frame_size_420,
        max_frames,
    )

    psnr_list: list[float] = []
    ssim_list: list[float] = []
    total_ssd = 0.0
    total_pixels = 0

    for i in range(n):
        base = i * frame_size_420
        o = np.frombuffer(orig_raw[base: base + luma_size], dtype=np.uint8).reshape(HEIGHT, WIDTH)
        s = np.frombuffer(stego_raw[base: base + luma_size], dtype=np.uint8).reshape(HEIGHT, WIDTH)

        diff = o.astype(np.float32) - s.astype(np.float32)
        ssd = float(np.dot(diff.ravel(), diff.ravel()))
        total_ssd += ssd
        total_pixels += luma_size

        frame_mse = ssd / luma_size
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
