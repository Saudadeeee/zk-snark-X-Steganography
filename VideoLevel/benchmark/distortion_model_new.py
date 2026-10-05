"""Distortion model of trailing-one sign embedding, and its experimental validation.

Model (paper, Section "Distortion model"):

    one sign flip changes a quantized level by 2, so before rounding its pixel-domain
    energy is SSE_1 = 4 * Qstep(QP)^2 * kappa, kappa in [0.925, 1.057] (exactly 1 for
    the even/even coefficient class and for every DC path)
    frame SSE ~= G * sum_k SSE_1(QP_k), G >= 1 the spread through intra prediction
    and deblocking
    inverse: N_flip_max(T) = 255^2 * W * H * 10^(-T/10) / (4 * Qstep^2 * G), and the
    per-IDR cap is N_flip_max / p with p = 1/2 for whitened bits

Experiments (``py -3.12 -m benchmark.distortion_model_new``):

    A  sequence level: the 27 cover/stego pairs of the recorded media run; flips are read
       from the bitstreams, measured SSE from FFmpeg decodes
    B  single flips: two x264 configurations x three QPs on one IDR; every sampled flip is
       decoded alone, with and without the deblocking filter
    C  inverse check: per-IDR cap from a target PSNR, real native embedding, measured
       per-frame PSNR

Results go to benchmark/results/distortion_new/.
"""
from __future__ import annotations

import math
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

from benchmark.media_benchmark_new import _tool
from src.video_binding import ebsp_to_rbsp, split_annex_b

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "demo"))
import h264_explain as hx  # noqa: E402  (exact dequantization and inverse transform)

OUT = ROOT / "benchmark" / "results" / "distortion_new"
MEDIA_RUN = ROOT / "benchmark" / "results" / "media_new" / "20261004T142448Z_1db00a"
RAW = ROOT / "data" / "raw"

_QSTEP_BASE = (0.625, 0.6875, 0.8125, 0.875, 1.0, 1.125)
_CHROMA_QP = (29, 30, 31, 32, 32, 33, 34, 34, 35, 35, 36, 36, 37, 37, 37, 38, 38, 38, 39, 39, 39, 39)
_NORM_ADJUST = ((10, 16, 13), (11, 18, 14), (13, 20, 16), (14, 23, 18), (16, 25, 20), (18, 29, 23))
_BASIS_NORM = (4.0, 2.5, 4.0, 2.5)  # squared norms of the inverse-transform rows b0..b3
CATEGORY_NAMES = ("LumaDC", "Luma4x4", "ChromaDC", "ChromaAC")
# x264 encoder configurations of experiment B: the benchmark's (Intra16x16 only, no
# deblocking) and the library default (Intra4x4 + Intra16x16, deblocking on).
CONFIGS = {
    "ultrafast": ["-preset", "ultrafast", "-tune", "zerolatency"],
    "default": ["-preset", "medium"],
}


# ------------------------------------------------------------------ model

