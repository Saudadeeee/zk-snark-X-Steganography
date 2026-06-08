"""Experimental fingerprint registry helpers.

The current implementation is a deterministic pHash-like prototype over luma
frames or numeric feature vectors. It is intentionally outside the current
paper-grade CAVLC embedding claim.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from .canonical import canonical_json_hash


@dataclass(frozen=True)
class FingerprintPreprocessPolicy:
    """Deterministic preprocessing contract for future video fingerprints."""

    sample_count: int = 4
    hash_size: int = 8
    color_mode: str = "bt601_luma"
    resize_mode: str = "block_mean"
    aggregate_mode: str = "majority_vote"

    def to_dict(self) -> dict[str, object]:
        return {
            "sample_count": self.sample_count,
            "hash_size": self.hash_size,
            "color_mode": self.color_mode,
            "resize_mode": self.resize_mode,
            "aggregate_mode": self.aggregate_mode,
        }


@dataclass(frozen=True)
class VideoFingerprint:
    """Fingerprint result with the exact sampling/preprocessing policy."""

    fingerprint_hex: str
    bit_count: int
    sample_indices: tuple[int, ...]
    frame_hashes: tuple[str, ...]
    policy: FingerprintPreprocessPolicy

    def to_dict(self) -> dict[str, object]:
        return {
            "fingerprint_hex": self.fingerprint_hex,
            "bit_count": self.bit_count,
            "sample_indices": list(self.sample_indices),
            "frame_hashes": list(self.frame_hashes),
            "policy": self.policy.to_dict(),
        }


def _bits_to_hex(bits: Sequence[int]) -> str:
    bit_string = "".join("1" if int(bit) else "0" for bit in bits)
    if not bit_string:
        return ""
    return f"{int(bit_string, 2):0{(len(bit_string) + 3) // 4}x}"


def _hex_to_bits(value: str, bit_count: int) -> list[int]:
    if bit_count <= 0:
        return []
    raw = bin(int(value or "0", 16))[2:].zfill(bit_count)
    return [1 if ch == "1" else 0 for ch in raw[-bit_count:]]


def sample_frame_indices(frame_count: int, sample_count: int) -> tuple[int, ...]:
    """Return deterministic evenly spaced frame indices."""
    if frame_count <= 0:
        raise ValueError("frame_count must be positive")
    if sample_count <= 0:
        raise ValueError("sample_count must be positive")
    if sample_count >= frame_count:
        return tuple(range(frame_count))
    indices = np.linspace(0, frame_count - 1, sample_count, dtype=int).tolist()
    return tuple(sorted(set(int(i) for i in indices)))


def to_luma_frame(frame: np.ndarray, *, color_mode: str = "bt601_luma") -> np.ndarray:
    """Convert a 2-D luma or 3-D RGB frame to a float32 luma frame."""
    arr = np.asarray(frame, dtype=np.float32)
    if arr.ndim == 2:
        return arr
    if arr.ndim == 3 and arr.shape[2] >= 3 and color_mode == "bt601_luma":
        return 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    raise ValueError("frame must be 2-D luma or 3-D RGB with bt601_luma mode")


def hamming_distance_hex(a: str, b: str, bit_count: int) -> int:
    """Return Hamming distance between two fixed-width hex fingerprints."""
    aa = _hex_to_bits(a, bit_count)
    bb = _hex_to_bits(b, bit_count)
    return sum(x != y for x, y in zip(aa, bb))


def compute_framehash(frame: np.ndarray, *, hash_size: int = 8, color_mode: str = "bt601_luma") -> str:
    """Compute a small deterministic perceptual hash over a luma frame.

    The frame is downsampled by block averaging to hash_size x hash_size and
    thresholded by its median.
    """
    arr = to_luma_frame(frame, color_mode=color_mode)
    h, w = arr.shape
    if h < hash_size or w < hash_size:
        raise ValueError("frame is smaller than requested hash size")
    y_edges = np.linspace(0, h, hash_size + 1, dtype=int)
    x_edges = np.linspace(0, w, hash_size + 1, dtype=int)
    pooled = np.empty((hash_size, hash_size), dtype=np.float32)
    for yi in range(hash_size):
        for xi in range(hash_size):
            block = arr[y_edges[yi]:y_edges[yi + 1], x_edges[xi]:x_edges[xi + 1]]
            pooled[yi, xi] = float(block.mean())
    median = float(np.median(pooled))
    return _bits_to_hex((pooled >= median).astype(np.uint8).ravel())


def compute_video_fingerprint(
    frames: Sequence[np.ndarray] | np.ndarray,
    *,
    policy: FingerprintPreprocessPolicy | None = None,
) -> VideoFingerprint:
    """Compute a deterministic video fingerprint from sampled luma frames."""
    policy = policy or FingerprintPreprocessPolicy()
    arr = np.asarray(frames)
    if arr.ndim not in (3, 4):
        raise ValueError("frames must have shape T,H,W or T,H,W,C")
    indices = sample_frame_indices(int(arr.shape[0]), policy.sample_count)
    frame_hashes = tuple(
        compute_framehash(arr[i], hash_size=policy.hash_size, color_mode=policy.color_mode) for i in indices
    )
    bit_count = policy.hash_size * policy.hash_size
    votes = np.zeros(bit_count, dtype=np.int32)
    for value in frame_hashes:
        votes += np.asarray(_hex_to_bits(value, bit_count), dtype=np.int32)
    threshold = len(frame_hashes) / 2.0
    fingerprint = _bits_to_hex((votes >= threshold).astype(np.uint8).tolist())
    return VideoFingerprint(
        fingerprint_hex=fingerprint,
        bit_count=bit_count,
        sample_indices=indices,
        frame_hashes=frame_hashes,
        policy=policy,
    )


def compute_featurehash(features: Iterable[float], *, bit_count: int = 64) -> str:
    """Compute a threshold hash for a fixed feature vector."""
    arr = np.asarray(list(features), dtype=np.float32)
    if arr.size == 0:
        raise ValueError("feature vector must be non-empty")
    if arr.size != bit_count:
        arr = np.interp(
            np.linspace(0, arr.size - 1, bit_count),
            np.arange(arr.size),
            arr,
        ).astype(np.float32)
    median = float(np.median(arr))
    return _bits_to_hex((arr >= median).astype(np.uint8).tolist())


@dataclass(frozen=True)
class FingerprintRecord:
    """Registry record for one media fingerprint."""

    record_id: str
    fingerprint_hex: str
    bit_count: int = 64
    metadata_hash: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "fingerprint_hex": self.fingerprint_hex,
            "bit_count": self.bit_count,
            "metadata_hash": self.metadata_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "FingerprintRecord":
        return cls(
            record_id=str(data["record_id"]),
            fingerprint_hex=str(data["fingerprint_hex"]),
            bit_count=int(data.get("bit_count", 64)),
            metadata_hash=data.get("metadata_hash") if data.get("metadata_hash") is None else str(data["metadata_hash"]),
        )

    def to_public_commitment(self) -> str:
        """Commit to a record without exposing raw metadata."""
        return canonical_json_hash(
            {
                "record_id": self.record_id,
                "fingerprint_hex": self.fingerprint_hex,
                "bit_count": self.bit_count,
                "metadata_hash": self.metadata_hash,
            }
        )


@dataclass(frozen=True)
class RegistryMatch:
    """Result of a private-registry style lookup."""

    matched: bool
    record_id: str | None
    distance: int | None
    threshold: int
    registry_commitment: str

    def to_dict(self) -> dict[str, object]:
        return {
            "matched": self.matched,
            "record_id": self.record_id,
            "distance": self.distance,
            "threshold": self.threshold,
            "registry_commitment": self.registry_commitment,
        }


class FingerprintRegistry:
    """Small deterministic registry with Hamming-threshold lookup."""

    def __init__(self, records: Iterable[FingerprintRecord] = ()):
        self._records = list(records)

    @property
    def records(self) -> tuple[FingerprintRecord, ...]:
        return tuple(self._records)

    def add(self, record: FingerprintRecord) -> None:
        self._records.append(record)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "zk-stego-fingerprint-registry-v1",
            "commitment": self.commitment(),
            "records": [record.to_dict() for record in self._records],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "FingerprintRegistry":
        raw_records = data.get("records", [])
        if not isinstance(raw_records, list):
            raise ValueError("fingerprint registry records must be a list")
        registry = cls(FingerprintRecord.from_dict(record) for record in raw_records)
        expected_commitment = data.get("commitment")
        if expected_commitment is not None and str(expected_commitment) != registry.commitment():
            raise ValueError("fingerprint registry commitment mismatch")
        return registry

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=True), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "FingerprintRegistry":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("fingerprint registry must be a JSON object")
        return cls.from_dict(data)

    def commitment(self) -> str:
        """Commit to the registry set without exposing an external DB."""
        return canonical_json_hash([record.to_public_commitment() for record in self._records])

    def lookup(self, fingerprint_hex: str, *, bit_count: int = 64, threshold: int = 8) -> RegistryMatch:
        """Return the nearest threshold match."""
        best_record: FingerprintRecord | None = None
        best_distance: int | None = None
        for record in self._records:
            if record.bit_count != bit_count:
                continue
            distance = hamming_distance_hex(fingerprint_hex, record.fingerprint_hex, bit_count)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_record = record
        matched = best_record is not None and best_distance is not None and best_distance <= threshold
        return RegistryMatch(
            matched=matched,
            record_id=best_record.record_id if matched else None,
            distance=best_distance,
            threshold=threshold,
            registry_commitment=self.commitment(),
        )
