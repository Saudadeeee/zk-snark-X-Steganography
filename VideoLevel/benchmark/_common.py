"""
_common.py — Shared utilities for all benchmark sections.

Provides: path constants, matplotlib style, video decode/PSNR/SSIM helpers,
          JSON cache helpers, and figure save/close utilities.
"""

import json
import math
import os
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

# Test sequences: full-length encodes from .y4m source
# foreman=300f (6x loop of 50f source, matching standard CIF full-length)
# coastguard=300f, deadline=1374f
SEQUENCES = {
    "foreman":    DATA_DIR / "foreman_cif_300_g8.h264",
    "coastguard": DATA_DIR / "coastguard_cif_full_g8.h264",
    "deadline":   DATA_DIR / "deadline_cif_full_g8.h264",
}

SEQ_FRAMES = {
    "foreman":    300,
    "coastguard": 300,
    "deadline":   1374,
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
    Decode H.264 -> array of Y (luma) frames, shape (N, H, W), dtype float64.
    Uses ffmpeg subprocess.
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
    frames = []
    for i in range(n_frames):
        start = i * frame_size_420
        y = np.frombuffer(raw[start: start + WIDTH * HEIGHT], dtype=np.uint8)
        frames.append(y.reshape(HEIGHT, WIDTH).astype(np.float64))
    return np.array(frames)

# ---------------------------------------------------------------------------
# Quality metrics
# ---------------------------------------------------------------------------
def psnr(orig: np.ndarray, stego: np.ndarray) -> float:
    """PSNR in dB between two same-shape arrays (luma frames or full video)."""
    mse = np.mean((orig - stego) ** 2)
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

# ---------------------------------------------------------------------------
# LSB pixel-domain baseline
# ---------------------------------------------------------------------------
def embed_lsb_pixel(frames: np.ndarray, n_bits: int, seed: int = 42) -> np.ndarray:
    """
    Embed n_bits random payload into LSB of Y channel.
    Returns modified frames (float64, same shape).
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
    result = np.clip(flat, 0, 255).reshape(frames.shape).astype(np.float64)
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
