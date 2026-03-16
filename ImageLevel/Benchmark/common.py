"""
Benchmark Common Utilities
==========================
Shared utilities for all benchmark modules:
  - DICOM loading + stego pair generation
  - Baseline embedding implementations (Sequential LSB, PRNG-LSB, ACM-only)
  - Consistent color palette and chart helpers
  - Results directory management
"""

import os
import sys
import json
import hashlib
import tempfile
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Any

# ── project root on sys.path ──────────────────────────────────────────────────
BENCH_DIR   = Path(__file__).resolve().parent
PROJECT_DIR = BENCH_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

DICOM_DIR   = PROJECT_DIR / "examples" / "dicom"
CHAOS_KEY   = "zkdicom_chaos_key_v1"
PROOF_KEY   = "zkdicom_proof_key_v1"

# ── chart style ───────────────────────────────────────────────────────────────
matplotlib.rcParams.update({
    "font.family":       "DejaVu Sans",
    "font.size":         11,
    "axes.titlesize":    13,
    "axes.labelsize":    11,
    "legend.fontsize":   10,
    "figure.dpi":        120,
    "savefig.dpi":       150,
    "savefig.bbox":      "tight",
})

# Method colour palette (consistent across all charts)
METHOD_COLORS = {
    "Cover":          "#2196F3",   # blue
    "Sequential LSB": "#F44336",   # red
    "PRNG-LSB":       "#4CAF50",   # green
    "ACM-only":       "#FF9800",   # orange
    "This Work":      "#9C27B0",   # purple
}
METHOD_ORDER = ["Cover", "Sequential LSB", "PRNG-LSB", "ACM-only", "This Work"]
METHOD_MARKERS = {
    "Cover":          "o",
    "Sequential LSB": "s",
    "PRNG-LSB":       "^",
    "ACM-only":       "D",
    "This Work":      "*",
}


# =============================================================================
# DICOM + STEGO LOADING
# =============================================================================

def list_dicom_files() -> List[Path]:
    """Return all .dcm files in examples/dicom/."""
    if not DICOM_DIR.exists():
        raise FileNotFoundError(
            f"DICOM directory not found: {DICOM_DIR}\n"
            "Please add DICOM test files (.dcm) to examples/dicom/"
        )
    dcm_files = sorted(DICOM_DIR.glob("*.dcm"))
    if not dcm_files:
        raise FileNotFoundError(
            f"No .dcm files found in {DICOM_DIR}\n"
            "Please add DICOM test files (.dcm) to examples/dicom/"
        )
    return dcm_files


def load_dicom_cover(dcm_path: Path) -> Tuple[np.ndarray, str]:
    """Load DICOM as uint16. Returns (pixel_array, stem_name)."""
    from src.zk_stego.dicom_handler import DicomHandler
    pixel_array, _, _ = DicomHandler.load(str(dcm_path))
    return pixel_array, dcm_path.stem


def make_stego_pair(
    dcm_path: Path,
    tmp_dir: Optional[Path] = None,
    chaos_key: str = CHAOS_KEY,
    verbose: bool = False,
) -> Tuple[np.ndarray, np.ndarray, Dict]:
    """
    Embed DICOM metadata into stego PNG (no ZK proof) and return:
        (cover_uint16, stego_uint16, embed_result_dict)
    Uses a temp PNG that is cleaned up automatically.
    """
    from src.zk_stego.dicom_handler import DicomStego, DicomHandler

    cover, _, _ = DicomHandler.load(str(dcm_path))

    with tempfile.NamedTemporaryFile(
        suffix=".png", dir=tmp_dir, delete=False
    ) as f:
        tmp_png = f.name

    try:
        ds = DicomStego()
        result = ds.embed(
            str(dcm_path), tmp_png,
            chaos_key=chaos_key,
            generate_zk_proof=False,
            verbose=verbose,
        )
        from PIL import Image
        stego = np.array(Image.open(tmp_png), dtype=np.uint16)
    finally:
        if os.path.exists(tmp_png):
            os.unlink(tmp_png)

    return cover, stego, result


