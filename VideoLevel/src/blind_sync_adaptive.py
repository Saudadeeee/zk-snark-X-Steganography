"""Capacity-adaptive blind payload transport over GOP-aligned H.264 segments.

Opt-in alternative to ``src.blind_sync_streaming`` (which is unchanged): the
chunk carried by each segment follows that segment's stable-carrier capacity
under a pinned :class:`~src.adaptive_chunks.AdaptiveChunkPlan`, low-capacity
segments are skipped, and every chunk is ZKBC v2 framed.

Blindness: a segment's capacity is the number of stable, patchability-checked
carriers of the operating contract.  Embedding flips only magnitude LSBs of
|level| >= 4 non-trailing-one coefficients (or trailing-one signs), which keeps
every block's zero pattern, trailing ones, total coefficients and hence nC and
CAVLC lengths, and the stable candidate rule is symmetric under the flip
(``src.core.stego.select_rederivable_stable_candidate``).  So the carrier set
of an embedded segment, and its count, equal the cover's; skipped and unused
segments are byte-identical.  The extractor therefore recomputes the same
capacities, the same plan and the same layout from the stego video alone.

The combined canonical digest binds the plan id, the payload size and, per
segment, its role, capacity and chunk size, so the statement covers the plan.
"""

from __future__ import annotations

import hashlib
import os
import struct
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adaptive_chunks import (
    CHUNK_HEADER,
    MAX_CHUNK_INDEX,
    MAX_SEGMENT_INDEX,
    AdaptiveChunkPlan,
    ChunkSlot,
    encode_adaptive_chunk,
    parse_adaptive_chunk,
    payload_crc,
    plan_layout,
)
from .blind_sync_streaming import (
    DEFAULT_STREAM_SEGMENT_FRAMES,
    ProgressCallback,
    _concatenate_annexb_segments,
    _emit_progress,
    _inspect_segments,
    _positive_int,
    _split_video_into_segments,
)
from .core.analysis_cache import (
    clear_video_analysis_cache,
    load_or_build_reconstruction_context,
    load_or_build_video_analysis,
    park_video_analysis_for_content_reuse,
)
from .gop_policy import ALL_INTRA
from .video_canonicalization import (
    DIGEST_V1,
    DIGEST_V2,
    SEGMENTATION_RULE_V2,
    raw_segment_sha256,
    require_digest_policy,
)

ROLE_UNUSED = 0  # after the payload: not analysed, hashed byte-for-byte
ROLE_SKIPPED = 1  # analysed, below the plan threshold: hashed byte-for-byte
ROLE_CARRIER = 2  # carries one chunk; the digest normalises its carriers
_DIGEST_DOMAIN = b"zkstego/canonical-h264-segmented-adaptive/v1\x00"
# DIGEST_V2 (codec policy v2): own domain plus the pinned segmentation rule.
_DIGEST_DOMAIN_V2 = b"zkstego/canonical-h264-segmented-adaptive/v2\x00"


@dataclass(frozen=True)
class SegmentRecord:
    index: int
    frame_count: int
    role: int
    capacity_bits: int
    chunk_bytes: int
    digest: str


@dataclass(frozen=True)
class AdaptiveVideoContext:
    positions_hash: str
    canonical_video_sha256: str
    global_positions: tuple[tuple[int, int, int], ...]
    segments_used: int
    frames_per_segment: int
    segment_capacity_bits: tuple[int, ...]
    layout: tuple[ChunkSlot, ...]


@dataclass(frozen=True)
class AdaptiveVideoEmbedResult:
    output_path: str
    payload_bytes: int
    segments_used: int
    carriers_used: int
    segment_capacity_bits: tuple[int, ...]
    layout: tuple[ChunkSlot, ...]


