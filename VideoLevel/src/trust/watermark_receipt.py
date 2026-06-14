"""Experimental watermark receipt helpers.

This models a tiny threshold detector whose public output is only a boolean
receipt plus audit metadata. It is deliberately separated from the fragile
CAVLC embedding path and does not claim real detector parity.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from .canonical import canonical_json_hash


DETECTOR_RECEIPT_SCHEMA = "zk-stego-detector-receipt-v2"
WATERMARK_POLICY_SCHEMA = "zk-stego-watermark-policy-v1"
WATERMARK_VERIFICATION_SCHEMA = "zk-stego-watermark-verification-v1"


@dataclass(frozen=True)
class DetectorCalibration:
    """Threshold calibration summary for a small detector candidate."""

    detector_id: str
    threshold: float
    positive_count: int
    negative_count: int
    true_accept_rate: float
    false_accept_rate: float
    accuracy: float

    def to_dict(self) -> dict[str, object]:
        return {
            "detector_id": self.detector_id,
            "threshold": self.threshold,
            "positive_count": self.positive_count,
            "negative_count": self.negative_count,
            "true_accept_rate": self.true_accept_rate,
            "false_accept_rate": self.false_accept_rate,
            "accuracy": self.accuracy,
        }


@dataclass(frozen=True)
class DetectorAlignmentScore:
    """Best score found by a small detector alignment search."""

    score: float
    alignment: str
    candidate_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "alignment": self.alignment,
            "candidate_count": self.candidate_count,
        }


@dataclass(frozen=True)
class WatermarkReceiptPolicy:
    """Verification policy for controlled watermark receipt workflows."""

    detector_family: str = "keyed-template"
    scoring_mode: str = "resynchronized"
    threshold_source: str = "calibrated"
    claim_scope: str = "controlled_keyed_template_receipt"
    crop_margins: tuple[int, ...] = (0, 4, 8, 12)

    def validate(self) -> None:
        if self.detector_family != "keyed-template":
            raise ValueError("only keyed-template detector family is supported")
        if self.scoring_mode not in {"fixed", "resynchronized"}:
            raise ValueError("scoring_mode must be fixed or resynchronized")
        if self.threshold_source not in {"calibrated", "provided"}:
            raise ValueError("threshold_source must be calibrated or provided")
        if self.claim_scope != "controlled_keyed_template_receipt":
            raise ValueError("only controlled_keyed_template_receipt scope is supported")
        if not self.crop_margins:
            raise ValueError("crop_margins must be non-empty")
        for margin in self.crop_margins:
            if int(margin) < 0:
                raise ValueError("crop_margins must be non-negative")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "schema": WATERMARK_POLICY_SCHEMA,
            "detector_family": self.detector_family,
            "scoring_mode": self.scoring_mode,
            "threshold_source": self.threshold_source,
            "claim_scope": self.claim_scope,
            "crop_margins": [int(value) for value in self.crop_margins],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "WatermarkReceiptPolicy":
        policy = cls(
            detector_family=str(data.get("detector_family", "keyed-template")),
            scoring_mode=str(data.get("scoring_mode", "resynchronized")),
            threshold_source=str(data.get("threshold_source", "calibrated")),
            claim_scope=str(data.get("claim_scope", "controlled_keyed_template_receipt")),
            crop_margins=tuple(int(value) for value in data.get("crop_margins", (0, 4, 8, 12))),
        )
        policy.validate()
        return policy

    def commitment(self) -> str:
        return canonical_json_hash(self.to_dict())


@dataclass(frozen=True)
class DetectorReceipt:
    """Public output of a detector wrapped in a trust receipt."""

    detector_id: str
    score: float
    threshold: float
    valid: bool
    payload_commitment: str | None = None
    detector_commitment: str | None = None
    policy_commitment: str | None = None
    alignment: DetectorAlignmentScore | None = None
    receipt_schema: str = DETECTOR_RECEIPT_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.receipt_schema,
            "detector_id": self.detector_id,
            "score": self.score,
            "threshold": self.threshold,
            "valid": self.valid,
            "payload_commitment": self.payload_commitment,
            "detector_commitment": self.detector_commitment,
            "policy_commitment": self.policy_commitment,
            "alignment": self.alignment.to_dict() if self.alignment else None,
            "receipt_commitment": self.commitment(include_self=False),
        }

    def commitment(self, *, include_self: bool = True) -> str:
        data = {
            "schema": self.receipt_schema,
            "detector_id": self.detector_id,
            "score": round(float(self.score), 12),
            "threshold": round(float(self.threshold), 12),
            "valid": bool(self.valid),
            "payload_commitment": self.payload_commitment,
            "detector_commitment": self.detector_commitment,
            "policy_commitment": self.policy_commitment,
            "alignment": self.alignment.to_dict() if self.alignment else None,
        }
        if include_self:
            data["receipt_commitment"] = canonical_json_hash(data)
        return canonical_json_hash(data)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "DetectorReceipt":
        alignment_data = data.get("alignment")
        alignment = None
        if isinstance(alignment_data, dict):
            alignment = DetectorAlignmentScore(
                score=float(alignment_data["score"]),
                alignment=str(alignment_data["alignment"]),
                candidate_count=int(alignment_data["candidate_count"]),
            )
        return cls(
            detector_id=str(data["detector_id"]),
            score=float(data["score"]),
            threshold=float(data["threshold"]),
            valid=bool(data["valid"]),
            payload_commitment=data.get("payload_commitment")
            if data.get("payload_commitment") is None
            else str(data["payload_commitment"]),
            detector_commitment=data.get("detector_commitment")
            if data.get("detector_commitment") is None
            else str(data["detector_commitment"]),
            policy_commitment=data.get("policy_commitment")
            if data.get("policy_commitment") is None
            else str(data["policy_commitment"]),
            alignment=alignment,
            receipt_schema=str(data.get("schema", DETECTOR_RECEIPT_SCHEMA)),
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=True), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "DetectorReceipt":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("detector receipt must be a JSON object")
        return cls.from_dict(data)


@dataclass(frozen=True)
class WatermarkVerificationReport:
    """Result of replaying a watermark receipt against frames and policy."""

    verified: bool
    expected_commitment: str
    observed_commitment: str
    receipt: DetectorReceipt
    policy: WatermarkReceiptPolicy
    schema: str = WATERMARK_VERIFICATION_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "verified": self.verified,
            "expected_commitment": self.expected_commitment,
            "observed_commitment": self.observed_commitment,
            "receipt": self.receipt.to_dict(),
            "policy": self.policy.to_dict(),
        }


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
        policy_commitment: str | None = None,
    ) -> DetectorReceipt:
        score = self.score(features)
        return DetectorReceipt(
            detector_id=self.detector_id,
            score=score,
            threshold=threshold,
            valid=score >= threshold,
            payload_commitment=payload_commitment,
            detector_commitment=self.commitment,
            policy_commitment=policy_commitment,
        )


class CalibratedThresholdDetector(TinyThresholdDetector):
    """Tiny detector with deterministic threshold calibration."""

    def __init__(self, weights: Iterable[float], *, detector_id: str = "calibrated-threshold-v1"):
        super().__init__(weights, detector_id=detector_id)

    def calibrate(
        self,
        positive_features: Sequence[Iterable[float]],
        negative_features: Sequence[Iterable[float]],
    ) -> DetectorCalibration:
        positive_scores = [self.score(features) for features in positive_features]
        negative_scores = [self.score(features) for features in negative_features]
        if not positive_scores:
            raise ValueError("positive_features must be non-empty")
        if not negative_scores:
            raise ValueError("negative_features must be non-empty")
        candidates = sorted(set(positive_scores + negative_scores))
        if len(candidates) == 1:
            thresholds = candidates
        else:
            thresholds = [candidates[0] - 1e-9]
            thresholds.extend((a + b) / 2.0 for a, b in zip(candidates, candidates[1:]))
            thresholds.append(candidates[-1] + 1e-9)

        best: DetectorCalibration | None = None
        for threshold in thresholds:
            true_accept = sum(score >= threshold for score in positive_scores)
            false_accept = sum(score >= threshold for score in negative_scores)
            true_accept_rate = true_accept / len(positive_scores)
            false_accept_rate = false_accept / len(negative_scores)
            accuracy = (true_accept + (len(negative_scores) - false_accept)) / (
                len(positive_scores) + len(negative_scores)
            )
            candidate = DetectorCalibration(
                detector_id=self.detector_id,
                threshold=float(threshold),
                positive_count=len(positive_scores),
                negative_count=len(negative_scores),
                true_accept_rate=float(true_accept_rate),
                false_accept_rate=float(false_accept_rate),
                accuracy=float(accuracy),
            )
            if best is None or (candidate.accuracy, candidate.true_accept_rate, -candidate.false_accept_rate) > (
                best.accuracy,
                best.true_accept_rate,
                -best.false_accept_rate,
            ):
                best = candidate
        if best is None:
            raise RuntimeError("calibration failed")
        return best


class KeyedTemplateDetector:
    """Hand-designed robust-video detector candidate.

    The detector uses a private keyed low-frequency template. Detection is a
    normalized spatial correlation, so global brightness and contrast changes
    have less impact than they do on raw pixel thresholds.
    """

    def __init__(
        self,
        key: bytes | str,
        *,
        frame_shape: tuple[int, int],
        grid_size: int = 8,
        detector_id: str = "keyed-template-v1",
    ):
        if isinstance(key, str):
            key = key.encode("utf-8")
        if not key:
            raise ValueError("key must be non-empty")
        if len(frame_shape) != 2 or frame_shape[0] <= 0 or frame_shape[1] <= 0:
            raise ValueError("frame_shape must be a positive H,W tuple")
        if grid_size <= 1:
            raise ValueError("grid_size must be greater than one")
        if frame_shape[0] < grid_size or frame_shape[1] < grid_size:
            raise ValueError("grid_size must fit inside frame_shape")

        self._key = bytes(key)
        self.frame_shape = (int(frame_shape[0]), int(frame_shape[1]))
        self.grid_size = int(grid_size)
        self.detector_id = detector_id
        self._template = self._normalize_template(self._build_template())

    @property
    def key_commitment(self) -> str:
        return hashlib.sha256(self._key).hexdigest()

    @property
    def template_digest(self) -> str:
        return hashlib.sha256(np.round(self._template, 6).astype(np.float32).tobytes()).hexdigest()

    @property
    def commitment(self) -> str:
        return canonical_json_hash(self.public_config())

    def public_config(self) -> dict[str, object]:
        return {
            "detector_id": self.detector_id,
            "frame_shape": list(self.frame_shape),
            "grid_size": self.grid_size,
            "key_commitment": self.key_commitment,
            "template_digest": self.template_digest,
        }

    def _build_template(self) -> np.ndarray:
        seed = int.from_bytes(hashlib.sha256(self._key + b":template").digest()[:8], "big", signed=False)
        rng = np.random.default_rng(seed)
        coarse = rng.choice(np.array([-1.0, 1.0], dtype=np.float32), size=(self.grid_size, self.grid_size))
        y_edges = np.linspace(0, self.grid_size, self.frame_shape[0], endpoint=False, dtype=int)
        x_edges = np.linspace(0, self.grid_size, self.frame_shape[1], endpoint=False, dtype=int)
        return coarse[y_edges[:, None], x_edges[None, :]].astype(np.float32)

    def _normalize_template(self, template: np.ndarray) -> np.ndarray:
        template = np.asarray(template, dtype=np.float32)
        template -= float(template.mean())
        norm = float(np.sqrt(np.mean(template * template)))
        if norm <= 1e-12:
            raise RuntimeError("template normalization failed")
        return template / norm

    def _resize_nearest_template(self, template: np.ndarray, height: int, width: int) -> np.ndarray:
        y_idx = (np.arange(height) * template.shape[0] / height).astype(int)
        x_idx = (np.arange(width) * template.shape[1] / width).astype(int)
        return template[y_idx[:, None], x_idx[None, :]].astype(np.float32)

    def _center_crop_resize_template(self, margin: int) -> np.ndarray:
        h, w = self.frame_shape
        if margin <= 0:
            return self._template
        if margin * 2 >= min(h, w):
            raise ValueError("crop margin is too large")
        cropped = self._template[margin : h - margin, margin : w - margin]
        return self._normalize_template(self._resize_nearest_template(cropped, h, w))

    def embed(self, frames: Sequence[np.ndarray] | np.ndarray, *, strength: float = 8.0) -> np.ndarray:
        arr = self._coerce_frames(frames)
        watermarked = np.clip(arr + self._template[None, :, :] * float(strength), 0, 255)
        return watermarked.astype(np.float32)

    def score(self, frames: Sequence[np.ndarray] | np.ndarray) -> float:
        arr = self._coerce_frames(frames)
        return self._score_with_template(arr, self._template)

    def score_resynchronized(
        self,
        frames: Sequence[np.ndarray] | np.ndarray,
        *,
        crop_margins: Sequence[int] = (0, 4, 8),
    ) -> DetectorAlignmentScore:
        arr = self._coerce_frames(frames)
        best_score = float("-inf")
        best_alignment = ""
        candidate_count = 0
        for margin in sorted({int(value) for value in crop_margins}):
            template = self._center_crop_resize_template(margin)
            score = self._score_with_template(arr, template)
            candidate_count += 1
            if score > best_score:
                best_score = score
                best_alignment = f"center_crop_resize_margin_{margin}"
        return DetectorAlignmentScore(
            score=float(best_score),
            alignment=best_alignment,
            candidate_count=candidate_count,
        )

    def _score_with_template(self, arr: np.ndarray, template: np.ndarray) -> float:
        centered = arr - arr.mean(axis=(1, 2), keepdims=True)
        scale = arr.std(axis=(1, 2), keepdims=True) + 1e-6
        normalized = centered / scale
        per_frame = np.mean(normalized * template[None, :, :], axis=(1, 2))
        return float(np.mean(per_frame))

    def receipt(
        self,
        frames: Sequence[np.ndarray] | np.ndarray,
        *,
        threshold: float,
        payload_commitment: str | None = None,
        policy: WatermarkReceiptPolicy | None = None,
    ) -> DetectorReceipt:
        policy = policy or WatermarkReceiptPolicy(scoring_mode="fixed", threshold_source="provided")
        score = self.score(frames)
        return DetectorReceipt(
            detector_id=self.detector_id,
            score=score,
            threshold=threshold,
            valid=score >= threshold,
            payload_commitment=payload_commitment,
            detector_commitment=self.commitment,
            policy_commitment=policy.commitment(),
        )

    def receipt_resynchronized(
        self,
        frames: Sequence[np.ndarray] | np.ndarray,
        *,
        threshold: float,
        payload_commitment: str | None = None,
        crop_margins: Sequence[int] = (0, 4, 8),
        policy: WatermarkReceiptPolicy | None = None,
    ) -> DetectorReceipt:
        policy = policy or WatermarkReceiptPolicy(
            scoring_mode="resynchronized",
            threshold_source="provided",
            crop_margins=tuple(int(value) for value in crop_margins),
        )
        aligned = self.score_resynchronized(frames, crop_margins=crop_margins)
        return DetectorReceipt(
            detector_id=self.detector_id,
            score=aligned.score,
            threshold=threshold,
            valid=aligned.score >= threshold,
            payload_commitment=payload_commitment,
            detector_commitment=self.commitment,
            policy_commitment=policy.commitment(),
            alignment=aligned,
        )

    def verify_receipt(
        self,
        frames: Sequence[np.ndarray] | np.ndarray,
        receipt: DetectorReceipt,
        *,
        policy: WatermarkReceiptPolicy,
        payload_commitment: str | None = None,
        tolerance: float = 1e-9,
    ) -> WatermarkVerificationReport:
        if receipt.detector_commitment != self.commitment:
            observed = receipt
        elif receipt.policy_commitment != policy.commitment():
            observed = receipt
        elif payload_commitment is not None and receipt.payload_commitment != payload_commitment:
            observed = receipt
        elif policy.scoring_mode == "fixed":
            observed = self.receipt(
                frames,
                threshold=receipt.threshold,
                payload_commitment=receipt.payload_commitment,
                policy=policy,
            )
        else:
            observed = self.receipt_resynchronized(
                frames,
                threshold=receipt.threshold,
                payload_commitment=receipt.payload_commitment,
                crop_margins=policy.crop_margins,
                policy=policy,
            )
        same_score = abs(float(observed.score) - float(receipt.score)) <= tolerance
        same_valid = bool(observed.valid) == bool(receipt.valid)
        same_commitment = observed.commitment() == receipt.commitment()
        verified = (
            receipt.detector_commitment == self.commitment
            and receipt.policy_commitment == policy.commitment()
            and (payload_commitment is None or receipt.payload_commitment == payload_commitment)
            and same_score
            and same_valid
            and same_commitment
        )
        return WatermarkVerificationReport(
            verified=verified,
            expected_commitment=receipt.commitment(),
            observed_commitment=observed.commitment(),
            receipt=observed,
            policy=policy,
        )

    def calibrate(
        self,
        positive_clips: Sequence[Sequence[np.ndarray] | np.ndarray],
        negative_clips: Sequence[Sequence[np.ndarray] | np.ndarray],
    ) -> DetectorCalibration:
        positive_scores = [self.score(frames) for frames in positive_clips]
        negative_scores = [self.score(frames) for frames in negative_clips]
        if not positive_scores:
            raise ValueError("positive_clips must be non-empty")
        if not negative_scores:
            raise ValueError("negative_clips must be non-empty")
        candidates = sorted(set(positive_scores + negative_scores))
        if len(candidates) == 1:
            thresholds = candidates
        else:
            thresholds = [candidates[0] - 1e-9]
            thresholds.extend((a + b) / 2.0 for a, b in zip(candidates, candidates[1:]))
            thresholds.append(candidates[-1] + 1e-9)

        best: DetectorCalibration | None = None
        for threshold in thresholds:
            true_accept = sum(score >= threshold for score in positive_scores)
            false_accept = sum(score >= threshold for score in negative_scores)
            true_accept_rate = true_accept / len(positive_scores)
            false_accept_rate = false_accept / len(negative_scores)
            accuracy = (true_accept + (len(negative_scores) - false_accept)) / (
                len(positive_scores) + len(negative_scores)
            )
            candidate = DetectorCalibration(
                detector_id=self.detector_id,
                threshold=float(threshold),
                positive_count=len(positive_scores),
                negative_count=len(negative_scores),
                true_accept_rate=float(true_accept_rate),
                false_accept_rate=float(false_accept_rate),
                accuracy=float(accuracy),
            )
            if best is None or (candidate.accuracy, candidate.true_accept_rate, -candidate.false_accept_rate) > (
                best.accuracy,
                best.true_accept_rate,
                -best.false_accept_rate,
            ):
                best = candidate
        if best is None:
            raise RuntimeError("calibration failed")
        return best

    def calibrate_resynchronized(
        self,
        positive_clips: Sequence[Sequence[np.ndarray] | np.ndarray],
        negative_clips: Sequence[Sequence[np.ndarray] | np.ndarray],
        *,
        crop_margins: Sequence[int] = (0, 4, 8),
    ) -> DetectorCalibration:
        positive_scores = [self.score_resynchronized(frames, crop_margins=crop_margins).score for frames in positive_clips]
        negative_scores = [self.score_resynchronized(frames, crop_margins=crop_margins).score for frames in negative_clips]
        if not positive_scores:
            raise ValueError("positive_clips must be non-empty")
        if not negative_scores:
            raise ValueError("negative_clips must be non-empty")
        candidates = sorted(set(positive_scores + negative_scores))
        if len(candidates) == 1:
            thresholds = candidates
        else:
            thresholds = [candidates[0] - 1e-9]
            thresholds.extend((a + b) / 2.0 for a, b in zip(candidates, candidates[1:]))
            thresholds.append(candidates[-1] + 1e-9)

        best: DetectorCalibration | None = None
        for threshold in thresholds:
            true_accept = sum(score >= threshold for score in positive_scores)
            false_accept = sum(score >= threshold for score in negative_scores)
            true_accept_rate = true_accept / len(positive_scores)
            false_accept_rate = false_accept / len(negative_scores)
            accuracy = (true_accept + (len(negative_scores) - false_accept)) / (
                len(positive_scores) + len(negative_scores)
            )
            candidate = DetectorCalibration(
                detector_id=self.detector_id,
                threshold=float(threshold),
                positive_count=len(positive_scores),
                negative_count=len(negative_scores),
                true_accept_rate=float(true_accept_rate),
                false_accept_rate=float(false_accept_rate),
                accuracy=float(accuracy),
            )
            if best is None or (candidate.accuracy, candidate.true_accept_rate, -candidate.false_accept_rate) > (
                best.accuracy,
                best.true_accept_rate,
                -best.false_accept_rate,
            ):
                best = candidate
        if best is None:
            raise RuntimeError("calibration failed")
        return best

    def _coerce_frames(self, frames: Sequence[np.ndarray] | np.ndarray) -> np.ndarray:
        arr = np.asarray(frames, dtype=np.float32)
        if arr.ndim != 3:
            raise ValueError("frames must have shape T,H,W")
        if arr.shape[0] == 0:
            raise ValueError("at least one frame is required")
        if tuple(arr.shape[1:]) != self.frame_shape:
            raise ValueError("frame shape does not match detector frame_shape")
        return arr
