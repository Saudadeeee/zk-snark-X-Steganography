"""Bounded-latency orchestration for a streaming CAVLC patcher.

This module owns scheduling only. ``patch_segment`` must be a CAVLC-preserving
IDR-segment patcher; the existing full-video Python embedder is intentionally
not accepted as a real-time implementation.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time
from typing import Callable, Deque


@dataclass(frozen=True)
class CAVLCRealtimeBudget:
    fps: float = 30.0
    max_queue_segments: int = 2
    max_p95_latency_s: float | None = None

    def __post_init__(self) -> None:
        if self.fps <= 0 or self.max_queue_segments < 1:
            raise ValueError("fps and max_queue_segments must be positive")

    @property
    def frame_interval_s(self) -> float:
        return 1.0 / self.fps

    @property
    def latency_limit_s(self) -> float:
        return self.max_p95_latency_s if self.max_p95_latency_s is not None else self.frame_interval_s


@dataclass(frozen=True)
class CAVLCRealtimeResult:
    epoch: int
    input_bytes: int
    output: bytes
    latency_s: float


@dataclass(frozen=True)
class CAVLCRealtimeReport:
    processed_segments: int
    dropped_segments: int
    p95_latency_s: float
    latency_limit_s: float
    accepted: bool


def _p95(samples: list[float]) -> float:
    if not samples:
        return 0.0
    return sorted(samples)[max(0, (len(samples) * 95 + 99) // 100 - 1)]


class RealtimeCAVLCScheduler:
    """Keep camera ingestion independent from CAVLC segment patch duration."""

    def __init__(
        self,
        budget: CAVLCRealtimeBudget,
        proof_for_epoch: Callable[[int], bytes],
        patch_segment: Callable[[bytes, bytes], bytes],
    ) -> None:
        self.budget = budget
        self._proof_for_epoch = proof_for_epoch
        self._patch_segment = patch_segment
        self._queue: Deque[tuple[bytes, int]] = deque()
        self._proof_cache: dict[int, bytes] = {}
        self._latencies: list[float] = []
        self.dropped_segments = 0

    def submit(self, segment: bytes, *, epoch: int) -> None:
        if not segment:
            raise ValueError("CAVLC segment must not be empty")
        if len(self._queue) >= self.budget.max_queue_segments:
            self._queue.popleft()
            self.dropped_segments += 1
        self._queue.append((bytes(segment), int(epoch)))

    def process_next(self) -> CAVLCRealtimeResult | None:
        if not self._queue:
            return None
        segment, epoch = self._queue.popleft()
        proof = self._proof_cache.get(epoch)
        if proof is None:
            proof = bytes(self._proof_for_epoch(epoch))
            if not proof:
                raise ValueError("proof_for_epoch returned an empty proof")
            self._proof_cache[epoch] = proof
        started = time.perf_counter()
        output = bytes(self._patch_segment(segment, proof))
        latency = time.perf_counter() - started
        self._latencies.append(latency)
        return CAVLCRealtimeResult(epoch, len(segment), output, latency)

    def report(self) -> CAVLCRealtimeReport:
        p95 = _p95(self._latencies)
        return CAVLCRealtimeReport(
            processed_segments=len(self._latencies),
            dropped_segments=self.dropped_segments,
            p95_latency_s=p95,
            latency_limit_s=self.budget.latency_limit_s,
            accepted=bool(self._latencies) and self.dropped_segments == 0 and p95 <= self.budget.latency_limit_s,
        )
