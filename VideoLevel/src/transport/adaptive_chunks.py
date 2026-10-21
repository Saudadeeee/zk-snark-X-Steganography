"""Capacity-adaptive chunk plan and strict ZKBC v2 framing (opt-in transport).

The fixed-size transport (``src.transport.blind_payload_chunks``, ZKBC v1) puts chunk
*i* of one pinned size into video segment *i*, so the smallest segment bounds
every chunk.  Here the chunk sizes follow the per-segment carrier capacity:

* the capacity of a segment is its number of stable, patchability-checked
  carriers (in envelope bits), which embedding leaves unchanged, so the
  extractor recomputes it from the stego video alone;
* :func:`plan_layout` fills segments greedily in order, skipping segments
  whose usable chunk would be below the pinned ``min_chunk_bytes``;
* every ZKBC v2 header field is a function of the plan and the payload, and
  :func:`assemble_adaptive_chunks` / the verifier require the extracted chunks
  to be byte-equal to :func:`pack_adaptive_chunks` of the recomputed plan.

The plan parameters are part of the carrier profile id (and hence of the
relation and statement), see ``docs/CARRIERS_VA_CHUNKING.md``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import struct
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple

ADAPTIVE_PLAN_VERSION = "zkbc-v2-greedy-fill-v1"
CHUNK_MAGIC = b"ZKBC"
CHUNK_VERSION = 2
# magic, version, chunk index, segment index, total size, offset, total CRC-32.
CHUNK_HEADER = struct.Struct(">4sBHHIII")
# ``src.transport.blind_sync.BLIND_ENVELOPE_HEADER_BYTES``: the per-segment ZKVP frame
# around each chunk (kept literal so this module stays import-light; a test
# pins the equality).
SEGMENT_ENVELOPE_HEADER_BYTES = 14
FRAMING_BYTES = SEGMENT_ENVELOPE_HEADER_BYTES + CHUNK_HEADER.size
MAX_ADAPTIVE_PAYLOAD_BYTES = 16 * 1024 * 1024
MAX_SEGMENT_INDEX = 0xFFFF
MAX_CHUNK_INDEX = 0xFFFF
_PLAN_DOMAIN = b"zkstego/adaptive-chunk-plan/v1\0"


def _require_int(name: str, value: Any, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


@dataclass(frozen=True)
class AdaptiveChunkPlan:
    """Pinned parameters of the greedy, capacity-following chunk plan.

    ``usable bits = capacity * fill_permille // 1000 - reserve_bits``; the
    usable chunk is that in bytes minus the per-segment framing, capped at
    ``max_chunk_bytes``.  A segment whose usable chunk is below
    ``min_chunk_bytes`` is skipped (left byte-identical).  The capacity is
    recomputed exactly by the verifier, so ``reserve_bits`` is not needed for
    correctness; it and ``fill_permille`` bound the per-segment embedding
    density (fewer changed carriers per segment, more segments touched).
    """

    version: str = ADAPTIVE_PLAN_VERSION
    min_chunk_bytes: int = 256
    reserve_bits: int = 0
    fill_permille: int = 1000
    max_chunk_bytes: int = 65_535

    def __post_init__(self) -> None:
        if self.version != ADAPTIVE_PLAN_VERSION:
            raise ValueError(f"unsupported adaptive chunk plan version: {self.version!r}")
        _require_int("max_chunk_bytes", self.max_chunk_bytes, 1, MAX_ADAPTIVE_PAYLOAD_BYTES)
        _require_int("min_chunk_bytes", self.min_chunk_bytes, 1, self.max_chunk_bytes)
        _require_int("reserve_bits", self.reserve_bits, 0, 1 << 40)
        _require_int("fill_permille", self.fill_permille, 1, 1000)

    def descriptor(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def plan_id(self) -> bytes:
        encoded = json.dumps(self.descriptor(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(_PLAN_DOMAIN + encoded.encode("ascii")).digest()

    def chunk_capacity_bytes(self, capacity_bits: int) -> int:
        """Largest chunk a segment of ``capacity_bits`` takes; 0 means skipped."""
        _require_int("capacity_bits", capacity_bits, 0, 1 << 48)
        usable_bits = capacity_bits * self.fill_permille // 1000 - self.reserve_bits
        if usable_bits <= 0:
            return 0
        usable = usable_bits // 8 - FRAMING_BYTES
        if usable < self.min_chunk_bytes:
            return 0
        return min(usable, self.max_chunk_bytes)


class ChunkSlot(NamedTuple):
    """One planned chunk: which bytes of the payload go into which segment."""

    chunk_index: int
    segment_index: int
    offset: int
    size: int


def _require_payload_size(payload_bytes: int) -> int:
    return _require_int("payload size", payload_bytes, 1, MAX_ADAPTIVE_PAYLOAD_BYTES)


def plan_layout(
    payload_bytes: int, capacities: Sequence[int], plan: AdaptiveChunkPlan
) -> tuple[ChunkSlot, ...]:
    """Greedy fill of segments in order; raise ``ValueError`` if it does not fit.

    Capacities after the segment that completes the payload are ignored.
    """
    _require_payload_size(payload_bytes)
    if not isinstance(plan, AdaptiveChunkPlan):
        raise TypeError("plan must be an AdaptiveChunkPlan")
    slots: list[ChunkSlot] = []
    offset = 0
    for segment_index, capacity in enumerate(capacities):
        if offset == payload_bytes:
            break
        usable = plan.chunk_capacity_bytes(capacity)
        if usable == 0:
            continue
        if segment_index > MAX_SEGMENT_INDEX or len(slots) > MAX_CHUNK_INDEX:
            raise ValueError("adaptive plan exceeds the segment or chunk index range")
        size = min(payload_bytes - offset, usable)
        slots.append(ChunkSlot(len(slots), segment_index, offset, size))
        offset += size
    if offset != payload_bytes:
        raise ValueError(
            f"carrier capacity is insufficient for the adaptive plan: "
            f"{payload_bytes - offset} of {payload_bytes} payload bytes do not fit"
        )
    return tuple(slots)


def _require_layout(payload_bytes: int, layout: Sequence[ChunkSlot]) -> None:
    if not layout:
        raise ValueError("an adaptive layout has at least one chunk")
    offset = 0
    previous_segment = -1
    for expected_index, slot in enumerate(layout):
        if not isinstance(slot, ChunkSlot):
            raise TypeError("layout entries must be ChunkSlot")
        if slot.chunk_index != expected_index or slot.offset != offset:
            raise ValueError("adaptive layout is not contiguous and in index order")
        if not previous_segment < slot.segment_index <= MAX_SEGMENT_INDEX:
            raise ValueError("adaptive layout segments must be strictly increasing")
        if slot.size <= 0:
            raise ValueError("adaptive layout chunks must be non-empty")
        offset += slot.size
        previous_segment = slot.segment_index
    if offset != payload_bytes:
        raise ValueError("adaptive layout does not cover the payload exactly")


def encode_adaptive_chunk(payload: bytes, slot: ChunkSlot, total_crc: int) -> bytes:
    """ZKBC v2 frame of one slot; every header field is fixed by the plan."""
    if not 0 <= slot.offset < slot.offset + slot.size <= len(payload):
        raise ValueError("chunk slot lies outside the payload")
    header = CHUNK_HEADER.pack(
        CHUNK_MAGIC, CHUNK_VERSION, slot.chunk_index, slot.segment_index,
        len(payload), slot.offset, total_crc,
    )
    return header + payload[slot.offset : slot.offset + slot.size]


def payload_crc(payload: bytes) -> int:
    return zlib.crc32(payload) & 0xFFFFFFFF


def pack_adaptive_chunks(payload: bytes, layout: Sequence[ChunkSlot]) -> list[bytes]:
    """The unique ZKBC v2 encoding of ``payload`` under ``layout``."""
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    _require_payload_size(len(payload))
    _require_layout(len(payload), layout)
    total_crc = payload_crc(payload)
    return [encode_adaptive_chunk(payload, slot, total_crc) for slot in layout]


def canonical_adaptive_chunks(
    payload: bytes, capacities: Sequence[int], plan: AdaptiveChunkPlan
) -> tuple[list[bytes], tuple[ChunkSlot, ...]]:
    layout = plan_layout(len(payload), capacities, plan)
    return pack_adaptive_chunks(payload, layout), layout


class AdaptiveChunkHeader(NamedTuple):
    chunk_index: int
    segment_index: int
    total_size: int
    offset: int
    total_crc: int
    part: bytes


def parse_adaptive_chunk(chunk: bytes) -> AdaptiveChunkHeader:
    """Validate the self-contained fields of one ZKBC v2 chunk."""
    if not isinstance(chunk, bytes):
        raise TypeError("chunk must be bytes")
    if len(chunk) <= CHUNK_HEADER.size:
        raise ValueError("chunk is truncated or has an empty body")
    magic, version, chunk_index, segment_index, total_size, offset, total_crc = (
        CHUNK_HEADER.unpack_from(chunk)
    )
    if magic != CHUNK_MAGIC or version != CHUNK_VERSION:
        raise ValueError("chunk magic or version is not ZKBC v2")
    if not 1 <= total_size <= MAX_ADAPTIVE_PAYLOAD_BYTES:
        raise ValueError("declared payload size is invalid")
    part = chunk[CHUNK_HEADER.size :]
    if offset + len(part) > total_size:
        raise ValueError("chunk extends beyond the declared payload")
    return AdaptiveChunkHeader(chunk_index, segment_index, total_size, offset, total_crc, part)


def assemble_adaptive_chunks(
    chunks: Sequence[bytes], capacities: Sequence[int], plan: AdaptiveChunkPlan
) -> tuple[bytes, tuple[ChunkSlot, ...]]:
    """Reassemble and require the chunks to be the canonical plan encoding.

    ``capacities`` are the per-segment capacities the caller recomputed from
    the video; anything but the exact canonical bytes is rejected.
    """
    if not isinstance(chunks, Sequence) or isinstance(chunks, (bytes, bytearray)) or not chunks:
        raise ValueError("chunks must be a non-empty sequence of byte strings")
    first = parse_adaptive_chunk(chunks[0])
    parts = [parse_adaptive_chunk(chunk).part for chunk in chunks]
    payload = b"".join(parts)
    if len(payload) != first.total_size:
        raise ValueError("assembled payload length mismatch")
    if payload_crc(payload) != first.total_crc:
        raise ValueError("assembled payload checksum mismatch")
    canonical, layout = canonical_adaptive_chunks(payload, capacities, plan)
    if list(chunks) != canonical:
        raise ValueError("chunks are not the canonical adaptive encoding of the payload")
    return payload, layout