@dataclass(frozen=True)
class AdaptiveVideoPayloadResult:
    payload: bytes
    segments_used: int
    carriers_used: int
    positions_hash: str
    canonical_video_sha256: str
    global_positions: tuple[tuple[int, int, int], ...]
    # Exactly as extracted, so a verifier can require them to be the
    # canonical encoding of ``payload`` under the recomputed plan.
    chunks: tuple[bytes, ...]
    segment_capacity_bits: tuple[int, ...]
    layout: tuple[ChunkSlot, ...]


@dataclass(frozen=True)
class _Carried:
    chunk: bytes
    positions: tuple[tuple[int, int, int], ...]
    carriers_used: int
    output: Path | None = None


@dataclass(frozen=True)
class _Walk:
    chunks: tuple[bytes, ...]
    layout: tuple[ChunkSlot, ...]
    capacities: tuple[int, ...]
    records: tuple[SegmentRecord, ...]
    global_positions: tuple[tuple[int, int, int], ...]
    carriers_used: int
    output_segments: tuple[Path, ...]
    payload: bytes

    @property
    def payload_bytes(self) -> int:
        return len(self.payload)


Carry = Callable[[int, Path, ChunkSlot], _Carried]


def _require_contract(contract: Any, sync_key: bytes) -> None:
    if not getattr(contract, "stable_carriers_only", False):
        raise ValueError("adaptive segmented transport requires stable carriers")
    if not getattr(contract, "require_bitstream_patchable", False):
        raise ValueError("adaptive segmented transport requires patchability validation")
    if not isinstance(sync_key, bytes) or not sync_key:
        raise ValueError("sync_key must be non-empty bytes")


def _require_plan(plan: AdaptiveChunkPlan) -> AdaptiveChunkPlan:
    if not isinstance(plan, AdaptiveChunkPlan):
        raise TypeError("plan must be an AdaptiveChunkPlan")
    return plan


def segment_capacity_bits(segment_path: str | Path, sync_key: bytes, contract: Any) -> int:
    """Envelope bits one segment can carry; recomputable from cover or stego.

    Direct contracts carry one envelope bit per stable carrier.  A syndrome
    coded contract spends ``header_carriers_per_bit * 112`` carriers on the
    header code and one carrier per body bit (``coded_carrier_layout``).  The
    count does not depend on the sync key: the key only orders the set.
    """
    from .blind_sync import (
        BLIND_ENVELOPE_HEADER_BYTES,
        _require_coded_contract,
        derive_blind_positions_operating_contract,
        is_syndrome_coded,
    )

    positions, _metadata = derive_blind_positions_operating_contract(
        str(segment_path), sync_key, sys.maxsize, contract, use_analysis_cache=True
    )
    available = len(positions)
    if not is_syndrome_coded(contract):
        return available
    _require_coded_contract(contract)
    header_bits = BLIND_ENVELOPE_HEADER_BYTES * 8
    header_carriers = header_bits * contract.header_carriers_per_bit
    return 0 if available < header_carriers else available - header_carriers + header_bits


def combine_adaptive_segment_digests(
    records: tuple[SegmentRecord, ...] | list[SegmentRecord],
    frames_per_segment: int,
    plan: AdaptiveChunkPlan,
    payload_bytes: int,
    digest_policy: str = DIGEST_V1,
) -> str:
    """Domain-separated digest of the segmentation, the plan and every segment.

    Roles already type every segment digest; ``DIGEST_V2`` additionally uses
    its own domain and binds the pinned segmentation rule.
    """
    require_digest_policy(digest_policy)
    if digest_policy == DIGEST_V2:
        rule = SEGMENTATION_RULE_V2.encode("ascii")
        digest = hashlib.sha256(_DIGEST_DOMAIN_V2)
        digest.update(struct.pack(">H", len(rule)) + rule)
    else:
        digest = hashlib.sha256(_DIGEST_DOMAIN)
    digest.update(_require_plan(plan).plan_id())
    digest.update(struct.pack(">III", frames_per_segment, payload_bytes, len(records)))
    for expected, record in enumerate(records):
        if record.index != expected:
            raise ValueError("segment records are not in index order")
        digest.update(
            struct.pack(
                ">IIBQI", record.index, record.frame_count, record.role,
                record.capacity_bits, record.chunk_bytes,
            )
        )
        digest.update(bytes.fromhex(record.digest))
    return digest.hexdigest()


