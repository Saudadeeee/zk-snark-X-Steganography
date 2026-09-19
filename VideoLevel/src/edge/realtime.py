"""Bounded-latency primitives for an all-edge H.264 camera pipeline.

The module deliberately separates capture/transport latency from proof and
embedding work.  A camera thread never waits for proof generation: it emits
complete IDR-delimited Annex-B segments into a bounded queue and drops the
oldest unprocessed segment under pressure.  That makes overload observable
instead of silently increasing end-to-end latency.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import threading
import time
from typing import Callable, Deque, Iterator


@dataclass(frozen=True)
class EdgeRealtimeBudget:
    """Acceptance budget for a camera stream; values are measured, never assumed."""

    fps: float = 30.0
    max_segment_latency_s: float = 1.0
    max_queue_segments: int = 2

    def __post_init__(self) -> None:
        if self.fps <= 0 or self.max_segment_latency_s <= 0 or self.max_queue_segments < 1:
            raise ValueError("fps, latency, and queue size must be positive")

    @property
    def frame_interval_ms(self) -> float:
        return 1000.0 / self.fps

    def accepts(self, *, p95_latency_s: float, dropped_segments: int) -> bool:
        return p95_latency_s <= self.max_segment_latency_s and dropped_segments == 0


class BoundedSegmentQueue:
    """Thread-safe queue that favors fresh camera content over stale work."""

    def __init__(self, max_segments: int):
        if max_segments < 1:
            raise ValueError("max_segments must be at least one")
        self._items: Deque[bytes] = deque()
        self._maximum = max_segments
        self._condition = threading.Condition()
        self.dropped_segments = 0

    def put(self, segment: bytes) -> None:
        if not segment:
            raise ValueError("segment must not be empty")
        with self._condition:
            if len(self._items) >= self._maximum:
                self._items.popleft()
                self.dropped_segments += 1
            self._items.append(bytes(segment))
            self._condition.notify()

    def get(self, timeout_s: float | None = None) -> bytes | None:
        with self._condition:
            if not self._items:
                self._condition.wait(timeout=timeout_s)
            return self._items.popleft() if self._items else None

    @property
    def size(self) -> int:
        with self._condition:
            return len(self._items)


class ProofEpochCoordinator:
    """Deduplicate expensive proof generation for all segments in an epoch."""

    def __init__(self, generate: Callable[[int], bytes]):
        self._generate = generate
        self._values: dict[int, bytes] = {}
        self._inflight: dict[int, threading.Event] = {}
        self._errors: dict[int, BaseException] = {}
        self._lock = threading.Lock()

    def get(self, epoch: int) -> bytes:
        with self._lock:
            if epoch in self._values:
                return self._values[epoch]
            event = self._inflight.get(epoch)
            owner = event is None
            if owner:
                event = threading.Event()
                self._inflight[epoch] = event
        assert event is not None
        if owner:
            try:
                value = bytes(self._generate(epoch))
                if not value:
                    raise ValueError("proof generator returned an empty proof")
                with self._lock:
                    self._values[epoch] = value
            except BaseException as exc:
                with self._lock:
                    self._errors[epoch] = exc
                raise
            finally:
                with self._lock:
                    self._inflight.pop(epoch, None)
                    event.set()
            return value
        event.wait()
        with self._lock:
            if epoch in self._errors:
                raise RuntimeError(f"proof generation failed for epoch {epoch}") from self._errors[epoch]
            return self._values[epoch]


def _start_code_at(data: bytes, index: int) -> int:
    if data[index:index + 4] == b"\x00\x00\x00\x01":
        return 4
    if data[index:index + 3] == b"\x00\x00\x01":
        return 3
    return 0


def _find_start_code(data: bytes, start: int = 0) -> int:
    for index in range(start, max(start, len(data) - 2)):
        length = _start_code_at(data, index)
        # The final three bytes of a four-byte start code also look like a
        # three-byte start code.  Do not rediscover that overlapping suffix.
        if length == 3 and index > 0 and data[index - 1] == 0:
            continue
        if length:
            return index
    return -1


class AnnexBSegmenter:
    """Emit complete Annex-B segments when the next IDR begins.

    SPS/PPS/SEI NAL units immediately preceding an IDR are prepended to that
    segment. The final open segment is intentionally retained until another
    IDR appears, preventing an incomplete frame from being handed to a proof
    or patching worker.
    """

    _PREFIX_TYPES = {6, 7, 8}

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._prefix = bytearray()
        self._active = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        if not chunk:
            return []
        self._buffer.extend(chunk)
        emitted: list[bytes] = []
        while True:
            first = _find_start_code(self._buffer)
            if first < 0:
                if len(self._buffer) > 3:
                    del self._buffer[:-3]
                break
            if first:
                del self._buffer[:first]
            code_length = _start_code_at(self._buffer, 0)
            next_start = _find_start_code(self._buffer, code_length)
            if next_start < 0:
                # An IDR header starts the next independently decodable
                # segment. Its payload may still be arriving, but the prior
                # active segment is complete and can leave the camera path
                # immediately instead of waiting for another NAL boundary.
                if (
                    self._active
                    and len(self._buffer) > code_length
                    and (self._buffer[code_length] & 0x1F) == 5
                ):
                    emitted.append(bytes(self._prefix + self._active))
                    self._active.clear()
                break
            nal = bytes(self._buffer[:next_start])
            del self._buffer[:next_start]
            if len(nal) <= code_length:
                continue
            nal_type = nal[code_length] & 0x1F
            if nal_type == 5:
                if self._active:
                    emitted.append(bytes(self._prefix + self._active))
                self._active = bytearray(nal)
                self._prefix.clear()
            elif self._active:
                self._active.extend(nal)
            elif nal_type in self._PREFIX_TYPES:
                self._prefix.extend(nal)
        return emitted


@dataclass(frozen=True)
class EdgeSegmentResult:
    epoch: int
    input_bytes: int
    output_bytes: int
    latency_s: float


class EdgeSegmentPipeline:
    """A local worker loop suitable for direct camera ingestion on an edge box."""

    def __init__(
        self,
        budget: EdgeRealtimeBudget,
        proof_for_epoch: Callable[[int], bytes],
        process: Callable[[bytes, bytes], bytes],
    ) -> None:
        self.budget = budget
        self.segmenter = AnnexBSegmenter()
        self.queue = BoundedSegmentQueue(budget.max_queue_segments)
        self.proofs = ProofEpochCoordinator(proof_for_epoch)
        self.process = process
        self.results: list[EdgeSegmentResult] = []

    def ingest(self, chunk: bytes) -> int:
        segments = self.segmenter.feed(chunk)
        for segment in segments:
            self.queue.put(segment)
        return len(segments)

    def process_one(self, epoch: int, timeout_s: float = 0.0) -> EdgeSegmentResult | None:
        segment = self.queue.get(timeout_s)
        if segment is None:
            return None
        started = time.perf_counter()
        output = self.process(segment, self.proofs.get(epoch))
        result = EdgeSegmentResult(
            epoch=epoch,
            input_bytes=len(segment),
            output_bytes=len(output),
            latency_s=time.perf_counter() - started,
        )
        self.results.append(result)
        return result