def qstep(qp: int) -> float:
    """H.264 quantizer step size; doubles every 6 QP (Qstep = v0(QP mod 6) / 16 * 2^(QP // 6))."""
    if not 0 <= qp <= 51:
        raise ValueError("QP must be in 0..51")
    return _QSTEP_BASE[qp % 6] * 2 ** (qp // 6)


def chroma_qp(qp: int, offset: int) -> int:
    """QPc from the luma QP and chroma_qp_index_offset (Table 8-15)."""
    index = min(max(qp + offset, 0), 51)
    return index if index < 30 else _CHROMA_QP[index - 30]


def flip_sse(qp: int) -> float:
    """Model energy of one sign flip: 4 * Qstep^2."""
    return 4.0 * qstep(qp) ** 2


def flip_sse_exact(qp: int, row: int, col: int) -> float:
    """Pre-rounding energy of a level change of 2 at raster (row, col) of a 4x4 block."""
    parity = 0 if row % 2 == 0 and col % 2 == 0 else 1 if row % 2 and col % 2 else 2
    delta = 2 * _NORM_ADJUST[qp % 6][parity] * 2 ** (qp // 6)
    return (delta / 64.0) ** 2 * _BASIS_NORM[row] * _BASIS_NORM[col]


def kappa(qp: int, row: int, col: int) -> float:
    return flip_sse_exact(qp, row, col) / flip_sse(qp)


def psnr_from_sse(sse: float, pixels: int) -> float:
    return math.inf if sse <= 0 else 10.0 * math.log10(255.0 ** 2 * pixels / sse)


def max_flips(target_psnr: float, qp: int, gain: float, pixels: int) -> float:
    """Largest number of flips per frame whose predicted PSNR stays >= target_psnr."""
    if gain <= 0 or pixels <= 0:
        raise ValueError("gain and pixels must be positive")
    return 255.0 ** 2 * pixels * 10 ** (-target_psnr / 10.0) / (gain * flip_sse(qp))


def cap_for_target(target_psnr: float, qp: int, gain: float, pixels: int, flip_probability: float = 0.5) -> int:
    """Per-IDR bit cap: whitened frame bits flip their sign with probability 1/2."""
    if not 0 < flip_probability <= 1:
        raise ValueError("flip probability must be in (0, 1]")
    return max(1, int(max_flips(target_psnr, qp, gain, pixels) / flip_probability))


def exact_block_flip_sse(scan: list[int], qp: int) -> float:
    """Exact (rounded) residual energy of flipping the last non-zero +-1 of a 16-coefficient block."""
    position = max(i for i, value in enumerate(scan) if value)
    if abs(scan[position]) != 1:
        raise ValueError("the flipped coefficient must be a trailing one")
    flipped = list(scan)
    flipped[position] = -flipped[position]
    before = hx.inverse_transform(hx.dequantize(hx.scan_to_matrix(scan), qp))[2]
    after = hx.inverse_transform(hx.dequantize(hx.scan_to_matrix(flipped), qp))[2]
    return float(sum((a - b) ** 2 for ra, rb in zip(after, before) for a, b in zip(ra, rb)))


def flipped_raster(scan: list[int], category: int) -> tuple[int, int]:
    """Raster (row, col) of the coefficient whose sign carries the bit (the last trailing one)."""
    if category in (0, 2):
        return 0, 0  # DC paths: same energy as the (0, 0) class
    offset = 16 - len(scan)  # AC-only blocks start at zig-zag index 1
    position = max(i for i, value in enumerate(scan) if value) + offset
    raster = hx.ZIGZAG_4x4[position]
    return raster // 4, raster % 4


def plane_of(category: int, block: int) -> int:
    if category in (0, 1):
        return 0
    return 1 + (block if category == 2 else block // 4)


# ------------------------------------------------------------------ media helpers

def _run(args: list[str], stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(args, input=stdin, capture_output=True, check=False, timeout=3600)
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).name} failed: {result.stderr.decode(errors='replace')[-400:]}")
    return result


def decode_planes(path: Path, width: int, height: int, *, deblock: bool = True) -> list[np.ndarray]:
    """Decoded frames as [Y, U, V] arrays of shape (frames, h, w)."""
    args = [_tool("ffmpeg"), "-v", "error", "-nostdin"]
    if not deblock:
        args += ["-skip_loop_filter", "all"]
    args += ["-i", str(path), "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"]
    raw = np.frombuffer(_run(args).stdout, dtype=np.uint8)
    frame = width * height * 3 // 2
    frames = raw.reshape(-1, frame)
    luma = width * height
    chroma = luma // 4
    return [frames[:, :luma].reshape(-1, height, width).astype(np.int32),
            frames[:, luma:luma + chroma].reshape(-1, height // 2, width // 2).astype(np.int32),
            frames[:, luma + chroma:].reshape(-1, height // 2, width // 2).astype(np.int32)]


def frame_sse(a: list[np.ndarray], b: list[np.ndarray]) -> np.ndarray:
    """SSE per frame and plane, shape (frames, 3)."""
    return np.stack([((x - y) ** 2).reshape(x.shape[0], -1).sum(axis=1) for x, y in zip(a, b)], axis=1)


_PIC_INIT = re.compile(r"pic_init_qp_minus26\s+\S+\s+=\s+(-?\d+)")
_CHROMA_OFFSET = re.compile(r"chroma_qp_index_offset\s+\S+\s+=\s+(-?\d+)")
_SLICE_DELTA = re.compile(r"slice_qp_delta\s+\S+\s+=\s+(-?\d+)")


def slice_qps(path: Path) -> tuple[list[int], int]:
    """(QP of every slice in file order, chroma_qp_index_offset) read by FFmpeg's trace_headers."""
    log = subprocess.run([_tool("ffmpeg"), "-hide_banner", "-nostdin", "-i", str(path), "-c:v", "copy",
                          "-bsf:v", "trace_headers", "-f", "null", "-"],
                         capture_output=True, check=False, timeout=3600).stderr.decode(errors="replace")
    init = [int(v) for v in _PIC_INIT.findall(log)]
    offsets = {int(v) for v in _CHROMA_OFFSET.findall(log)}
    deltas = [int(v) for v in _SLICE_DELTA.findall(log)]
    if not init or len(offsets) != 1 or len(set(init)) != 1:
        raise RuntimeError(f"unexpected parameter sets in {path.name}")
    return [26 + init[0] + delta for delta in deltas], offsets.pop()


def x264_options(path: Path) -> dict[str, str]:
    text = path.read_bytes()[:4096].decode("latin-1")
    match = re.search(r"options: ([^\x00]+)", text)
    if not match:
        raise RuntimeError(f"no x264 SEI in {path.name}")
    return dict(item.split("=", 1) for item in match.group(1).split() if "=" in item)


def flipped_bits(cover: bytes, stego: bytes) -> list[tuple[int, int]]:
    """(NAL index, RBSP bit) of every bit that differs between two bitstreams with the same NAL layout."""
    left, right = split_annex_b(cover), split_annex_b(stego)
    if len(left) != len(right):
        raise RuntimeError("cover and stego have different NAL counts")
    flips = []
    for index, ((_, a), (_, b)) in enumerate(zip(left, right)):
        ra, rb = ebsp_to_rbsp(a), ebsp_to_rbsp(b)
        if len(ra) != len(rb):
            raise RuntimeError(f"NAL {index}: RBSP length changed")
        for byte, (x, y) in enumerate(zip(ra, rb)):
            diff = x ^ y
            flips += [(index, byte * 8 + bit) for bit in range(8) if diff & (0x80 >> bit)]
    return flips