def _canonical_segment_digest(segment: Path, positions, global_offset_slots: int,
                              macroblocks: list[int], digest_policy: str,
                              ) -> tuple[str, list[tuple[int, int, int]]]:
    """Canonical digest of a carrier segment and its globalised positions."""
    from .video_canonicalization import canonical_video_sha256

    analysis = load_or_build_video_analysis(segment, use_cache=True, stable_blind_only=True)
    reconstruction = load_or_build_reconstruction_context(segment, use_cache=True)
    current = int(reconstruction["mb_count_per_slice"])
    if not macroblocks:
        macroblocks.append(current)
    elif current != macroblocks[0]:
        raise ValueError("video resolution changes between H.264 segments")
    digest = canonical_video_sha256(
        segment, positions, parser=reconstruction["parser"], frame_verified_data=analysis[1],
        digest_policy=digest_policy,
    )
    shifted = [(mb + global_offset_slots * current, block, coefficient)
               for mb, block, coefficient in positions]
    return digest, shifted


def _walk(
    segments: list[Path], frame_counts: list[int], structures: list[Any], *,
    payload_bytes: int | None, plan: AdaptiveChunkPlan, sync_key: bytes, contract: Any,
    carry: Carry, bind: bool, phase: str, progress_callback: ProgressCallback | None,
    keep_last_analysis: bool = False, digest_policy: str = DIGEST_V1,
) -> _Walk:
    """Visit segments in order, applying the greedy plan; fail closed on any deviation.

    ``payload_bytes`` is ``None`` only for extraction without a pinned size:
    the first chunk header then supplies it, and every later field is checked
    against the plan it implies.
    """
    total = payload_bytes
    offset = 0
    total_crc: int | None = None
    chunks: list[bytes] = []
    layout: list[ChunkSlot] = []
    capacities: list[int] = []
    records: list[SegmentRecord] = []
    global_positions: list[tuple[int, int, int]] = []
    outputs: list[Path] = []
    carriers_used = 0
    slot_offset = 0
    macroblocks: list[int] = []
    for index, (segment, frame_count) in enumerate(zip(segments, frame_counts, strict=True)):
        coded_slices = structures[index].coded_slices
        events = {"segment_index": index, "segments_total": len(segments)}
        if total is not None and offset == total:
            _emit_progress(progress_callback, phase, "segment_unused", **events)
            records.append(SegmentRecord(index, frame_count, ROLE_UNUSED, 0, 0,
                                         raw_segment_sha256(segment, digest_policy) if bind else ""))
            outputs.append(segment)
            slot_offset += coded_slices
            continue
        _emit_progress(progress_callback, phase, "segment_started", **events)
        capacity = segment_capacity_bits(segment, sync_key, contract)
        capacities.append(capacity)
        usable = plan.chunk_capacity_bytes(capacity)
        if usable == 0:
            records.append(SegmentRecord(index, frame_count, ROLE_SKIPPED, capacity, 0,
                                         raw_segment_sha256(segment, digest_policy) if bind else ""))
            outputs.append(segment)
            slot_offset += coded_slices
            clear_video_analysis_cache()
            _emit_progress(progress_callback, phase, "segment_below_threshold",
                           capacity_bits=capacity, **events)
            continue
        if index > MAX_SEGMENT_INDEX or len(layout) > MAX_CHUNK_INDEX:
            raise ValueError("adaptive plan exceeds the segment or chunk index range")
        planned = usable if total is None else min(total - offset, usable)
        carried = carry(index, segment, ChunkSlot(len(layout), index, offset, planned))
        header = parse_adaptive_chunk(carried.chunk)
        if total is None:
            total = header.total_size
            planned = min(total - offset, usable)
        expected = (len(layout), index, total, offset)
        actual = (header.chunk_index, header.segment_index, header.total_size, header.offset)
        if actual != expected or len(header.part) != planned:
            raise ValueError(f"segment {index}: chunk does not match the adaptive plan")
        if total_crc is None:
            total_crc = header.total_crc
        elif header.total_crc != total_crc:
            raise ValueError(f"segment {index}: payload checksum changes between chunks")
        chunks.append(carried.chunk)
        layout.append(ChunkSlot(len(layout), index, offset, planned))
        offset += planned
        carriers_used += carried.carriers_used
        outputs.append(carried.output or segment)
        digest = ""
        if bind:
            digest, shifted = _canonical_segment_digest(
                segment, carried.positions, slot_offset, macroblocks, digest_policy
            )
            global_positions.extend(shifted)
        records.append(SegmentRecord(index, frame_count, ROLE_CARRIER, capacity, planned, digest))
        slot_offset += coded_slices
        if not (keep_last_analysis and offset == total):
            clear_video_analysis_cache()
        _emit_progress(progress_callback, phase, "segment_completed",
                       carriers_used=carried.carriers_used, capacity_bits=capacity, **events)
    if total is None or offset != total:
        missing = "all" if total is None else f"{total - offset} of {total}"
        raise ValueError(
            f"carrier capacity is insufficient for the adaptive plan: {missing} payload bytes "
            "did not fit the video's segments"
        )
    payload = b"".join(chunk[CHUNK_HEADER.size:] for chunk in chunks)
    if payload_crc(payload) != total_crc:
        raise ValueError("assembled payload checksum mismatch")
    return _Walk(tuple(chunks), tuple(layout), tuple(capacities), tuple(records),
                 tuple(global_positions), carriers_used, tuple(outputs), payload)


