"""Bounded-latency transport primitives for live H.264 Annex-B streams.

This module deliberately separates transport from coefficient mutation.  The
existing CAVLC patcher is file-oriented and must not be called on an arbitrary
live NAL as though it were realtime-safe.  A live mutator receives complete
access units from this module and may only return a length-preserving,
independently validated replacement.  Otherwise the relay forwards the source
unit unchanged.

The supported transport contract is Annex-B with Access Unit Delimiters (AUD,
NAL type 9).  Configure an upstream encoder with ``aud=1``.  This gives a
deterministic frame boundary without guessing from slice headers.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Iterable, Optional, Protocol


ANNEXB_START_CODE = b"\x00\x00\x00\x01"


@dataclass(frozen=True)
class AnnexBNal:
    """One H.264 NAL payload, excluding its Annex-B start code."""

    payload: bytes

    def __post_init__(self) -> None:
        if not self.payload:
            raise ValueError("Annex-B NAL payload cannot be empty")

    @property
    def nal_type(self) -> int:
        return self.payload[0] & 0x1F

    def to_annexb(self) -> bytes:
        return ANNEXB_START_CODE + self.payload


def _start_code_positions(data: bytes) -> list[tuple[int, int]]:
    """Return non-overlapping ``(offset, length)`` Annex-B prefixes."""
    result: list[tuple[int, int]] = []
    index = 0
    limit = len(data)
    while index + 3 <= limit:
        if data[index:index + 4] == ANNEXB_START_CODE:
            result.append((index, 4))
            index += 4
        elif data[index:index + 3] == b"\x00\x00\x01":
            result.append((index, 3))
            index += 3
        else:
            index += 1
    return result


class AnnexBStreamParser:
    """Incrementally split arbitrary byte chunks into complete Annex-B NALs."""

    def __init__(self) -> None:
        self._buffer = b""
        self.discarded_prefix_bytes = 0

    def feed(self, data: bytes) -> list[AnnexBNal]:
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("Annex-B input must be bytes")
        if not data:
            return []
        self._buffer += bytes(data)
        prefixes = _start_code_positions(self._buffer)
        if not prefixes:
            # Retain up to three trailing bytes: they may be a split start code.
            if len(self._buffer) > 3:
                self.discarded_prefix_bytes += len(self._buffer) - 3
                self._buffer = self._buffer[-3:]
            return []

        first_offset, _first_length = prefixes[0]
        if first_offset:
            self.discarded_prefix_bytes += first_offset
            self._buffer = self._buffer[first_offset:]
            prefixes = _start_code_positions(self._buffer)

        output: list[AnnexBNal] = []
        for (offset, length), (next_offset, _next_length) in zip(prefixes, prefixes[1:]):
            payload = self._buffer[offset + length:next_offset]
            if payload:
                output.append(AnnexBNal(payload))
        last_offset, _last_length = prefixes[-1]
        self._buffer = self._buffer[last_offset:]
        return output

    def finish(self) -> list[AnnexBNal]:
        """Flush the final NAL at end-of-stream; no partial NAL is invented."""
        prefixes = _start_code_positions(self._buffer)
        if not prefixes:
            self.discarded_prefix_bytes += len(self._buffer)
            self._buffer = b""
            return []
        offset, length = prefixes[-1]
        payload = self._buffer[offset + length:]
        self._buffer = b""
        return [AnnexBNal(payload)] if payload else []


@dataclass(frozen=True)
class AccessUnit:
    """A complete AUD-delimited H.264 access unit."""

    nals: tuple[AnnexBNal, ...]
    sequence: int

    def __post_init__(self) -> None:
        if not self.nals:
            raise ValueError("access unit must contain at least one NAL")

    @property
    def is_idr(self) -> bool:
        return any(nal.nal_type == 5 for nal in self.nals)

    def to_annexb(self) -> bytes:
        return b"".join(nal.to_annexb() for nal in self.nals)


class AccessUnitAssembler:
    """Assemble complete access units, enforcing AUD boundaries by default."""

    def __init__(self, require_aud: bool = True) -> None:
        self.require_aud = require_aud
        self._prefix: list[AnnexBNal] = []
        self._current: list[AnnexBNal] = []
        self._sequence = 0

    def _complete_current(self) -> list[AccessUnit]:
        if not self._current:
            return []
        unit = AccessUnit(tuple(self._current), self._sequence)
        self._sequence += 1
        self._current = []
        return [unit]

    def push(self, nal: AnnexBNal) -> list[AccessUnit]:
        if nal.nal_type == 9:  # access_unit_delimiter_rbsp
            completed = self._complete_current()
            self._current = [*self._prefix, nal]
            self._prefix = []
            return completed

        if not self._current:
            if nal.nal_type in {7, 8, 6}:  # SPS, PPS, SEI apply to next AU
                self._prefix.append(nal)
                return []
            if self.require_aud:
                raise ValueError("live Annex-B transport requires AUD before each access unit")
            self._current = [*self._prefix]
            self._prefix = []
        self._current.append(nal)
        return []

    def finish(self) -> list[AccessUnit]:
        return self._complete_current()


@dataclass
class QueueMetrics:
    accepted: int = 0
    dropped_non_idr: int = 0
    dropped_idr: int = 0
    high_watermark: int = 0


class BoundedAccessUnitQueue:
    """Small queue with a latency-first drop policy.

    On overflow, the oldest non-IDR unit is discarded first.  If every queued
    unit is IDR, an incoming non-IDR is discarded; an incoming IDR replaces the
    oldest IDR so the receiver can resynchronise at the newest keyframe.
    """

    def __init__(self, max_units: int = 3) -> None:
        if max_units < 1:
            raise ValueError("max_units must be positive")
        self.max_units = max_units
        self._items: Deque[AccessUnit] = deque()
        self.metrics = QueueMetrics()

    def offer(self, unit: AccessUnit) -> bool:
        if len(self._items) >= self.max_units:
            non_idr_index = next((index for index, item in enumerate(self._items) if not item.is_idr), None)
            if non_idr_index is not None:
                del self._items[non_idr_index]
                self.metrics.dropped_non_idr += 1
            elif not unit.is_idr:
                self.metrics.dropped_non_idr += 1
                return False
            else:
                self._items.popleft()
                self.metrics.dropped_idr += 1
        self._items.append(unit)
        self.metrics.accepted += 1
        self.metrics.high_watermark = max(self.metrics.high_watermark, len(self._items))
        return True

    def pop(self) -> AccessUnit:
        if not self._items:
            raise IndexError("access-unit queue is empty")
        return self._items.popleft()

    def __len__(self) -> int:
        return len(self._items)


@dataclass(frozen=True)
class PayloadChunk:
    sequence: int
    data: bytes


class RealtimePayloadScheduler:
    """Allocate a small, repeating control payload only to complete IDR AUs."""

    def __init__(self, payload: bytes, chunk_bytes: int = 16, repeat_every_idr: int = 1) -> None:
        if not payload:
            raise ValueError("realtime payload must not be empty")
        if chunk_bytes < 1:
            raise ValueError("chunk_bytes must be positive")
        if repeat_every_idr < 1:
            raise ValueError("repeat_every_idr must be positive")
        self.payload = bytes(payload)
        self.chunk_bytes = chunk_bytes
        self.repeat_every_idr = repeat_every_idr
        self._idr_seen = 0
        self._emitted = 0

    def next_for_access_unit(self, is_idr: bool) -> Optional[PayloadChunk]:
        if not is_idr:
            return None
        self._idr_seen += 1
        if (self._idr_seen - 1) % self.repeat_every_idr:
            return None
        offset = (self._emitted * self.chunk_bytes) % len(self.payload)
        data = self.payload[offset:offset + self.chunk_bytes]
        if len(data) < self.chunk_bytes:
            data += self.payload[:self.chunk_bytes - len(data)]
        chunk = PayloadChunk(sequence=self._emitted, data=data)
        self._emitted += 1
        return chunk


class AccessUnitMutator(Protocol):
    """A native/live backend that changes a validated access unit in place."""

    def __call__(self, access_unit: AccessUnit, payload: Optional[PayloadChunk]) -> AccessUnit: ...


@dataclass
class RelayMetrics:
    forwarded_units: int = 0
    idr_units: int = 0
    mutation_failures: int = 0
    scheduled_chunks: int = 0
    queue: QueueMetrics = field(default_factory=QueueMetrics)


class RealtimeAnnexBRelay:
    """Synchronous bounded relay suitable for a pipe worker or event loop.

    The supplied mutator is optional.  If it throws or returns invalid output,
    the original AU is forwarded and the failure becomes observable in metrics.
    This fail-open media policy prevents a security feature from taking down a
    live stream; deployments that require fail-closed behavior should wrap the
    relay and terminate the transport on ``mutation_failures``.
    """

    def __init__(
        self,
        scheduler: RealtimePayloadScheduler,
        mutator: Optional[AccessUnitMutator] = None,
        max_queue_units: int = 3,
    ) -> None:
        self.parser = AnnexBStreamParser()
        self.assembler = AccessUnitAssembler(require_aud=True)
        self.queue = BoundedAccessUnitQueue(max_queue_units)
        self.scheduler = scheduler
        self.mutator = mutator
        self.metrics = RelayMetrics(queue=self.queue.metrics)

    def feed(self, data: bytes) -> bytes:
        output = bytearray()
        for nal in self.parser.feed(data):
            for unit in self.assembler.push(nal):
                self.queue.offer(unit)
        while self.queue:
            output.extend(self._process_one().to_annexb())
        return bytes(output)

    def finish(self) -> bytes:
        output = bytearray()
        for nal in self.parser.finish():
            for unit in self.assembler.push(nal):
                self.queue.offer(unit)
        for unit in self.assembler.finish():
            self.queue.offer(unit)
        while self.queue:
            output.extend(self._process_one().to_annexb())
        return bytes(output)

    def _process_one(self) -> AccessUnit:
        unit = self.queue.pop()
        payload = self.scheduler.next_for_access_unit(unit.is_idr)
        if unit.is_idr:
            self.metrics.idr_units += 1
        if payload is not None:
            self.metrics.scheduled_chunks += 1
        output = unit
        if self.mutator is not None:
            try:
                candidate = self.mutator(unit, payload)
                if not isinstance(candidate, AccessUnit):
                    raise TypeError("live mutator must return AccessUnit")
                output = candidate
            except Exception:
                self.metrics.mutation_failures += 1
        self.metrics.forwarded_units += 1
        return output
