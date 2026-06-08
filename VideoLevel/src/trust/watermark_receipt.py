"""Experimental watermark receipt helpers.

This models a tiny threshold detector whose public output is only a boolean
receipt plus audit metadata. It is deliberately separated from the fragile
CAVLC embedding path and does not claim real detector parity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

from .canonical import canonical_json_hash


@dataclass(frozen=True)
class DetectorReceipt:
    """Public output of a detector wrapped in a trust receipt."""

    detector_id: str
    score: float
    threshold: float
    valid: bool
    payload_commitment: str | None = None
    detector_commitment: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "detector_id": self.detector_id,
            "score": self.score,
            "threshold": self.threshold,
            "valid": self.valid,
            "payload_commitment": self.payload_commitment,
            "detector_commitment": self.detector_commitment,
        }

    def commitment(self) -> str:
        return canonical_json_hash(self.to_dict())


def extract_tiny_video_features(frames: Sequence[np.ndarray] | np.ndarray) -> list[float]:
    """Extract four normalized toy features from luma frames."""
    arr = np.asarray(frames, dtype=np.float32)
    if arr.ndim != 3:
        raise ValueError("extract_tiny_video_features expects T,H,W luma frames")
    if arr.shape[0] == 0:
        raise ValueError("at least one frame is required")
    mean_level = float(np.mean(arr) / 255.0)
    contrast = float(np.std(arr) / 128.0)
    grad_x = np.abs(np.diff(arr, axis=2)).mean() if arr.shape[2] > 1 else 0.0
    grad_y = np.abs(np.diff(arr, axis=1)).mean() if arr.shape[1] > 1 else 0.0
    texture = float((grad_x + grad_y) / 255.0)
    motion = float(np.abs(np.diff(arr, axis=0)).mean() / 255.0) if arr.shape[0] > 1 else 0.0
    return [mean_level, contrast, texture, motion]


class TinyThresholdDetector:
    """A minimal detector over numeric feature vectors.

    The detector computes a dot product with an internal weight vector and
    returns a boolean threshold decision. In a future branch this can be
    replaced by a learned detector or feature extractor.
    """

    def __init__(self, weights: Iterable[float], *, detector_id: str = "tiny-threshold-v1"):
        weights_arr = np.asarray(list(weights), dtype=np.float32)
        if weights_arr.size == 0:
            raise ValueError("weights must be non-empty")
        self._weights = weights_arr
        self.detector_id = detector_id

    @property
    def commitment(self) -> str:
        return canonical_json_hash(
            {
                "detector_id": self.detector_id,
                "weights": self._weights.round(6).tolist(),
                "shape": int(self._weights.size),
            }
        )

    def score(self, features: Iterable[float]) -> float:
        values = np.asarray(list(features), dtype=np.float32)
        if values.size != self._weights.size:
            raise ValueError("feature vector length must match detector weights")
        return float(np.dot(values, self._weights))

    def receipt(
        self,
        features: Iterable[float],
        *,
        threshold: float,
        payload_commitment: str | None = None,
    ) -> DetectorReceipt:
        score = self.score(features)
        return DetectorReceipt(
            detector_id=self.detector_id,
            score=score,
            threshold=threshold,
            valid=score >= threshold,
            payload_commitment=payload_commitment,
            detector_commitment=self.commitment,
        )