# =============================================================================
# QUALITY METRICS
# =============================================================================

def psnr(cover: np.ndarray, stego: np.ndarray, data_range: int = 65535) -> float:
    """PSNR for 16-bit images.  data_range=65535."""
    mse = float(np.mean((cover.astype(np.float64) - stego.astype(np.float64)) ** 2))
    if mse == 0:
        return float("inf")
    return float(10.0 * np.log10(data_range ** 2 / mse))


def ssim(cover: np.ndarray, stego: np.ndarray, data_range: int = 65535) -> float:
    """SSIM for 16-bit images."""
    try:
        from skimage.metrics import structural_similarity
        return float(structural_similarity(cover, stego, data_range=data_range))
    except ImportError:
        # Manual SSIM (Wang et al. 2004)
        c1 = (0.01 * data_range) ** 2
        c2 = (0.03 * data_range) ** 2
        mu1 = float(np.mean(cover, dtype=np.float64))
        mu2 = float(np.mean(stego, dtype=np.float64))
        sigma1sq = float(np.var(cover, dtype=np.float64))
        sigma2sq = float(np.var(stego, dtype=np.float64))
        sigma12  = float(np.mean((cover.astype(np.float64) - mu1) *
                                 (stego.astype(np.float64) - mu2)))
        num = (2 * mu1 * mu2 + c1) * (2 * sigma12 + c2)
        den = (mu1 ** 2 + mu2 ** 2 + c1) * (sigma1sq + sigma2sq + c2)
        return float(num / den) if den != 0 else 1.0


def mse_metric(cover: np.ndarray, stego: np.ndarray) -> float:
    return float(np.mean((cover.astype(np.float64) - stego.astype(np.float64)) ** 2))


def bpp(stego: np.ndarray, payload_bits: int) -> float:
    """Bits per pixel embedded."""
    total_pixels = stego.size
    return payload_bits / total_pixels if total_pixels > 0 else 0.0


# =============================================================================
# BASELINE EMBEDDING (2 bits/pixel to match DicomStego)
# =============================================================================

def _embed_2bit(img: np.ndarray, positions: List[Tuple[int, int]], bits: List[int]) -> np.ndarray:
    """Embed 2 bits per pixel (bits 1 and 0) at given positions."""
    out = img.copy()
    for i, (x, y) in enumerate(positions):
        b_idx = i * 2
        b0 = int(bits[b_idx])     if b_idx     < len(bits) else 0
        b1 = int(bits[b_idx + 1]) if b_idx + 1 < len(bits) else 0
        out[y, x] = (int(out[y, x]) & 0xFFFC) | ((b0 & 1) << 1) | (b1 & 1)
    return out


