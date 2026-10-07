"""Shared helpers: manifest model, FFmpeg luma decoding and the on-disk feature cache."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
NATIVE_BIN = REPO_ROOT / "native" / "build" / "Release"
INSPECT_EXE = NATIVE_BIN / "zkstego_inspect.exe"
BLIND_BITS_EXE = NATIVE_BIN / "zkstego_blind_bits.exe"
DEFAULT_CACHE_DIR = REPO_ROOT / "benchmark" / "results" / "steganalysis_cache"
SPLITS = ("train", "val", "test")


@dataclass(frozen=True)
class Pair:
    """One cover/stego pair of the manifest (cover label 0, stego label 1)."""

    pair_id: str
    source: str
    split: str
    method: str
    rate: str
    cover: Path
    stego: Path
    width: int
    height: int
    frames: tuple[int, ...]

    @property
    def group(self) -> tuple[str, str]:
        return (self.method, self.rate)


def _resolve(path: str, base: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


def parse_pairs(entries: Sequence[dict], base: Path) -> list[Pair]:
    """Validate raw manifest entries; relative paths resolve against ``base``."""
    pairs: list[Pair] = []
    split_of_source: dict[str, str] = {}
    seen_ids: set[str] = set()
    for entry in entries:
        missing = {"pair_id", "source", "split", "method", "rate", "cover", "stego",
                   "width", "height", "frames"} - set(entry)
        if missing:
            raise ValueError(f"manifest entry lacks {sorted(missing)}: {entry}")
        if entry["split"] not in SPLITS:
            raise ValueError(f"pair {entry['pair_id']}: split must be one of {SPLITS}")
        pair_id = str(entry["pair_id"])
        if pair_id in seen_ids:
            raise ValueError(f"duplicate pair_id {pair_id}")
        seen_ids.add(pair_id)
        source = str(entry["source"])
        previous = split_of_source.setdefault(source, entry["split"])
        if previous != entry["split"]:
            raise ValueError(f"source {source} appears in splits {previous} and {entry['split']}")
        frames = tuple(sorted({int(f) for f in entry["frames"]}))
        if not frames or frames[0] < 0:
            raise ValueError(f"pair {pair_id}: frames must be a non-empty list of indices >= 0")
        width, height = int(entry["width"]), int(entry["height"])
        if width <= 0 or height <= 0 or width % 2 or height % 2:
            raise ValueError(f"pair {pair_id}: invalid frame size {width}x{height}")
        pairs.append(Pair(pair_id, source, entry["split"], str(entry["method"]), str(entry["rate"]),
                          _resolve(entry["cover"], base), _resolve(entry["stego"], base),
                          width, height, frames))
    return pairs


def load_manifest(path: Path) -> list[Pair]:
    with open(path, "r", encoding="utf-8") as handle:
        entries = json.load(handle)
    if not isinstance(entries, list):
        raise TypeError("manifest must be a JSON list of pair objects")
    return parse_pairs(entries, path.resolve().parent)


def decode_luma(path: Path, width: int, height: int, frames: Iterable[int]) -> dict[int, np.ndarray]:
    """Decode ``path`` with FFmpeg and return {frame_index: uint8 luma plane (H, W)}."""
    wanted = set(frames)
    if not wanted:
        return {}
    last = max(wanted)
    luma_size = width * height
    frame_size = luma_size * 3 // 2
    command = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-frames:v", str(last + 1),
               "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"]
    planes: dict[int, np.ndarray] = {}
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        assert process.stdout is not None
        for index in range(last + 1):
            buffer = process.stdout.read(frame_size)
            if len(buffer) < frame_size:
                break
            if index in wanted:
                planes[index] = np.frombuffer(buffer, np.uint8, luma_size).reshape(height, width).copy()
        process.stdout.close()
        stderr = process.stderr.read().decode("utf-8", "replace") if process.stderr else ""
        process.wait()
    missing = wanted - set(planes)
    if missing:
        raise RuntimeError(f"{path}: FFmpeg did not deliver frames {sorted(missing)[:5]} ({stderr.strip()[:300]})")
    return planes


_DIGESTS: dict[tuple[str, int, int], str] = {}


def file_digest(path: Path) -> str:
    """SHA-256 of the file content (memoised on path, size and mtime)."""
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key not in _DIGESTS:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        _DIGESTS[key] = digest.hexdigest()
    return _DIGESTS[key]


class FeatureCache:
    """Per-stream feature cache: one ``.npy`` per (stream content, feature set, frame list)."""

    def __init__(self, root: Path = DEFAULT_CACHE_DIR) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        ignore = root / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n", encoding="utf-8")

    def _path(self, stream: Path, tag: str, frames: Sequence[int]) -> Path:
        frame_key = hashlib.sha1(",".join(map(str, frames)).encode()).hexdigest()[:12]
        return self.root / tag / f"{file_digest(stream)[:32]}_{frame_key}.npy"

    def get_or_compute(self, stream: Path, tag: str, frames: Sequence[int],
                       compute: Callable[[], np.ndarray], dtype: type = np.float32) -> np.ndarray:
        target = self._path(stream, tag, frames)
        if target.exists():
            return np.load(target)
        features = np.asarray(compute(), dtype=dtype)
        if features.shape[0] != len(frames):
            raise ValueError(f"{tag}: expected {len(frames)} rows, got {features.shape[0]}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp.npy")
        np.save(temporary, features)
        temporary.replace(target)
        return features