def _prepare(video_path: str | Path, temp_dir: str, frames_per_segment: int, ffmpeg: str,
             ffprobe: str, gop_policy: str, progress_callback: ProgressCallback | None,
             phase: str, digest_policy: str) -> tuple[list[Path], list[int], list[Any]]:
    _positive_int("frames_per_segment", frames_per_segment)
    require_digest_policy(digest_policy)
    segments, frame_counts = _split_video_into_segments(
        video_path, temp_dir, frames_per_segment, ffmpeg=ffmpeg, ffprobe=ffprobe,
        progress_callback=progress_callback if phase == "extract" else None,
        digest_policy=digest_policy,
    )
    structures = _inspect_segments(segments, frame_counts, gop_policy)
    _emit_progress(progress_callback, phase, "segments_ready",
                   segments_total=len(segments), frames_total=sum(frame_counts))
    return segments, frame_counts, structures


def _source(path: str | Path, name: str) -> Path:
    source = Path(path).resolve(strict=True)
    if not source.is_file():
        raise ValueError(f"{name} must identify a regular file")
    return source


def derive_adaptive_video_context(
    video_path: str | Path, payload: bytes, sync_key: bytes, contract: Any, *,
    plan: AdaptiveChunkPlan, frames_per_segment: int = DEFAULT_STREAM_SEGMENT_FRAMES,
    ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
    progress_callback: ProgressCallback | None = None, gop_policy: str = ALL_INTRA,
    digest_policy: str = DIGEST_V1,
) -> AdaptiveVideoContext:
    """Plan the chunks, select their carriers and compute the bound video context.

    Only the payload length matters: a same-length placeholder yields the
    positions and digest the real payload will have.
    """
    source = _source(video_path, "video_path")
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    _require_contract(contract, sync_key)
    _require_plan(plan)
    from .blind_sync import (
        derive_blind_positions_operating_contract,
        derive_coded_carrier_positions,
        is_syndrome_coded,
        pack_blind_payload,
    )
    from .manifest import hash_positions

    total_crc = payload_crc(payload)

    def carry(index: int, segment: Path, slot: ChunkSlot) -> _Carried:
        chunk = encode_adaptive_chunk(payload, slot, total_crc)
        required_bits = len(pack_blind_payload(chunk)) * 8
        if is_syndrome_coded(contract):
            positions, _metadata = derive_coded_carrier_positions(
                str(segment), sync_key, required_bits, contract
            )
            required_bits = len(positions)
        else:
            positions, _metadata = derive_blind_positions_operating_contract(
                str(segment), sync_key, required_bits, contract, use_analysis_cache=True
            )
        if len(positions) != required_bits:
            raise ValueError(
                f"segment {index} has insufficient patchable stable carriers: "
                f"need {required_bits}, got {len(positions)}"
            )
        return _Carried(chunk, tuple(positions), len(positions))

    with tempfile.TemporaryDirectory(prefix="zkstego-adaptive-context-") as temp_name:
        segments, frame_counts, structures = _prepare(
            source, temp_name, frames_per_segment, ffmpeg, ffprobe, gop_policy,
            progress_callback, "carrier_context", digest_policy,
        )
        completed = False
        try:
            walk = _walk(segments, frame_counts, structures, payload_bytes=len(payload),
                         plan=plan, sync_key=sync_key, contract=contract, carry=carry,
                         bind=True, phase="carrier_context",
                         progress_callback=progress_callback, keep_last_analysis=True,
                         digest_policy=digest_policy)
            completed = True
        finally:
            if completed:
                # The embedder re-analyses the byte-identical last carrier
                # segment next; keep that analysis for reuse by content.
                park_video_analysis_for_content_reuse()
            else:
                clear_video_analysis_cache()
    return AdaptiveVideoContext(
        positions_hash=hash_positions(list(walk.global_positions)),
        canonical_video_sha256=combine_adaptive_segment_digests(
            walk.records, frames_per_segment, plan, walk.payload_bytes, digest_policy
        ),
        global_positions=walk.global_positions,
        segments_used=len(walk.layout),
        frames_per_segment=frames_per_segment,
        segment_capacity_bits=walk.capacities,
        layout=walk.layout,
    )