def embed_sequential_lsb(cover: np.ndarray, bits: List[int]) -> np.ndarray:
    """
    Baseline A: Sequential left-to-right, top-to-bottom, 2-bit/pixel.
    Weakest possible scheme — maximum RS detectability.
    Fully vectorised: operates on flat array, no Python loops.
    """
    out   = cover.copy()
    flat  = out.ravel()
    n_pix = min(len(flat), (len(bits) + 1) // 2)
    ba    = np.array(bits[:n_pix * 2], dtype=np.uint16)
    if len(ba) < n_pix * 2:
        ba = np.pad(ba, (0, n_pix * 2 - len(ba)))
    ba    = ba.reshape(n_pix, 2)
    flat[:n_pix] = ((flat[:n_pix].astype(np.uint16) & np.uint16(0xFFFC))
                    | ((ba[:, 0] & 1) << 1) | (ba[:, 1] & 1))
    return out


def embed_prng_lsb(cover: np.ndarray, bits: List[int], seed: int = 42) -> np.ndarray:
    """
    Baseline B: PRNG-shuffled flat indices (numpy RNG), 2-bit/pixel.
    Seeded PRNG — better spread than sequential but no chaos structure.
    Fully vectorised: no Python loops, no tuple list comprehensions.
    """
    out   = cover.copy()
    flat  = out.ravel()
    n_pix = min(len(flat), (len(bits) + 1) // 2)
    rng   = np.random.default_rng(seed)
    idx   = rng.permutation(len(flat))[:n_pix]
    ba    = np.array(bits[:n_pix * 2], dtype=np.uint16)
    if len(ba) < n_pix * 2:
        ba = np.pad(ba, (0, n_pix * 2 - len(ba)))
    ba    = ba.reshape(n_pix, 2)
    flat[idx] = ((flat[idx].astype(np.uint16) & np.uint16(0xFFFC))
                 | ((ba[:, 0] & 1) << 1) | (ba[:, 1] & 1))
    return out


def embed_acm_only(cover: np.ndarray, bits: List[int],
                   x0: int = 256, y0: int = 256) -> np.ndarray:
    """
    Baseline C: Pure Arnold Cat Map (no Logistic Map perturbation), 2-bit/pixel.
    Isolates the ACM contribution from the full chaos system.
    Vectorised: ACM orbit detected and capped; sequential numpy fallback for remainder.
    """
    h, w = cover.shape
    n_positions = min((len(bits) + 1) // 2, h * w)

    # --- collect the ACM orbit (terminates when it cycles back to start) ------
    sx, sy = x0 % w, y0 % h
    ox, oy = [sx], [sy]
    x, y = sx, sy
    for _ in range(h * w - 1):
        xn = (2 * x + y) % w
        yn = (x + y) % h
        x, y = xn, yn
        if x == sx and y == sy:
            break      # full orbit completed
        ox.append(x); oy.append(y)

    orbit_flat = np.array(oy, dtype=np.int64) * w + np.array(ox, dtype=np.int64)

    # --- sequential fallback if orbit smaller than needed --------------------
    if len(orbit_flat) < n_positions:
        used_mask = np.zeros(h * w, dtype=bool)
        used_mask[orbit_flat] = True
        remaining = np.flatnonzero(~used_mask)
        need = n_positions - len(orbit_flat)
        flat_idx = np.concatenate([orbit_flat, remaining[:need]])
    else:
        flat_idx = orbit_flat[:n_positions]

    # --- vectorised embed (2 bits per pixel, bits 1 and 0) -------------------
    out  = cover.copy()
    flat = out.ravel()
    ba   = np.array(bits[:n_positions * 2], dtype=np.uint16)
    if len(ba) < n_positions * 2:
        ba = np.pad(ba, (0, n_positions * 2 - len(ba)))
    ba = ba.reshape(n_positions, 2)
    flat[flat_idx] = ((flat[flat_idx].astype(np.uint16) & np.uint16(0xFFFC))
                      | ((ba[:, 0] & 1) << 1) | (ba[:, 1] & 1))
    return out


def embed_this_work(cover: np.ndarray, bits: List[int],
                    chaos_key: str = CHAOS_KEY,
                    _roi_cache: dict = {}) -> np.ndarray:
    """
    This Work: DicomStego chaos+ROI position selection, vectorised embed.
    Uses the actual system's position selection (ACM + Logistic Map + ROI).
    ROI mask is cached per image (keyed by id) to avoid recomputation.
    """
    from src.zk_stego.dicom_handler import DicomHandler
    from src.zk_stego.utils import generate_chaos_key_from_secret
    from src.zk_stego.dicom_handler import DicomStego

    cache_key = id(cover)
    if cache_key not in _roi_cache:
        _roi_cache[cache_key] = DicomHandler.detect_roi(cover)
    roi_mask = _roi_cache[cache_key]

    chaos_key_int = generate_chaos_key_from_secret(chaos_key)
    h, w = cover.shape
    x0, y0 = DicomStego._key_start(chaos_key_int, w, h, roi_mask)

    # cap n to available ROI capacity to avoid ValueError
    roi_capacity = int(np.sum(roi_mask))
    n = min((len(bits) + 1) // 2, roi_capacity)

    positions = DicomStego._roi_positions(
        cover, roi_mask, x0, y0, chaos_key_int, n,
        sort_by_entropy=False, exclude=None
    )

    # vectorised embed — no Python loop over positions
    pos_arr  = np.asarray(positions, dtype=np.int64)   # (n, 2) = (x, y)
    flat_idx = pos_arr[:, 1] * w + pos_arr[:, 0]       # y*w + x
    n_pos    = len(flat_idx)
    ba       = np.array(bits[:n_pos * 2], dtype=np.uint16)
    if len(ba) < n_pos * 2:
        ba = np.pad(ba, (0, n_pos * 2 - len(ba)))
    ba = ba.reshape(n_pos, 2)

    out  = cover.copy()
    flat = out.ravel()
    flat[flat_idx] = ((flat[flat_idx].astype(np.uint16) & np.uint16(0xFFFC))
                      | ((ba[:, 0] & 1) << 1) | (ba[:, 1] & 1))
    return out


# Map method name -> embed function
EMBED_FUNCS = {
    "Sequential LSB": embed_sequential_lsb,
    "PRNG-LSB":       embed_prng_lsb,
    "ACM-only":       embed_acm_only,
    "This Work":      embed_this_work,
}


def make_random_bits(n: int, seed: int = 0) -> List[int]:
    """Generate deterministic random bits for payload sweeps."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 2, size=n).tolist()


# =============================================================================
# RS ANALYSIS  (Fridrich, Goljan, Du — 2001)
# =============================================================================

def rs_analysis(img_array: np.ndarray) -> Dict[str, float]:
    """
    RS Analysis for 16-bit grayscale images.
    Uses 4-pixel horizontal groups with mask M=(0,1,0,1):
      F_1  : flip bit-0 at mask=1 positions
      F_{-1}: if even subtract-1 else add-1 at mask=1 positions

    Returns dict with Rm, Sm, Rm_, Sm_, Rm-Sm, p_hat.
    """
    arr = img_array.astype(np.int64).ravel()
    n   = (len(arr) // 4) * 4
    g   = arr[:n].reshape(-1, 4)                       # (N, 4) — fully vectorised

    def _smooth_v(x: np.ndarray) -> np.ndarray:
        return (np.abs(x[:, 1] - x[:, 0]) +
                np.abs(x[:, 2] - x[:, 1]) +
                np.abs(x[:, 3] - x[:, 2]))

    f0 = _smooth_v(g)

    # F_1: flip LSB at cols 1 and 3
    g1 = g.copy(); g1[:, 1] ^= 1; g1[:, 3] ^= 1
    f1 = _smooth_v(g1)

    # F_{-1}: even->value-1, odd->value+1 at cols 1 and 3
    gn = g.copy()
    for c in (1, 3):
        even_m = (gn[:, c] % 2) == 0
        gn[even_m,  c] -= 1
        gn[~even_m, c] += 1
    fn = _smooth_v(gn)

    total = len(g)
    Rm  = int(np.sum(f1 > f0));  Sm  = int(np.sum(f1 < f0))
    Rm_ = int(np.sum(fn > f0));  Sm_ = int(np.sum(fn < f0))

    rm, sm   = Rm / total,  Sm / total
    rm_, sm_ = Rm_ / total, Sm_ / total

    denom = rm - rm_ + sm_ - sm
    # NOTE: for 16-bit images, rm - rm_ ≈ -(sm_ - sm) always, so denom ≈ 2*(rm-rm_)
    # making p_hat always ~0.5.  This is a known limitation of the RS formula for 16-bit
    # data — the formula was designed for 8-bit images.  Mark as invalid when symmetric.
    numerator = rm - rm_
    symmetric = abs(denom) > 1e-12 and abs(abs(numerator / denom) - 0.5) < 0.01
    if abs(denom) < 1e-12 or symmetric:
        p_hat       = 0.5        # formula degenerate — not meaningful
        p_hat_valid = False
    else:
        p_hat       = float(np.clip(numerator / denom, 0.0, 1.0))
        p_hat_valid = True

    return {
        "Rm": rm, "Sm": sm, "Rm_": rm_, "Sm_": sm_,
        "Rm-Sm": rm - sm, "Rm_-Sm_": rm_ - sm_,
        "p_hat": p_hat, "p_hat_valid": p_hat_valid,
    }


# =============================================================================
# CHI-SQUARE ATTACK  (Westfeld & Pfitzmann 1999)
# =============================================================================

def chi_square_attack(img_array: np.ndarray) -> float:
    """
    Returns p-value: large -> not detectable; small (< 0.05) -> detected.
    Measures the natural vs forced 50/50 split between PoV pairs (value, value+1).
    """
    from scipy.stats import chi2 as chi2dist
    pixels = img_array.astype(np.int64).ravel()
    counts = np.bincount(pixels, minlength=65536)
    # Compare even vs odd values in pairs
    even_c = counts[0::2]
    odd_c  = counts[1::2]
    expected = (even_c + odd_c) / 2.0
    # chi2 only over pairs where at least one value exists
    mask = (even_c + odd_c) > 0
    chi_sq = float(np.sum((even_c[mask] - expected[mask]) ** 2 / (expected[mask] + 1e-9)))
    df = int(np.sum(mask)) - 1
    if df <= 0:
        return 1.0
    return float(chi2dist.sf(chi_sq, df=df))


# =============================================================================
# SPA ANALYSIS  (Dumitrescu et al. 2003 — simplified)
# =============================================================================

def spa_analysis(img_array: np.ndarray) -> Dict[str, float]:
    """
    Sample Pairs Analysis (Dumitrescu et al. 2003 — simplified).
    Counts horizontally-adjacent pairs by relative value.
    alpha = (Cp1+Cm1)/(2*C0): close-pair ratio.
    p_hat = |Cp1-Cm1|/(2*C0+Cp1+Cm1): asymmetry normalized by total pairs.
    NOTE: designed for 8-bit images; values will be small for 16-bit DICOM at low BPP.
    """
    arr = img_array.astype(np.int64)
    h, w = arr.shape
    P = arr[:, :-1].ravel()
    Q = arr[:, 1:].ravel()
    d = P - Q
    C0   = int(np.sum(d ==  0))
    Cp1  = int(np.sum(d ==  1))
    Cm1  = int(np.sum(d == -1))
    total = len(d)
    alpha = (Cp1 + Cm1) / (2 * C0) if C0 > 0 else 0.0
    # Normalize by total pairs for a fraction that's comparable across methods
    p_hat = float(np.clip(abs(Cp1 - Cm1) / (total + 1e-9), 0.0, 1.0))
    return {
        "C0": C0, "Cp1": Cp1, "Cm1": Cm1,
        "alpha": float(alpha), "p_hat": p_hat,
    }


# =============================================================================
# CHART HELPERS
# =============================================================================

def save_figure(fig: plt.Figure, path: Path, also_pdf: bool = False) -> None:
    """Save figure as PNG (and optionally PDF)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(path))
    if also_pdf:
        fig.savefig(str(path.with_suffix(".pdf")))
    plt.close(fig)
    print(f"  Saved: {path}")


def results_dir(benchmark_subdir: str) -> Path:
    """Return the results/ directory for a benchmark sub-module."""
    d = BENCH_DIR / benchmark_subdir / "results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=lambda x: float(x) if isinstance(x, (np.floating,)) else int(x) if isinstance(x, (np.integer,)) else x)
    print(f"  Saved: {path}")
