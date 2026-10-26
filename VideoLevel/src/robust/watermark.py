"""Dither-modulation QIM on low-order DCT coefficients of 16x16 luma blocks.

Carrier choice (measured, ``docs/ROBUST_MODE.md``): 8x8 mid-band carriers
lose 20-45 % of their bits to one x264 CRF 23 re-encode; 16x16 low-order
carriers whose bits stay constant over ``group`` consecutive frames lose far
fewer, because an inter encoder that skips or copies a block from the
previous frame then copies the right bit.

A *position* is one (carrier block, coefficient) pair of a frame, numbered
``block * len(coefficients) + k`` in raster block order.  A *slot* is a
position in one temporal group of ``group`` frames (trailing frames join the
last group); all frames of a group carry the same slot bits.  The slot
permutation and the per-position dither come from SHAKE-256 over the sync key
and the layout, so they are reproducible on every platform.  The dither does
not change over time.

Bit ``b`` at a coefficient ``c`` with dither ``d`` (a fraction of the step)
moves ``c`` to the nearest point of ``step * (Z + d + b / 2)``.  AC basis
functions sum to zero over their block, so embedding leaves every
carrier-block mean, and hence the content fingerprint, unchanged up to
rounding.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from functools import cache

import numpy as np

_DOMAIN = b"zkstego/robust/watermark/v1/"
DEFAULT_BLOCK = 16
DEFAULT_COEFFICIENTS = (
    (0, 1), (1, 0), (1, 1), (0, 2), (2, 0), (1, 2), (2, 1), (2, 2), (0, 3), (3, 0),
)


@cache
def dct_matrix(size: int) -> np.ndarray:
    """Orthonormal DCT-II matrix of order ``size``."""
    matrix = np.zeros((size, size))
    for k in range(size):
        scale = math.sqrt(1 / size) if k == 0 else math.sqrt(2 / size)
        for n in range(size):
            matrix[k, n] = scale * math.cos(math.pi * (2 * n + 1) * k / (2 * size))
    return matrix


@dataclass(frozen=True)
class WatermarkLayout:
    """Everything that fixes where and how bits sit in a clip."""

    frames: int
    height: int
    width: int
    step: float
    coefficients: tuple[tuple[int, int], ...] = DEFAULT_COEFFICIENTS
    block: int = DEFAULT_BLOCK
    group: int = 3

    def __post_init__(self) -> None:
        if self.block not in (8, 16, 32):
            raise ValueError("carrier block size must be 8, 16 or 32")
        if self.frames < 1 or self.height < self.block or self.width < self.block:
            raise ValueError("layout needs at least one frame and one carrier block")
        if not self.step > 0:
            raise ValueError("QIM step must be positive")
        if not 1 <= self.group <= self.frames:
            raise ValueError("temporal group must be between 1 and the frame count")
        if not self.coefficients or len(set(self.coefficients)) != len(self.coefficients):
            raise ValueError("coefficients must be distinct")
        for u, v in self.coefficients:
            if not (0 <= u < self.block and 0 <= v < self.block) or (u, v) == (0, 0):
                raise ValueError("coefficients must be AC positions of a carrier block")

    @property
    def block_rows(self) -> int:
        return self.height // self.block

    @property
    def block_cols(self) -> int:
        return self.width // self.block

    @property
    def blocks_per_frame(self) -> int:
        return self.block_rows * self.block_cols

    @property
    def positions_per_frame(self) -> int:
        return self.blocks_per_frame * len(self.coefficients)

    @property
    def groups(self) -> int:
        return self.frames // self.group

    @property
    def capacity(self) -> int:
        """Number of slots, i.e. bits the clip carries once."""
        return self.groups * self.positions_per_frame

    def frame_group(self) -> np.ndarray:
        return np.minimum(np.arange(self.frames) // self.group, self.groups - 1)

    def descriptor(self) -> dict:
        return {
            "frames": self.frames, "height": self.height, "width": self.width,
            "step": self.step, "coefficients": [list(pair) for pair in self.coefficients],
            "block": self.block, "group": self.group,
        }

    def encoded(self) -> bytes:
        return json.dumps(self.descriptor(), sort_keys=True, separators=(",", ":")).encode("ascii")


def _stream(sync_key: bytes, label: bytes, context: bytes, length: int) -> bytes:
    if not isinstance(sync_key, bytes) or len(sync_key) != 32:
        raise ValueError("sync key must be exactly 32 bytes")
    material = _DOMAIN + label + b"\0" + sync_key + struct.pack(">I", len(context)) + context
    return hashlib.shake_256(material).digest(length)


def permutation(sync_key: bytes, layout: WatermarkLayout) -> np.ndarray:
    """``order[j]`` is the slot that carries stream entry ``j``."""
    raw = _stream(sync_key, b"order", layout.encoded(), 8 * layout.capacity)
    return np.argsort(np.frombuffer(raw, dtype="<u8"), kind="stable")


def dither(sync_key: bytes, layout: WatermarkLayout) -> np.ndarray:
    """Per-position dither in ``[0, 1)``; depends on the frame geometry only."""
    geometry = json.dumps(
        {key: value for key, value in layout.descriptor().items() if key not in ("frames", "group")},
        sort_keys=True, separators=(",", ":"),
    ).encode("ascii")
    raw = _stream(sync_key, b"dither", geometry, 4 * layout.positions_per_frame)
    return np.frombuffer(raw, dtype="<u4").astype(np.float64) / float(1 << 32)


def _blocks(plane: np.ndarray, layout: WatermarkLayout) -> np.ndarray:
    rows, cols, size = layout.block_rows, layout.block_cols, layout.block
    cropped = plane[: rows * size, : cols * size].astype(np.float64)
    return cropped.reshape(rows, size, cols, size).transpose(0, 2, 1, 3).reshape(-1, size, size)


def _bases(layout: WatermarkLayout) -> np.ndarray:
    dct = dct_matrix(layout.block)
    return np.stack([np.outer(dct[u], dct[v]) for u, v in layout.coefficients])


def _coefficients(blocks: np.ndarray, bases: np.ndarray) -> np.ndarray:
    """``(blocks, len(coefficients))`` DCT values at the carrier positions."""
    return np.einsum("bij,kij->bk", blocks, bases)


def _check_luma(luma: np.ndarray, layout: WatermarkLayout) -> None:
    if luma.shape != (layout.frames, layout.height, layout.width):
        raise ValueError("luma shape does not match the layout")


def embed(luma: np.ndarray, slot_bits: np.ndarray, sync_key: bytes, layout: WatermarkLayout) -> np.ndarray:
    """Return a new luma array carrying ``slot_bits`` (one 0/1 value per slot)."""
    _check_luma(luma, layout)
    slot_bits = np.asarray(slot_bits, dtype=np.float64)
    if slot_bits.shape != (layout.capacity,):
        raise ValueError("need exactly one bit per slot")
    per_frame, step, count = layout.positions_per_frame, layout.step, len(layout.coefficients)
    offsets = dither(sync_key, layout).reshape(-1, count)
    bases = _bases(layout)
    rows, cols, size = layout.block_rows, layout.block_cols, layout.block
    out = luma.copy()
    for frame, group in enumerate(layout.frame_group()):
        bits = slot_bits[group * per_frame:(group + 1) * per_frame].reshape(-1, count)
        shift = (offsets + bits / 2) * step
        blocks = _blocks(luma[frame], layout)
        values = _coefficients(blocks, bases)
        moved = step * np.round((values - shift) / step) + shift
        blocks = blocks + np.einsum("bk,kij->bij", moved - values, bases)
        pixels = blocks.reshape(rows, cols, size, size).transpose(0, 2, 1, 3).reshape(rows * size, cols * size)
        out[frame, : rows * size, : cols * size] = np.clip(np.round(pixels), 0, 255).astype(np.uint8)
    return out


def frame_soft_values(luma: np.ndarray, sync_key: bytes, layout: WatermarkLayout) -> np.ndarray:
    """``(frames, positions_per_frame)`` soft values in ``[-1, 1]`` (+1: confident 1)."""
    _check_luma(luma, layout)
    offsets = dither(sync_key, layout)
    bases = _bases(layout)
    out = np.empty((layout.frames, layout.positions_per_frame))
    for frame in range(layout.frames):
        values = _coefficients(_blocks(luma[frame], layout), bases).reshape(-1)
        fraction = np.mod(values / layout.step - offsets, 1.0)
        out[frame] = 4.0 * np.minimum(fraction, 1.0 - fraction) - 1.0
    return out


def slot_soft_values(frame_soft: np.ndarray, layout: WatermarkLayout) -> np.ndarray:
    """Average the frames of each temporal group: one soft value per slot."""
    groups = layout.frame_group()
    total = np.zeros((layout.groups, layout.positions_per_frame))
    np.add.at(total, groups, frame_soft)
    counts = np.bincount(groups, minlength=layout.groups)[:, None]
    return (total / counts).reshape(-1)


def frame_expected_bits(slot_bits: np.ndarray, layout: WatermarkLayout) -> np.ndarray:
    """``(frames, positions_per_frame)`` bits each frame should carry."""
    per_group = np.asarray(slot_bits).reshape(layout.groups, layout.positions_per_frame)
    return per_group[layout.frame_group()]


def spread(codeword: np.ndarray, order: np.ndarray) -> np.ndarray:
    """Repeat ``codeword`` over every slot in permuted order."""
    stream = np.resize(np.asarray(codeword, dtype=np.uint8), len(order))
    bits = np.empty(len(order), dtype=np.uint8)
    bits[order] = stream
    return bits


def gather(soft: np.ndarray, order: np.ndarray, coded_bits: int) -> np.ndarray:
    """Soft-combine every repetition of each coded bit (mean of its copies)."""
    entries = np.arange(len(order)) % coded_bits
    total = np.bincount(entries, weights=soft[order], minlength=coded_bits)
    count = np.bincount(entries, minlength=coded_bits)
    return total / np.maximum(count, 1)