def embed_adaptive_video_payload(
    cover_video_path: str | Path, output_video_path: str | Path, payload: bytes,
    sync_key: bytes, contract: Any, *, plan: AdaptiveChunkPlan,
    expected_layout: tuple[ChunkSlot, ...] | None = None,
    frames_per_segment: int = DEFAULT_STREAM_SEGMENT_FRAMES,
    ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
    progress_callback: ProgressCallback | None = None, gop_policy: str = ALL_INTRA,
    digest_policy: str = DIGEST_V1,
) -> AdaptiveVideoEmbedResult:
    """Embed ZKBC v2 chunks under the plan; only IDR slices of carrier segments change.

    ``expected_layout`` (from :func:`derive_adaptive_video_context`) makes the
    embedder fail closed if the plan it recomputes differs.
    """
    source = _source(cover_video_path, "cover_video_path")
    output = Path(output_video_path).resolve()
    if source == output:
        raise ValueError("output video must differ from input video")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"output video already exists: {output}")
    if not output.parent.is_dir():
        raise FileNotFoundError("output video directory does not exist")
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    _require_contract(contract, sync_key)
    _require_plan(plan)
    from .blind_sync import embed_blind_video_payload
    from .embedder import _strict_validate_h264_decode

    total_crc = payload_crc(payload)
    with tempfile.TemporaryDirectory(prefix="zkstego-adaptive-", dir=output.parent) as temp_name:
        temp_dir = Path(temp_name)

        def carry(index: int, segment: Path, slot: ChunkSlot) -> _Carried:
            if expected_layout is not None and (
                slot.chunk_index >= len(expected_layout) or expected_layout[slot.chunk_index] != slot
            ):
                raise RuntimeError(f"segment {index}: recomputed plan differs from the derived layout")
            chunk = encode_adaptive_chunk(payload, slot, total_crc)
            stego_segment = temp_dir / f"stego_{index:05}.h264"
            result = embed_blind_video_payload(str(segment), str(stego_segment), chunk,
                                               sync_key, contract)
            return _Carried(chunk, (), result.carriers_used, stego_segment)

        segments, frame_counts, structures = _prepare(
            source, temp_name, frames_per_segment, ffmpeg, ffprobe, gop_policy,
            progress_callback, "embed", digest_policy,
        )
        try:
            walk = _walk(segments, frame_counts, structures, payload_bytes=len(payload),
                         plan=plan, sync_key=sync_key, contract=contract, carry=carry,
                         bind=False, phase="embed", progress_callback=progress_callback)
            if expected_layout is not None and walk.layout != tuple(expected_layout):
                raise RuntimeError("recomputed plan differs from the derived layout")
            candidate = temp_dir / "candidate.h264"
            _emit_progress(progress_callback, "embed", "assembly_started",
                           segments_total=len(walk.output_segments))
            _concatenate_annexb_segments(list(walk.output_segments), candidate)
            _strict_validate_h264_decode(str(candidate))
            _emit_progress(progress_callback, "embed", "decode_passed",
                           segments_total=len(walk.output_segments))
            try:
                os.link(candidate, output)
            except FileExistsError:
                raise FileExistsError(f"output video appeared during embedding: {output}") from None
        finally:
            clear_video_analysis_cache()
    return AdaptiveVideoEmbedResult(
        output_path=str(output), payload_bytes=len(payload), segments_used=len(walk.layout),
        carriers_used=walk.carriers_used, segment_capacity_bits=walk.capacities,
        layout=walk.layout,
    )


