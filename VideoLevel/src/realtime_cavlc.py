"""Bounded-latency orchestration for a streaming CAVLC patcher.

This module owns scheduling only. ``patch_segment`` must be a CAVLC-preserving
IDR-segment patcher (in production, the native C++ core behind the
zkstego_blind_bits CLI).
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class CAVLCRealtimeBudget:
    fps: float = 30.0
    max_queue_segments: int = 2
    max_p95_latency_s: float | None = None
    max_segment_bytes: int = 16 * 1024 * 1024
    max_queued_bytes: int = 32 * 1024 * 1024
    max_cached_epochs: int = 4
    max_latency_samples: int = 4096

    def __post_init__(self) -> None:
        if (
            isinstance(self.fps, bool)
            or not isinstance(self.fps, (int, float))
            or not math.isfinite(self.fps)
            or self.fps <= 0
        ):
            raise ValueError("fps must be finite and positive and max_queue_segments must be positive")
        if type(self.max_queue_segments) is not int or self.max_queue_segments < 1:
            raise ValueError("fps must be finite and positive and max_queue_segments must be positive")
        if self.max_p95_latency_s is not None and (
            isinstance(self.max_p95_latency_s, bool)
            or not isinstance(self.max_p95_latency_s, (int, float))
            or not math.isfinite(self.max_p95_latency_s)
            or self.max_p95_latency_s <= 0
        ):
            raise ValueError("max_p95_latency_s must be finite and positive")
        bounds = (self.max_segment_bytes, self.max_queued_bytes, self.max_cached_epochs, self.max_latency_samples)
        if any(type(bound) is not int or bound < 1 for bound in bounds):
            raise ValueError("realtime memory and sample bounds must be positive")

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
    latency_s: float  # Patch-only duration; kept for compatibility with earlier reports.
    proof_s: float = 0.0  # Proof generation time; 0.0 when the epoch proof was already cached.
    end_to_end_latency_s: float = 0.0  # submit() -> patched segment returned.


@dataclass(frozen=True)
class CAVLCRealtimeReport:
    processed_segments: int
    dropped_segments: int
    p95_latency_s: float
    latency_limit_s: float
    accepted: bool
    failed_segments: int = 0
    end_to_end_p95_latency_s: float = 0.0
    proof_p95_s: float = 0.0


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
        self._queue: deque[tuple[bytes, int, float]] = deque()
        self._queued_bytes = 0
        self._proof_cache: OrderedDict[int, bytes] = OrderedDict()
        self._latencies: deque[float] = deque(maxlen=budget.max_latency_samples)
        self._end_to_end_latencies: deque[float] = deque(maxlen=budget.max_latency_samples)
        self._proof_latencies: deque[float] = deque(maxlen=budget.max_latency_samples)
        self._processed_segments = 0
        self.dropped_segments = 0
        self.failed_segments = 0
        self._lock = threading.Lock()
        self._proof_lock = threading.Lock()
        self._last_submitted_epoch: int | None = None

    @property
    def queued_bytes(self) -> int:
        with self._lock:
            return self._queued_bytes

    def submit(self, segment: bytes, *, epoch: int) -> None:
        if not isinstance(segment, bytes):
            raise TypeError("CAVLC segment must be immutable bytes")
        if not segment:
            raise ValueError("CAVLC segment must not be empty")
        if len(segment) > self.budget.max_segment_bytes or len(segment) > self.budget.max_queued_bytes:
            raise ValueError("CAVLC segment exceeds configured maximum byte size")
        if type(epoch) is not int or epoch < 0:
            raise ValueError("CAVLC proof epoch must be a non-negative integer")
        segment_bytes = bytes(segment)
        if len(segment_bytes) > self.budget.max_segment_bytes or len(segment_bytes) > self.budget.max_queued_bytes:
            raise ValueError("CAVLC segment exceeds configured maximum byte size")
        with self._lock:
            if self._last_submitted_epoch is not None and epoch < self._last_submitted_epoch:
                raise ValueError("CAVLC proof epochs must be monotonic")
            while self._queue and (
                len(self._queue) >= self.budget.max_queue_segments
                or self._queued_bytes + len(segment_bytes) > self.budget.max_queued_bytes
            ):
                dropped, _, _ = self._queue.popleft()
                self._queued_bytes -= len(dropped)
                self.dropped_segments += 1
            self._queue.append((segment_bytes, epoch, time.perf_counter()))
            self._queued_bytes += len(segment_bytes)
            self._last_submitted_epoch = epoch

    def process_next(self) -> CAVLCRealtimeResult | None:
        with self._lock:
            if not self._queue:
                return None
            segment, epoch, enqueued_at = self._queue.popleft()
            self._queued_bytes -= len(segment)
        # The segment has left the queue; any failure below must be counted so
        # report() can never accept a run that silently lost segments.
        try:
            proof, proof_s = self._proof_for(epoch)
            started = time.perf_counter()
            output = bytes(self._patch_segment(segment, proof))
            finished = time.perf_counter()
        except BaseException:
            with self._lock:
                self.failed_segments += 1
            raise
        latency = finished - started
        end_to_end = finished - enqueued_at
        with self._lock:
            self._latencies.append(latency)
            self._end_to_end_latencies.append(end_to_end)
            if proof_s > 0.0:
                self._proof_latencies.append(proof_s)
            self._processed_segments += 1
        return CAVLCRealtimeResult(epoch, len(segment), output, latency, proof_s, end_to_end)

    def _proof_for(self, epoch: int) -> tuple[bytes, float]:
        """Return the cached epoch proof, generating it once; also return generation time."""
        with self._proof_lock:
            proof = self._proof_cache.get(epoch)
            if proof is not None:
                self._proof_cache.move_to_end(epoch)
                return proof, 0.0
            started = time.perf_counter()
            proof = bytes(self._proof_for_epoch(epoch))
            proof_s = time.perf_counter() - started
            if not proof:
                raise ValueError("proof_for_epoch returned an empty proof")
            self._proof_cache[epoch] = proof
            self._proof_cache.move_to_end(epoch)
            while len(self._proof_cache) > self.budget.max_cached_epochs:
                self._proof_cache.popitem(last=False)
            return proof, max(proof_s, 1e-9)

    def report(self) -> CAVLCRealtimeReport:
        with self._lock:
            latencies = list(self._latencies)
            end_to_end_latencies = list(self._end_to_end_latencies)
            proof_latencies = list(self._proof_latencies)
            processed_segments = self._processed_segments
            dropped_segments = self.dropped_segments
            failed_segments = self.failed_segments
        p95 = _p95(latencies)
        return CAVLCRealtimeReport(
            processed_segments=processed_segments,
            dropped_segments=dropped_segments,
            p95_latency_s=p95,
            latency_limit_s=self.budget.latency_limit_s,
            accepted=(
                bool(latencies)
                and dropped_segments == 0
                and failed_segments == 0
                and p95 <= self.budget.latency_limit_s
            ),
            failed_segments=failed_segments,
            end_to_end_p95_latency_s=_p95(end_to_end_latencies),
            proof_p95_s=_p95(proof_latencies),
        )
