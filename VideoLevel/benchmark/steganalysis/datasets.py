"""Per-stream feature / tile extraction with caching, assembled into paired frame tables."""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .cavlc_trace import load_trace
from .common import DEFAULT_CACHE_DIR, FeatureCache, Pair, decode_luma
from .features_cavlc import extract_cavlc_features
from .features_pixel import extract_pixel_features

FEATURE_DETECTORS = ("cavlc", "spam", "srmlite")
DETECTORS = FEATURE_DETECTORS + ("cnn",)
CACHE_VERSION = "v1"


@dataclass(frozen=True)
class FrameTable:
    """Row-aligned cover/stego data; row i of both comes from the same pair and frame."""

    cover: np.ndarray
    stego: np.ndarray
    pair_index: np.ndarray
    frame: np.ndarray

    def select(self, rows: np.ndarray) -> FrameTable:
        return FrameTable(self.cover[rows], self.stego[rows], self.pair_index[rows], self.frame[rows])

    @property
    def size(self) -> int:
        return int(self.pair_index.size)


@dataclass(frozen=True)
class StreamJob:
    stream: Path
    width: int
    height: int
    frames: tuple[int, ...]
    detector: str
    cache_root: Path
    tile: int = 256
    max_tiles: int = 8


def _compute(job: StreamJob) -> np.ndarray:
    if job.detector == "cavlc":
        return extract_cavlc_features(load_trace(job.stream), job.frames)
    planes = decode_luma(job.stream, job.width, job.height, job.frames)
    ordered = [planes[f] for f in job.frames]
    if job.detector == "cnn":
        from .cnn import cut_tiles  # torch is only needed for the CNN detector

        return np.stack([cut_tiles(plane, job.tile, job.max_tiles) for plane in ordered])
    return extract_pixel_features(ordered, job.detector)


def run_job(job: StreamJob) -> np.ndarray:
    """Features (n_frames, d) or tiles (n_frames, n_tiles, t, t) of one stream, cached on disk."""
    cache = FeatureCache(job.cache_root)
    if job.detector == "cnn":
        tag = f"tiles{job.tile}x{job.max_tiles}_{CACHE_VERSION}"
        return cache.get_or_compute(job.stream, tag, job.frames, lambda: _compute(job), np.uint8)
    if job.detector not in FEATURE_DETECTORS:
        raise ValueError(f"unknown detector {job.detector!r}; choose from {DETECTORS}")
    return cache.get_or_compute(job.stream, f"{job.detector}_{CACHE_VERSION}", job.frames, lambda: _compute(job))


def _jobs(pairs: Sequence[Pair], detector: str, cache_root: Path, tile: int, max_tiles: int) -> list[StreamJob]:
    jobs = []
    for pair in pairs:
        for stream in (pair.cover, pair.stego):
            if not stream.exists():
                raise FileNotFoundError(f"pair {pair.pair_id}: missing stream {stream}")
            jobs.append(StreamJob(stream, pair.width, pair.height, pair.frames, detector, cache_root,
                                  tile, max_tiles))
    return jobs


def build_table(pairs: Sequence[Pair], detector: str, cache_root: Path = DEFAULT_CACHE_DIR,
                workers: int = 1, tile: int = 256, max_tiles: int = 8) -> FrameTable:
    """Extract (or load) every stream of ``pairs`` and stack frame rows pair by pair."""
    jobs = _jobs(pairs, detector, cache_root, tile, max_tiles)
    if workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(run_job, jobs))
    else:
        results = [run_job(job) for job in jobs]
    covers, stegos, owners, frames = [], [], [], []
    for index, pair in enumerate(pairs):
        cover, stego = results[2 * index], results[2 * index + 1]
        if cover.shape != stego.shape:
            raise ValueError(f"pair {pair.pair_id}: cover {cover.shape} and stego {stego.shape} differ")
        covers.append(cover)
        stegos.append(stego)
        owners.append(np.full(len(pair.frames), index))
        frames.append(np.asarray(pair.frames))
    if not covers:
        raise ValueError("no pairs to extract")
    return FrameTable(np.concatenate(covers), np.concatenate(stegos), np.concatenate(owners),
                      np.concatenate(frames))