def extract_adaptive_video_payload(
    video_path: str | Path, sync_key: bytes, contract: Any, *, plan: AdaptiveChunkPlan,
    payload_bytes: int | None = None, frames_per_segment: int = DEFAULT_STREAM_SEGMENT_FRAMES,
    ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
    progress_callback: ProgressCallback | None = None, gop_policy: str = ALL_INTRA,
    digest_policy: str = DIGEST_V1,
) -> AdaptiveVideoPayloadResult:
    """Recompute capacities and plan from the video alone, then extract and check.

    ``payload_bytes`` pins the payload size (the verifier knows the envelope
    size); without it the first chunk's declared size is used and checked.
    """
    source = _source(video_path, "video_path")
    _require_contract(contract, sync_key)
    _require_plan(plan)
    if payload_bytes is not None:
        _positive_int("payload_bytes", payload_bytes)
    from .blind_sync import extract_blind_video_payload
    from .manifest import hash_positions

    def carry(_index: int, segment: Path, _slot: ChunkSlot) -> _Carried:
        result = extract_blind_video_payload(str(segment), sync_key, contract)
        return _Carried(result.payload, tuple(result.carrier_positions), result.carriers_used)

    with tempfile.TemporaryDirectory(prefix="zkstego-adaptive-extract-") as temp_name:
        segments, frame_counts, structures = _prepare(
            source, temp_name, frames_per_segment, ffmpeg, ffprobe, gop_policy,
            progress_callback, "extract", digest_policy,
        )
        try:
            walk = _walk(segments, frame_counts, structures, payload_bytes=payload_bytes,
                         plan=plan, sync_key=sync_key, contract=contract, carry=carry,
                         bind=True, phase="extract", progress_callback=progress_callback,
                         digest_policy=digest_policy)
        finally:
            clear_video_analysis_cache()
    # Recompute the whole plan from the capacities and require it to match.
    if plan_layout(walk.payload_bytes, walk.capacities, plan) != walk.layout:
        raise ValueError("extracted layout differs from the plan of the recomputed capacities")
    return AdaptiveVideoPayloadResult(
        payload=walk.payload,
        segments_used=len(walk.layout),
        carriers_used=walk.carriers_used,
        positions_hash=hash_positions(list(walk.global_positions)),
        canonical_video_sha256=combine_adaptive_segment_digests(
            walk.records, frames_per_segment, plan, walk.payload_bytes, digest_policy
        ),
        global_positions=walk.global_positions,
        chunks=walk.chunks,
        segment_capacity_bits=walk.capacities,
        layout=walk.layout,
    )
