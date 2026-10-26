"""Coarse content fingerprint for semi-fragile integrity.

Luma: per frame, the plane is tiled into ``block x block`` cells (edge cells
may be partial) and each cell's mean is quantized with ``step``.  Cell means
change little under re-compression at the same resolution, ignore the QIM
carriers (their AC basis functions sum to zero over every carrier block, and
a cell is a union of whole carrier blocks), and move when content in the
cell is replaced.

Chroma: on every ``chroma_every``-th frame (0, chroma_every, 2*chroma_every,
...) the U and V planes are tiled into ``chroma_block x chroma_block`` cells
of the half-resolution 4:2:0 planes (64 chroma samples = 128 luma pixels)
and quantized with ``chroma_step``.  The watermark never touches chroma, so
this binds colour coarsely: a recolouring that moves a sampled cell by at
least ``chroma_hard_delta`` steps is caught; one confined to unsampled
frames, or to a small fraction of a cell, is not (``docs/ROBUST_MODE.md``).
``chroma_every = 0`` disables the section (luma-only fingerprint).

Blob layout (big-endian), version 2::

    "ZKRF" || u8 version || u16 width || u16 height || u32 frames
    || u16 block || u8 step || u8 bits || u32 luma cells per frame
    || u16 chroma_block || u8 chroma_step || u8 chroma_every || u8 chroma_bits
    || u32 chroma cells per sampled frame (U and V) || u32 sampled frames
    || packed luma values, ``bits`` each, frame-major raster, byte padded
    || packed chroma values, ``chroma_bits`` each, sampled-frame-major,
       U plane then V plane, raster, byte padded
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

MAGIC = b"ZKRF"
VERSION = 2
_HEADER = struct.Struct(">4sBHHIHBBIHBBBII")
MAX_DIMENSION = 0xFFFF
PLANES = ("U", "V")


def _bits_for(step: int) -> int:
    return max(1, math.ceil(math.log2(255 // step + 1)))


def _packed_bytes(count: int, bits: int) -> int:
    return math.ceil(count * bits / 8)


def _grid(height: int, width: int, block: int) -> tuple[int, int]:
    return math.ceil(height / block), math.ceil(width / block)


@dataclass(frozen=True)
class FingerprintSpec:
    block: int = 64
    step: int = 4
    chroma_block: int = 64   # chroma-plane samples: 64 = 128x128 luma pixels at 4:2:0
    chroma_step: int = 8
    chroma_every: int = 6    # sample every 6th frame; 0 disables chroma binding

    def __post_init__(self) -> None:
        if self.block < 16 or self.block % 16:
            raise ValueError("fingerprint cells must be whole 16x16 carrier blocks")
        if not 1 <= self.step <= 64:
            raise ValueError("fingerprint step must be in 1..64")
        if not 8 <= self.chroma_block <= MAX_DIMENSION:
            raise ValueError("chroma cells must be at least 8x8 chroma samples")
        if not 1 <= self.chroma_step <= 64:
            raise ValueError("chroma step must be in 1..64")
        if not 0 <= self.chroma_every <= 255:
            raise ValueError("chroma_every must be in 0..255 (0 disables chroma)")

    @property
    def bits(self) -> int:
        return _bits_for(self.step)

    @property
    def chroma_bits(self) -> int:
        return _bits_for(self.chroma_step)

    @property
    def binds_chroma(self) -> bool:
        return self.chroma_every > 0

    def grid(self, height: int, width: int) -> tuple[int, int]:
        return _grid(height, width, self.block)

    def chroma_grid(self, height: int, width: int) -> tuple[int, int]:
        return _grid(height // 2, width // 2, self.chroma_block)

    def sampled_frames(self, frames: int) -> np.ndarray:
        if not self.binds_chroma:
            return np.zeros(0, dtype=np.int64)
        return np.arange(0, frames, self.chroma_every, dtype=np.int64)

    def chroma_frames(self, frames: int) -> int:
        return math.ceil(frames / self.chroma_every) if self.binds_chroma else 0

    def chroma_cells(self, height: int, width: int) -> int:
        """Chroma cells per sampled frame, both planes; 0 when chroma is off."""
        rows, cols = self.chroma_grid(height, width)
        return len(PLANES) * rows * cols if self.binds_chroma else 0

    def luma_bytes(self, frames: int, height: int, width: int) -> int:
        rows, cols = self.grid(height, width)
        return _packed_bytes(frames * rows * cols, self.bits)

    def chroma_bytes(self, frames: int, height: int, width: int) -> int:
        return _packed_bytes(self.chroma_frames(frames) * self.chroma_cells(height, width), self.chroma_bits)

    def blob_bytes(self, frames: int, height: int, width: int) -> int:
        return _HEADER.size + self.luma_bytes(frames, height, width) + self.chroma_bytes(frames, height, width)

    def descriptor(self) -> dict:
        return {
            "block": self.block, "step": self.step, "chroma_block": self.chroma_block,
            "chroma_step": self.chroma_step, "chroma_every": self.chroma_every,
        }


def _pack_values(values: np.ndarray, bits: int) -> bytes:
    flat = values.reshape(-1).astype(np.uint16)
    if flat.size == 0:
        return b""
    planes = ((flat[:, None] >> np.arange(bits - 1, -1, -1)) & 1).astype(np.uint8)
    return np.packbits(planes.reshape(-1)).tobytes()


def _unpack_values(data: bytes, count: int, bits: int, maximum: int) -> np.ndarray:
    if count == 0:
        return np.zeros(0, dtype=np.int64)
    raw = np.unpackbits(np.frombuffer(data, dtype=np.uint8))[: count * bits]
    weights = 1 << np.arange(bits - 1, -1, -1)
    values = (raw.reshape(count, bits).astype(np.int64) * weights).sum(axis=1)
    if (values > maximum).any():
        raise ValueError("fingerprint value out of range")
    return values


@dataclass(frozen=True)
class Fingerprint:
    width: int
    height: int
    spec: FingerprintSpec
    values: np.ndarray         # (frames, rows, cols) quantized luma cell means
    chroma_values: np.ndarray  # (sampled frames, 2, rows, cols); empty when chroma is off

    @property
    def frames(self) -> int:
        return int(self.values.shape[0])

    def to_bytes(self) -> bytes:
        spec = self.spec
        rows, cols = spec.grid(self.height, self.width)
        header = _HEADER.pack(
            MAGIC, VERSION, self.width, self.height, self.frames, spec.block, spec.step, spec.bits,
            rows * cols, spec.chroma_block, spec.chroma_step, spec.chroma_every, spec.chroma_bits,
            spec.chroma_cells(self.height, self.width), spec.chroma_frames(self.frames),
        )
        return header + _pack_values(self.values, spec.bits) + _pack_values(self.chroma_values, spec.chroma_bits)

    @classmethod
    def from_bytes(cls, data: bytes) -> Fingerprint:
        if len(data) < _HEADER.size:
            raise ValueError("fingerprint blob is truncated")
        (magic, version, width, height, frames, block, step, bits, cells, chroma_block, chroma_step,
         chroma_every, chroma_bits, chroma_cells, chroma_frames) = _HEADER.unpack_from(data)
        if magic != MAGIC or version != VERSION:
            raise ValueError("fingerprint magic or version is unsupported")
        spec = FingerprintSpec(block, step, chroma_block, chroma_step, chroma_every)
        rows, cols = spec.grid(height, width)
        declared = (bits, cells, chroma_bits, chroma_cells, chroma_frames)
        expected = (spec.bits, rows * cols, spec.chroma_bits, spec.chroma_cells(height, width),
                    spec.chroma_frames(frames))
        if declared != expected or frames < 1 or width < 1 or height < 1:
            raise ValueError("fingerprint header is inconsistent")
        if len(data) != spec.blob_bytes(frames, height, width):
            raise ValueError("fingerprint blob has the wrong length")
        luma_end = _HEADER.size + spec.luma_bytes(frames, height, width)
        values = _unpack_values(data[_HEADER.size:luma_end], frames * cells, bits, 255 // step)
        chroma = _unpack_values(data[luma_end:], chroma_frames * chroma_cells, chroma_bits, 255 // chroma_step)
        chroma_rows, chroma_cols = spec.chroma_grid(height, width)
        return cls(
            width, height, spec, values.reshape(frames, rows, cols),
            chroma.reshape(chroma_frames, len(PLANES), chroma_rows, chroma_cols),
        )


def cell_means(plane: np.ndarray, block: int) -> np.ndarray:
    """``(frames, rows, cols)`` float means of every (possibly partial) cell."""
    frames, height, width = plane.shape
    rows, cols = _grid(height, width, block)
    padded_h, padded_w = rows * block, cols * block
    data = np.zeros((frames, padded_h, padded_w), dtype=np.float64)
    weight = np.zeros((padded_h, padded_w), dtype=np.float64)
    data[:, :height, :width] = plane
    weight[:height, :width] = 1.0
    sums = data.reshape(frames, rows, block, cols, block).sum(axis=(2, 4))
    counts = weight.reshape(rows, block, cols, block).sum(axis=(1, 3))
    return sums / counts


def _quantize(means: np.ndarray, step: int) -> np.ndarray:
    return np.clip(np.round(means / step), 0, 255 // step).astype(np.int64)


def compute(
    luma: np.ndarray, spec: FingerprintSpec, u: np.ndarray | None = None, v: np.ndarray | None = None,
) -> Fingerprint:
    """Fingerprint of a clip; ``u`` and ``v`` are required when the spec binds chroma."""
    if luma.ndim != 3:
        raise ValueError("luma must be a (frames, height, width) array")
    frames, height, width = luma.shape
    if frames < 1 or not (1 <= width <= MAX_DIMENSION and 1 <= height <= MAX_DIMENSION):
        raise ValueError("clip geometry is outside what the fingerprint header can carry")
    values = _quantize(cell_means(luma, spec.block), spec.step)
    chroma_rows, chroma_cols = spec.chroma_grid(height, width)
    if not spec.binds_chroma:
        return Fingerprint(width, height, spec, values, np.zeros((0, len(PLANES), chroma_rows, chroma_cols), np.int64))
    if u is None or v is None:
        raise ValueError("this fingerprint specification binds chroma: pass the U and V planes")
    chroma_shape = (frames, height // 2, width // 2)
    if u.shape != chroma_shape or v.shape != chroma_shape:
        raise ValueError("chroma planes must be 4:2:0 companions of the luma")
    sampled = spec.sampled_frames(frames)
    chroma = np.stack(
        [_quantize(cell_means(plane[sampled], spec.chroma_block), spec.chroma_step) for plane in (u, v)], axis=1,
    )
    return Fingerprint(width, height, spec, values, chroma)


@dataclass(frozen=True)
class Tolerance:
    """Pinned decision rule, in quantization units of the fingerprint.

    Luma deltas are in ``step`` units (default 4 levels), chroma deltas in
    ``chroma_step`` units (default 8 levels).  Chroma defaults come from
    short-clip calibration recorded in ``docs/ROBUST_MODE.md``: clean x264
    CRF 23 re-encodes move no chroma cell by more than one step, while a
    16-level recolouring of a sampled cell moves it two.
    """

    hard_delta: int = 3          # any luma cell this far off rejects
    drift_delta: int = 2         # luma cells this far off count as drifting
    max_drift_fraction: float = 0.002
    chroma_hard_delta: int = 2   # any sampled chroma cell this far off rejects
    chroma_drift_delta: int = 1  # chroma cells this far off count as drifting
    chroma_max_drift_fraction: float = 0.25

    def __post_init__(self) -> None:
        if not 1 <= self.drift_delta <= self.hard_delta:
            raise ValueError("need 1 <= drift_delta <= hard_delta")
        if not 0 <= self.max_drift_fraction < 1:
            raise ValueError("max_drift_fraction must be in [0, 1)")
        if not 1 <= self.chroma_drift_delta <= self.chroma_hard_delta:
            raise ValueError("need 1 <= chroma_drift_delta <= chroma_hard_delta")
        if not 0 <= self.chroma_max_drift_fraction < 1:
            raise ValueError("chroma_max_drift_fraction must be in [0, 1)")

    def descriptor(self) -> dict:
        return {
            "hard_delta": self.hard_delta, "drift_delta": self.drift_delta,
            "max_drift_fraction": self.max_drift_fraction,
            "chroma_hard_delta": self.chroma_hard_delta, "chroma_drift_delta": self.chroma_drift_delta,
            "chroma_max_drift_fraction": self.chroma_max_drift_fraction,
        }


class _Deltas(NamedTuple):
    max_delta: int
    fraction: float
    flagged: tuple[tuple[int, ...], ...]


def _deltas(carried: np.ndarray, received: np.ndarray, drift_delta: int, frame_index: np.ndarray | None) -> _Deltas:
    if carried.size == 0:
        return _Deltas(0, 0.0, ())
    delta = np.abs(carried - received)
    flagged_index = np.argwhere(delta >= drift_delta)
    flagged = []
    for index in flagged_index:
        cell = tuple(int(axis) for axis in index)
        frame = cell[0] if frame_index is None else int(frame_index[cell[0]])
        flagged.append((frame, *cell[1:], int(delta[tuple(index)])))
    return _Deltas(int(delta.max()), float(len(flagged_index) / delta.size), tuple(flagged))


@dataclass(frozen=True)
class Comparison:
    accepted: bool
    reason: str
    max_delta: int
    drift_fraction: float
    # (frame, row, col, delta) for every luma cell at or above drift_delta
    flagged: tuple[tuple[int, int, int, int], ...]
    max_chroma_delta: int = 0
    chroma_drift_fraction: float = 0.0
    # (frame, plane, row, col, delta) for every sampled chroma cell at or
    # above chroma_drift_delta; plane 0 is U, 1 is V
    flagged_chroma: tuple[tuple[int, int, int, int, int], ...] = ()


def compare(carried: Fingerprint, received: Fingerprint, tolerance: Tolerance) -> Comparison:
    if (carried.width, carried.height, carried.frames) != (received.width, received.height, received.frames):
        return Comparison(
            False,
            f"geometry differs: carried {carried.width}x{carried.height}x{carried.frames}, "
            f"received {received.width}x{received.height}x{received.frames}",
            -1, 1.0, (), -1, 1.0, (),
        )
    if carried.spec != received.spec:
        return Comparison(False, "fingerprint specification differs from the pinned one", -1, 1.0, (), -1, 1.0, ())
    luma = _deltas(carried.values, received.values, tolerance.drift_delta, None)
    chroma = _deltas(
        carried.chroma_values, received.chroma_values, tolerance.chroma_drift_delta,
        carried.spec.sampled_frames(carried.frames),
    )
    reason = "ok"
    if luma.max_delta >= tolerance.hard_delta:
        reason = f"content changed: a luma cell moved {luma.max_delta} steps"
    elif chroma.max_delta >= tolerance.chroma_hard_delta:
        reason = f"colour changed: a chroma cell moved {chroma.max_delta} steps"
    elif luma.fraction > tolerance.max_drift_fraction:
        reason = f"content drift: {luma.fraction:.4f} of luma cells moved"
    elif chroma.fraction > tolerance.chroma_max_drift_fraction:
        reason = f"colour drift: {chroma.fraction:.4f} of chroma cells moved"
    return Comparison(
        reason == "ok", reason, luma.max_delta, luma.fraction, luma.flagged,
        chroma.max_delta, chroma.fraction, chroma.flagged,
    )
