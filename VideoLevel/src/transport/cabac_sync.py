"""Blind payload transport over native H.264 CABAC (Main/High profile) streams.

Drop-in alternative to ``blind_sync_streaming`` (fixed ZKBC v1 chunks) and
``blind_sync_adaptive`` (capacity-adaptive ZKBC v2 chunks) for streams with
``entropy_coding_mode_flag = 1``; ``video_pipeline`` selects it for the codec
policy ``CODEC_POLICY_CABAC_V1``.  Design: docs/CABAC_SUPPORT.md.

Carriers (:class:`CabacMagnitudeContract`): in IDR slices only, one per
residual block (4x4 or I16x16-AC luma, 8x8 luma, chroma AC; DC blocks are
excluded), the coefficient of largest scan index with ``|level| >= 2``.
Embedding flips the LSB of ``|level|`` and keeps the sign, so the carrier set
of a stego segment equals the cover's.  The order is the keyed SPS-geometry
order of ``src.core.carrier_order``.

Canonical form: every IDR slice of a carrier segment is re-encoded by
``src.bitstream.cabac.encode_slice`` (the 9.3.4 encoder).  A verifier rejects
a carrier segment whose IDR slices are not byte-identical to the canonical
re-encoding of their own syntax, so the digest of the canonical encoding of
the carrier-normalised syntax binds every byte of the received slices.

Digest scope (``DIGEST_CABAC_V1``): segments must be the pinned access-unit
partition (``SEGMENTATION_RULE_V2``).  A carrier segment hashes, in stream
order, every start-code prefix and NAL unit: IDR slices as the canonical
encoding of their syntax with the used carriers' LSBs cleared, every other
NAL unit (SPS, PPS, SEI, P/B and non-IDR I slices) byte for byte.  Raw
segments hash their bytes under a separate domain.  Every value is length
prefixed and typed.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import hmac
import json
import os
import struct
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from ..bitstream.cabac import (
    AnnexBUnit,
    CabacError,
    CabacSlice,
    UnsupportedStream,
    collect_parameter_sets,
    decode_slice,
    encode_slice,
    join_annexb,
    split_annexb,
)
from ..bitstream.cabac.headers import (
    NAL_SLICE_IDR,
    NAL_SLICE_NON_IDR,
    BitReader,
    is_canonically_escaped,
    unescape,
)
from ..core.carrier_order import SPS_GEOMETRY_ORDER_V1, PictureGeometry, order_carriers
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
from .blind_payload_chunks import (
    assemble_payload_chunks,
    pack_payload_chunks,
    payload_chunk_count,
)
from .gop_policy import (
    ALL_INTRA,
    IDR_CARRIERS_INTER_RAW,
    SegmentStructure,
    _require_framed_stream,
    require_policy,
)
from .video_canonicalization import DIGEST_V2, SEGMENTATION_RULE_V2

DIGEST_CABAC_V1 = "cabac-canonical-syntax-carrier-normalized-v1"
CABAC_MAGNITUDE_CONTRACT_VERSION = "cabac-magnitude-sps-geometry-v1"
DEFAULT_STREAM_SEGMENT_FRAMES = 100
DEFAULT_STREAM_CHUNK_BYTES = 1_250
_SEGMENT_DOMAIN = b"zkstego/canonical-h264-cabac-segment/v1\x00"
_RAW_SEGMENT_DOMAIN = b"zkstego/canonical-h264-cabac-raw-segment/v1\x00"
_COMBINED_DOMAIN = b"zkstego/canonical-h264-cabac-segmented/v1\x00"
_ADAPTIVE_DOMAIN = b"zkstego/canonical-h264-cabac-segmented-adaptive/v1\x00"
_SEED_DOMAIN = b"zkstego/cabac-carrier-seed/v1\x00"
_ORDER_LABEL = b"|cabac-blind-order-v1"
_DATA_PARTITION_TYPES = frozenset({2, 3, 4})
_SLICE_P, _SLICE_B, _SLICE_I = 0, 1, 2
ROLE_UNUSED, ROLE_SKIPPED, ROLE_CARRIER = 0, 1, 2
# Carrier positions are ``slot * mbs_per_picture + mbAddr`` packed as int64 (here
# and in ``core.carrier_order``); with this pin the product stays far below 2^63
# for any segment the framing can hold.  The bitstream parser's own cap
# (``headers.MAX_MBS_PER_PICTURE``) is tighter; this one is the transport's.
MAX_TRANSPORT_MBS_PER_PICTURE = 1 << 24
# Faults the decoder or the position packing can raise on a crafted stream.  The
# pipeline treats ``ValueError`` as "reject this video" and must never crash.
_MALFORMED_STREAM_ERRORS = (struct.error, IndexError, KeyError, OverflowError, ZeroDivisionError, CabacError)
ProgressCallback = Callable[[dict[str, Any]], None]
_F = TypeVar("_F", bound=Callable[..., Any])


def _reject_malformed(function: _F) -> _F:
    """Convert parser faults on malformed input into ``ValueError`` (other errors pass through)."""

    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return function(*args, **kwargs)
        except _MALFORMED_STREAM_ERRORS as error:
            raise ValueError(f"malformed CABAC stream: {type(error).__name__}: {error}") from error

    return wrapper  # type: ignore[return-value]


@dataclass(frozen=True)
class CabacMagnitudeContract:
    """Verifier-pinned CABAC carrier rule (its fields enter the carrier profile id)."""

    version: str = CABAC_MAGNITUDE_CONTRACT_VERSION
    min_magnitude: int = 2
    dedup_per_block: bool = True
    include_chroma: bool = True
    carrier_order: str = SPS_GEOMETRY_ORDER_V1
    # Carriers are invariant under embedding, and every stego IDR slice is
    # canonically re-encoded and checked; both are what these flags assert.
    stable_carriers_only: bool = True
    require_bitstream_patchable: bool = True

    def __post_init__(self) -> None:
        if self.version != CABAC_MAGNITUDE_CONTRACT_VERSION:
            raise ValueError(f"unsupported CABAC contract version {self.version!r}")
        magnitude = self.min_magnitude
        if isinstance(magnitude, bool) or not isinstance(magnitude, int) or magnitude < 2 or magnitude & 1:
            # An odd threshold m would let the LSB flip m -> m - 1 leave the carrier set.
            raise ValueError("min_magnitude must be an even integer >= 2")
        if self.carrier_order != SPS_GEOMETRY_ORDER_V1:
            raise ValueError("CABAC carriers use the SPS geometry order")
        if not (self.stable_carriers_only and self.require_bitstream_patchable):
            raise ValueError("CABAC carriers are always stable and canonically re-encoded")


DEFAULT_CABAC_CONTRACT = CabacMagnitudeContract()


def _require_contract(contract: Any) -> CabacMagnitudeContract:
    if not isinstance(contract, CabacMagnitudeContract):
        raise ValueError("the CABAC transport needs a CabacMagnitudeContract")
    return contract


def _require_digest(digest_policy: str) -> None:
    if digest_policy != DIGEST_CABAC_V1:
        raise ValueError(f"the CABAC transport only implements digest policy {DIGEST_CABAC_V1!r}")


def _require_key(sync_key: bytes) -> None:
    if not isinstance(sync_key, bytes) or not sync_key:
        raise ValueError("sync_key must be non-empty bytes")


def _positive(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _emit(callback: ProgressCallback | None, phase: str, event: str, **details: Any) -> None:
    if callback is not None:
        callback({"phase": phase, "event": event, **details})


# --- segment structure -------------------------------------------------------

def _slice_prefix(nal: bytes) -> tuple[int, int]:
    reader = BitReader(unescape(nal[1:]))
    first_mb = reader.ue()
    slice_type = reader.ue()
    if slice_type > 9:
        raise ValueError(f"invalid slice_type {slice_type}")
    return first_mb, slice_type % 5


@_reject_malformed
def inspect_cabac_segment(data: bytes, gop_policy: str) -> SegmentStructure:
    """Check one Annex B segment for the CABAC transport; raise ``ValueError`` if it fails.

    Every segment starts with an IDR picture; pictures do not mix IDR and
    non-IDR slices; slices of a picture come in increasing first_mb order.
    ``ALL_INTRA`` allows IDR slices only; ``IDR_CARRIERS_INTER_RAW`` also
    allows P, B and non-IDR I slices, which are never parsed beyond their
    first two header fields and are bound byte for byte.
    """
    require_policy(gop_policy)
    _require_framed_stream(data)
    units = split_annexb(data)
    sps_map, pps_map = collect_parameter_sets(units)
    for sps in sps_map.values():
        if sps.mbs_per_picture > MAX_TRANSPORT_MBS_PER_PICTURE:
            raise ValueError(
                f"picture of {sps.mbs_per_picture} macroblocks exceeds the transport limit "
                f"of {MAX_TRANSPORT_MBS_PER_PICTURE}"
            )
    coded = pictures = idr = non_idr = p_slices = 0
    previous_first_mb = -1
    picture_type: int | None = None
    for unit in units:
        nal = unit.nal
        if nal[0] & 0x80:
            raise ValueError("NAL unit with forbidden_zero_bit set")
        if not is_canonically_escaped(nal[1:]):
            raise ValueError("NAL unit with non-canonical emulation prevention")
        nal_type = unit.nal_type
        if nal_type in _DATA_PARTITION_TYPES:
            raise ValueError("data-partitioned slices are not supported")
        if nal_type not in (NAL_SLICE_IDR, NAL_SLICE_NON_IDR):
            continue
        if not sps_map or not pps_map:
            raise ValueError("coded slice before the segment's SPS and PPS")
        for pps in pps_map.values():
            if not pps.entropy_coding_mode:
                raise UnsupportedStream("the CABAC transport needs entropy_coding_mode_flag = 1")
        first_mb, slice_type = _slice_prefix(nal)
        mbs = next(iter(sps_map.values())).mbs_per_picture
        if first_mb >= mbs:
            raise ValueError("first_mb_in_slice lies outside the picture")
        if coded == 0 and nal_type != NAL_SLICE_IDR:
            raise ValueError("transport segment does not start with an IDR slice")
        if first_mb == 0:
            pictures += 1
            picture_type = nal_type
        elif coded == 0:
            raise ValueError("transport segment starts in the middle of a picture")
        elif first_mb <= previous_first_mb:
            raise ValueError("arbitrary slice order is not supported")
        elif nal_type != picture_type:
            raise ValueError("a picture mixes IDR and non-IDR slices")
        previous_first_mb = first_mb
        coded += 1
        if nal_type == NAL_SLICE_IDR:
            if slice_type != _SLICE_I:
                raise ValueError("IDR NAL unit with a non-I slice type")
            idr += 1
            continue
        if gop_policy == ALL_INTRA:
            raise ValueError(
                "non-IDR slice in an all-intra carrier profile; use the "
                f"{IDR_CARRIERS_INTER_RAW!r} GOP policy for GOP > 1 streams"
            )
        if slice_type not in (_SLICE_P, _SLICE_B, _SLICE_I):
            raise ValueError("SP and SI slices are not supported")
        non_idr += 1
        p_slices += slice_type == _SLICE_P
    if coded == 0:
        raise ValueError("transport segment contains no coded slices")
    sizes = {(sps.width_mbs, sps.height_mbs) for sps in sps_map.values()}
    if len(sizes) != 1:
        raise ValueError("parameter sets of one segment disagree on the picture size")
    return SegmentStructure(coded, pictures, idr, non_idr, p_slices)


# --- segment analysis ------------------------------------------------------------

@dataclass
class _Segment:
    units: list[AnnexBUnit]
    slices: dict[int, CabacSlice]  # unit index -> decoded IDR slice
    geometry: PictureGeometry
    coded_slices: int
    candidates: list[tuple[int, int, int]]
    locator: dict[tuple[int, int, int], tuple[int, int, int, int]]

    def level(self, position: tuple[int, int, int]) -> tuple[list[int], int]:
        unit_index, mb_index, block, index = self.locator[position]
        return _block_list(self.slices[unit_index].macroblocks[mb_index], block), index


def _block_list(mb, block: int) -> list[int]:
    if block < 16:
        return mb.luma[block]
    if block < 20:
        return mb.luma8x8[block - 16]
    comp, blk = divmod(block - 20, 4)
    return mb.chroma_ac[comp][blk]


def _mb_blocks(mb, include_chroma: bool):
    """``(block id, coefficients, scan offset)`` of every coded non-DC block."""
    if mb.luma is not None:
        offset = 1 if mb.is_i16 else 0
        for blk, block in enumerate(mb.luma):
            if block is not None:
                yield blk, block, offset
    if mb.luma8x8 is not None:
        for b8, block in enumerate(mb.luma8x8):
            if block is not None:
                yield 16 + b8, block, 0
    if include_chroma and mb.chroma_ac is not None:
        for comp in range(2):
            for blk, block in enumerate(mb.chroma_ac[comp]):
                if block is not None:
                    yield 20 + 4 * comp + blk, block, 1


@_reject_malformed
def _analyze(data: bytes, contract: CabacMagnitudeContract, gop_policy: str) -> _Segment:
    structure = inspect_cabac_segment(data, gop_policy)
    units = split_annexb(data)
    sps_map, pps_map = collect_parameter_sets(units)
    sps = next(iter(sps_map.values()))
    geometry = PictureGeometry(sps.width_mbs, sps.height_mbs)
    per_picture = geometry.mbs_per_picture
    slices: dict[int, CabacSlice] = {}
    candidates: list[tuple[int, int, int]] = []
    locator: dict[tuple[int, int, int], tuple[int, int, int, int]] = {}
    threshold = contract.min_magnitude
    slot = -1
    for unit_index, unit in enumerate(units):
        if unit.nal_type not in (NAL_SLICE_IDR, NAL_SLICE_NON_IDR):
            continue
        slot += 1
        if unit.nal_type != NAL_SLICE_IDR:
            continue
        decoded = decode_slice(unit.nal, sps_map, pps_map)
        slices[unit_index] = decoded
        for mb_index, mb in enumerate(decoded.macroblocks):
            if mb.mb_type == 25:
                continue
            mb_key = slot * per_picture + mb.addr
            for block_id, block, offset in _mb_blocks(mb, contract.include_chroma):
                eligible = [i for i, value in enumerate(block) if abs(value) >= threshold]
                if not eligible:
                    continue
                chosen = eligible[-1:] if contract.dedup_per_block else eligible
                for index in chosen:
                    position = (mb_key, block_id, index + offset)
                    candidates.append(position)
                    locator[position] = (unit_index, mb_index, block_id, index)
    if slot + 1 != structure.coded_slices:
        raise ValueError("coded slice count mismatch")
    return _Segment(units, slices, geometry, structure.coded_slices, candidates, locator)


def _seed_base(segment: _Segment, contract: CabacMagnitudeContract) -> bytes:
    canonical = sorted(segment.candidates)
    fingerprint = hashlib.sha256()
    for position in canonical:
        fingerprint.update(struct.pack(">qqq", *position))
    descriptor = json.dumps(dataclasses.asdict(contract), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(
        _SEED_DOMAIN + struct.pack(">H", len(descriptor)) + descriptor.encode("ascii")
        + struct.pack(">IIQ", segment.geometry.width_mbs, segment.geometry.height_mbs, len(canonical))
        + fingerprint.digest()
    ).digest()


def _ordered(segment: _Segment, sync_key: bytes, contract: CabacMagnitudeContract) -> list[tuple[int, int, int]]:
    secret = hmac.new(sync_key, _seed_base(segment, contract) + _ORDER_LABEL, hashlib.sha256).digest()
    return order_carriers(segment.candidates, segment.geometry, secret)


@_reject_malformed
def segment_capacity_bits(segment_path: str | Path, sync_key: bytes, contract: Any,
                          gop_policy: str = ALL_INTRA) -> int:
    """Envelope bits one segment can carry: its carrier count (identical for cover and stego)."""
    _require_key(sync_key)
    return len(_analyze(Path(segment_path).read_bytes(), _require_contract(contract), gop_policy).candidates)


# --- per-segment carry ---------------------------------------------------------

def _bits(data: bytes) -> list[int]:
    return [(byte >> shift) & 1 for byte in data for shift in range(7, -1, -1)]


def _from_bits(bits: list[int]) -> bytes:
    out = bytearray()
    for start in range(0, len(bits), 8):
        value = 0
        for bit in bits[start:start + 8]:
            value = (value << 1) | bit
        out.append(value)
    return bytes(out)


def _canonical_bytes(segment: _Segment, slices: dict[int, CabacSlice] | None = None) -> bytes:
    source = segment.slices if slices is None else slices
    units = [
        AnnexBUnit(unit.prefix, encode_slice(source[index])) if index in source else unit
        for index, unit in enumerate(segment.units)
    ]
    return join_annexb(units)


def _require_canonical(segment: _Segment) -> None:
    for index, decoded in segment.slices.items():
        if encode_slice(decoded) != segment.units[index].nal:
            raise ValueError("an IDR slice is not the canonical CABAC encoding of its syntax")


@_reject_malformed
def _embed_segment(data: bytes, chunk: bytes, sync_key: bytes, contract: CabacMagnitudeContract,
                   gop_policy: str) -> tuple[bytes, int, int]:
    """Return ``(stego segment bytes, carriers used, carriers changed)``."""
    from .blind_sync import pack_blind_payload

    segment = _analyze(data, contract, gop_policy)
    bits = _bits(pack_blind_payload(chunk))
    order = _ordered(segment, sync_key, contract)
    if len(order) < len(bits):
        raise ValueError(f"segment has {len(order)} CABAC carriers, needs {len(bits)}")
    changed = 0
    for position, bit in zip(order, bits):
        block, index = segment.level(position)
        value = block[index]
        magnitude = abs(value)
        if magnitude & 1 != bit:
            magnitude ^= 1
            block[index] = magnitude if value > 0 else -magnitude
            changed += 1
    stego = _canonical_bytes(segment)
    # Self-check: the stego segment is canonical and yields the same carriers and chunk.
    extracted, positions = _extract_segment(stego, sync_key, contract, gop_policy)
    if extracted != chunk or positions != tuple(order[:len(bits)]):
        raise RuntimeError("CABAC embedding self-check failed")
    return stego, len(bits), changed


@_reject_malformed
def _extract_segment(data: bytes, sync_key: bytes, contract: CabacMagnitudeContract,
                     gop_policy: str, segment: _Segment | None = None,
                     ) -> tuple[bytes, tuple[tuple[int, int, int], ...]]:
    from .blind_sync import (
        BLIND_ENVELOPE_HEADER_BYTES,
        parse_blind_payload_header,
        unpack_blind_payload,
    )

    if segment is None:
        segment = _analyze(data, contract, gop_policy)
    _require_canonical(segment)
    order = _ordered(segment, sync_key, contract)

    def read(count: int) -> list[int]:
        if count > len(order):
            raise ValueError("declared payload exceeds the segment's CABAC carriers")
        out = []
        for position in order[:count]:
            block, index = segment.level(position)
            out.append(abs(block[index]) & 1)
        return out

    header_bits = BLIND_ENVELOPE_HEADER_BYTES * 8
    header = _from_bits(read(header_bits))
    total_bits = (BLIND_ENVELOPE_HEADER_BYTES + parse_blind_payload_header(header)) * 8
    envelope = _from_bits(read(total_bits))
    return unpack_blind_payload(envelope), tuple(order[:total_bits])


def _carrier_segment_digest(segment: _Segment, positions: tuple[tuple[int, int, int], ...]) -> str:
    """Digest of a carrier segment with the used carriers' LSBs cleared."""
    normalized = {index: decoded.copy() for index, decoded in segment.slices.items()}
    for position in positions:
        unit_index, mb_index, block_id, index = segment.locator[position]
        block = _block_list(normalized[unit_index].macroblocks[mb_index], block_id)
        value = block[index]
        magnitude = abs(value) & ~1
        block[index] = magnitude if value > 0 else -magnitude
    digest = hashlib.sha256(_SEGMENT_DOMAIN)
    digest.update(struct.pack(">I", len(segment.units)))
    for index, unit in enumerate(segment.units):
        if index in normalized:
            kind, body = 1, encode_slice(normalized[index])
        else:
            kind, body = 0, unit.nal
        digest.update(struct.pack(">I", len(unit.prefix)) + unit.prefix)
        digest.update(struct.pack(">BQ", kind, len(body)) + body)
    return digest.hexdigest()


def raw_segment_digest(data: bytes) -> str:
    return hashlib.sha256(_RAW_SEGMENT_DOMAIN + struct.pack(">Q", len(data)) + data).hexdigest()


def _hash_positions(positions) -> str:
    from ..core.carrier_gate import hash_positions

    return hash_positions([list(position) for position in positions])


# --- segmentation ------------------------------------------------------------------

def _prepare(video_path: str | Path, temp_dir: str, frames_per_segment: int, ffmpeg: str,
             ffprobe: str, gop_policy: str, progress_callback: ProgressCallback | None,
             phase: str) -> tuple[list[Path], list[int], list[SegmentStructure]]:
    from .blind_sync_streaming import _split_video_into_segments

    _positive("frames_per_segment", frames_per_segment)
    segments, frame_counts = _split_video_into_segments(
        video_path, temp_dir, frames_per_segment, ffmpeg=ffmpeg, ffprobe=ffprobe,
        digest_policy=DIGEST_V2,  # pins the access-unit partition (SEGMENTATION_RULE_V2)
    )
    structures = []
    for index, (segment, frame_count) in enumerate(zip(segments, frame_counts, strict=True)):
        try:
            structure = inspect_cabac_segment(segment.read_bytes(), gop_policy)
        except ValueError as error:
            raise ValueError(f"H.264 segment {index}: {error}") from None
        if structure.pictures != frame_count:
            raise ValueError(
                f"H.264 segment {index}: {structure.pictures} coded pictures but {frame_count} decoded frames"
            )
        structures.append(structure)
    _emit(progress_callback, phase, "segments_ready", segments_total=len(segments),
          frames_total=sum(frame_counts))
    return segments, frame_counts, structures


def _source(path: str | Path, name: str) -> Path:
    source = Path(path).resolve(strict=True)
    if not source.is_file():
        raise ValueError(f"{name} must identify a regular file")
    return source


def _output(output_path: str | Path, source: Path) -> Path:
    output = Path(output_path).resolve()
    if source == output:
        raise ValueError("output video must differ from input video")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"output video already exists: {output}")
    if not output.parent.is_dir():
        raise FileNotFoundError("output video directory does not exist")
    return output


def _finish(output_segments: list[bytes], temp_dir: Path, output: Path) -> None:
    from ..core.carrier_gate import strict_validate_h264_decode

    candidate = temp_dir / "candidate.h264"
    with candidate.open("xb") as stream:
        for data in output_segments:
            stream.write(data)
    strict_validate_h264_decode(str(candidate))
    try:
        os.link(candidate, output)
    except FileExistsError:
        raise FileExistsError(f"output video appeared during embedding: {output}") from None


def _combine(digests: list[tuple[int, int, str]], frames_per_segment: int, carrier_segments: int) -> str:
    rule = SEGMENTATION_RULE_V2.encode("ascii")
    digest = hashlib.sha256(_COMBINED_DOMAIN + struct.pack(">H", len(rule)) + rule)
    digest.update(struct.pack(">III", frames_per_segment, len(digests), carrier_segments))
    for index, (frame_count, kind, value) in enumerate(digests):
        digest.update(struct.pack(">IIB", index, frame_count, kind) + bytes.fromhex(value))
    return digest.hexdigest()


def _globalize(positions, slot_offset: int, per_picture: int) -> list[tuple[int, int, int]]:
    return [(mb + slot_offset * per_picture, block, coefficient) for mb, block, coefficient in positions]


# --- fixed-chunk transport (``video_pipeline.Transport``) ----------------------------

@dataclass(frozen=True)
class ChunkedVideoContext:
    positions_hash: str
    canonical_video_sha256: str
    global_positions: tuple[tuple[int, int, int], ...]
    segments_used: int
    frames_per_segment: int


@dataclass(frozen=True)
class ChunkedVideoEmbedResult:
    output_path: str
    payload_bytes: int
    segments_used: int
    carriers_used: int
    carriers_changed: int = 0


@dataclass(frozen=True)
class ChunkedVideoPayloadResult:
    payload: bytes
    segments_used: int
    carriers_used: int
    positions_hash: str
    canonical_video_sha256: str
    global_positions: tuple[tuple[int, int, int], ...]
    chunks: tuple[bytes, ...] = ()


@_reject_malformed
def derive_chunked_video_context(
    video_path: str | Path, chunks: list[bytes], sync_key: bytes, contract: Any, *,
    frames_per_segment: int = DEFAULT_STREAM_SEGMENT_FRAMES, ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe", progress_callback: ProgressCallback | None = None,
    gop_policy: str = ALL_INTRA, digest_policy: str = DIGEST_CABAC_V1,
) -> ChunkedVideoContext:
    """Carrier positions and the bound digest the given chunks will have (cover side)."""
    _require_digest(digest_policy)
    contract = _require_contract(contract)
    _require_key(sync_key)
    source = _source(video_path, "video_path")
    if not isinstance(chunks, list) or not chunks:
        raise ValueError("at least one payload chunk is required")
    assemble_payload_chunks(chunks)
    from .blind_sync import pack_blind_payload

    with tempfile.TemporaryDirectory(prefix="zkstego-cabac-context-") as temp_name:
        segments, frame_counts, structures = _prepare(
            source, temp_name, frames_per_segment, ffmpeg, ffprobe, gop_policy,
            progress_callback, "carrier_context",
        )
        if len(chunks) > len(segments):
            raise ValueError(f"payload requires {len(chunks)} segments, video has {len(segments)}")
        global_positions: list[tuple[int, int, int]] = []
        digests: list[tuple[int, int, str]] = []
        slot_offset = 0
        for index, (path, frame_count) in enumerate(zip(segments, frame_counts, strict=True)):
            data = path.read_bytes()
            if index < len(chunks):
                segment = _analyze(data, contract, gop_policy)
                required = len(pack_blind_payload(chunks[index])) * 8
                order = _ordered(segment, sync_key, contract)
                if len(order) < required:
                    raise ValueError(
                        f"segment {index} has insufficient CABAC carriers: need {required}, got {len(order)}"
                    )
                used = tuple(order[:required])
                digests.append((frame_count, 1, _carrier_segment_digest(segment, used)))
                global_positions.extend(_globalize(used, slot_offset, segment.geometry.mbs_per_picture))
            else:
                digests.append((frame_count, 0, raw_segment_digest(data)))
            slot_offset += structures[index].coded_slices
            _emit(progress_callback, "carrier_context", "segment_completed", segment_index=index)
    return ChunkedVideoContext(
        positions_hash=_hash_positions(global_positions),
        canonical_video_sha256=_combine(digests, frames_per_segment, len(chunks)),
        global_positions=tuple(global_positions),
        segments_used=len(chunks),
        frames_per_segment=frames_per_segment,
    )


@_reject_malformed
def embed_chunked_video_payload(
    cover_video_path: str | Path, output_video_path: str | Path, payload: bytes, sync_key: bytes,
    contract: Any, *, frames_per_segment: int = DEFAULT_STREAM_SEGMENT_FRAMES,
    chunk_size: int = DEFAULT_STREAM_CHUNK_BYTES, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
    progress_callback: ProgressCallback | None = None, gop_policy: str = ALL_INTRA,
    digest_policy: str = DIGEST_CABAC_V1,
) -> ChunkedVideoEmbedResult:
    """Embed ZKBC v1 chunks; only IDR slices of carrier segments are re-encoded."""
    _require_digest(digest_policy)
    contract = _require_contract(contract)
    _require_key(sync_key)
    source = _source(cover_video_path, "cover_video_path")
    output = _output(output_video_path, source)
    chunks = pack_payload_chunks(payload, chunk_size=chunk_size)
    with tempfile.TemporaryDirectory(prefix="zkstego-cabac-", dir=output.parent) as temp_name:
        segments, _frame_counts, _structures = _prepare(
            source, temp_name, frames_per_segment, ffmpeg, ffprobe, gop_policy,
            progress_callback, "embed",
        )
        if len(chunks) > len(segments):
            raise ValueError(f"payload requires {len(chunks)} segments, video has {len(segments)}")
        outputs: list[bytes] = []
        used = changed = 0
        for index, path in enumerate(segments):
            data = path.read_bytes()
            if index < len(chunks):
                data, carriers, flips = _embed_segment(data, chunks[index], sync_key, contract, gop_policy)
                used += carriers
                changed += flips
            outputs.append(data)
            _emit(progress_callback, "embed", "segment_completed", segment_index=index)
        _finish(outputs, Path(temp_name), output)
    return ChunkedVideoEmbedResult(str(output), len(payload), len(chunks), used, changed)


@_reject_malformed
def extract_chunked_video_payload(
    video_path: str | Path, sync_key: bytes, contract: Any, *,
    frames_per_segment: int = DEFAULT_STREAM_SEGMENT_FRAMES, ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe", progress_callback: ProgressCallback | None = None,
    gop_policy: str = ALL_INTRA, digest_policy: str = DIGEST_CABAC_V1,
) -> ChunkedVideoPayloadResult:
    """Blind-extract ordered chunks from the stego video alone and recompute the digest."""
    _require_digest(digest_policy)
    contract = _require_contract(contract)
    _require_key(sync_key)
    source = _source(video_path, "video_path")
    with tempfile.TemporaryDirectory(prefix="zkstego-cabac-extract-") as temp_name:
        segments, frame_counts, structures = _prepare(
            source, temp_name, frames_per_segment, ffmpeg, ffprobe, gop_policy,
            progress_callback, "extract",
        )
        pieces: list[bytes] = []
        expected: int | None = None
        global_positions: list[tuple[int, int, int]] = []
        digests: list[tuple[int, int, str]] = []
        used = 0
        slot_offset = 0
        for index, (path, frame_count) in enumerate(zip(segments, frame_counts, strict=True)):
            data = path.read_bytes()
            if expected is not None and len(pieces) >= expected:
                digests.append((frame_count, 0, raw_segment_digest(data)))
            else:
                segment = _analyze(data, contract, gop_policy)
                piece, positions = _extract_segment(data, sync_key, contract, gop_policy, segment)
                count = payload_chunk_count(piece)
                if expected is None:
                    expected = count
                    if count > len(segments):
                        raise ValueError("payload declares more chunks than the video has segments")
                elif count != expected:
                    raise ValueError("chunk count changes between video segments")
                pieces.append(piece)
                used += len(positions)
                digests.append((frame_count, 1, _carrier_segment_digest(segment, positions)))
                global_positions.extend(_globalize(positions, slot_offset, segment.geometry.mbs_per_picture))
            slot_offset += structures[index].coded_slices
            _emit(progress_callback, "extract", "segment_completed", segment_index=index)
    if expected is None or len(pieces) != expected:
        raise ValueError("video ended before all declared payload chunks were extracted")
    return ChunkedVideoPayloadResult(
        payload=assemble_payload_chunks(pieces),
        segments_used=len(pieces),
        carriers_used=used,
        positions_hash=_hash_positions(global_positions),
        canonical_video_sha256=_combine(digests, frames_per_segment, len(pieces)),
        global_positions=tuple(global_positions),
        chunks=tuple(pieces),
    )


# --- capacity-adaptive transport (``video_pipeline.AdaptiveTransport``) --------------

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
    carriers_changed: int = 0


@dataclass(frozen=True)
class AdaptiveVideoPayloadResult:
    payload: bytes
    segments_used: int
    carriers_used: int
    positions_hash: str
    canonical_video_sha256: str
    global_positions: tuple[tuple[int, int, int], ...]
    chunks: tuple[bytes, ...]
    segment_capacity_bits: tuple[int, ...]
    layout: tuple[ChunkSlot, ...]


def combine_adaptive_segment_digests(records: list[SegmentRecord], frames_per_segment: int,
                                     plan: AdaptiveChunkPlan, payload_bytes: int) -> str:
    rule = SEGMENTATION_RULE_V2.encode("ascii")
    digest = hashlib.sha256(_ADAPTIVE_DOMAIN + struct.pack(">H", len(rule)) + rule)
    digest.update(plan.plan_id())
    digest.update(struct.pack(">III", frames_per_segment, payload_bytes, len(records)))
    for expected, record in enumerate(records):
        if record.index != expected:
            raise ValueError("segment records are not in index order")
        digest.update(struct.pack(">IIBQI", record.index, record.frame_count, record.role,
                                  record.capacity_bits, record.chunk_bytes))
        digest.update(bytes.fromhex(record.digest))
    return digest.hexdigest()


@dataclass
class _Walk:
    chunks: list[bytes]
    layout: list[ChunkSlot]
    capacities: list[int]
    records: list[SegmentRecord]
    global_positions: list[tuple[int, int, int]]
    outputs: list[bytes]
    carriers_used: int
    carriers_changed: int
    payload: bytes


def _adaptive_walk(segments: list[Path], frame_counts: list[int], structures: list[SegmentStructure], *,
                   payload: bytes | None, payload_bytes: int | None, plan: AdaptiveChunkPlan,
                   sync_key: bytes, contract: CabacMagnitudeContract, gop_policy: str, mode: str,
                   expected_layout: tuple[ChunkSlot, ...] | None,
                   progress_callback: ProgressCallback | None) -> _Walk:
    """Greedy plan over segments; ``mode`` is ``context``, ``embed`` or ``extract``."""
    from .blind_sync import pack_blind_payload

    total = payload_bytes if payload is None else len(payload)
    total_crc = None if payload is None else payload_crc(payload)
    offset = 0
    walk = _Walk([], [], [], [], [], [], 0, 0, b"")
    slot_offset = 0
    for index, (path, frame_count) in enumerate(zip(segments, frame_counts, strict=True)):
        data = path.read_bytes()
        coded = structures[index].coded_slices
        if total is not None and offset == total:
            walk.records.append(SegmentRecord(index, frame_count, ROLE_UNUSED, 0, 0, raw_segment_digest(data)))
            walk.outputs.append(data)
            slot_offset += coded
            continue
        segment = _analyze(data, contract, gop_policy)
        capacity = len(segment.candidates)
        walk.capacities.append(capacity)
        usable = plan.chunk_capacity_bytes(capacity)
        if usable == 0:
            walk.records.append(SegmentRecord(index, frame_count, ROLE_SKIPPED, capacity, 0,
                                              raw_segment_digest(data)))
            walk.outputs.append(data)
            slot_offset += coded
            continue
        if index > MAX_SEGMENT_INDEX or len(walk.layout) > MAX_CHUNK_INDEX:
            raise ValueError("adaptive plan exceeds the segment or chunk index range")
        if mode == "extract":
            chunk, positions = _extract_segment(data, sync_key, contract, gop_policy, segment)
            header = parse_adaptive_chunk(chunk)
            if total is None:
                total = header.total_size
            if total_crc is None:
                total_crc = header.total_crc
            planned = min(total - offset, usable)
            expected = (len(walk.layout), index, total, offset, total_crc)
            actual = (header.chunk_index, header.segment_index, header.total_size, header.offset,
                      header.total_crc)
            if actual != expected or len(header.part) != planned:
                raise ValueError(f"segment {index}: chunk does not match the adaptive plan")
            output = data
        else:
            planned = min(total - offset, usable)
            slot = ChunkSlot(len(walk.layout), index, offset, planned)
            if expected_layout is not None and (
                slot.chunk_index >= len(expected_layout) or expected_layout[slot.chunk_index] != slot
            ):
                raise RuntimeError(f"segment {index}: recomputed plan differs from the derived layout")
            chunk = encode_adaptive_chunk(payload, slot, total_crc)
            if mode == "embed":
                output, used, flips = _embed_segment(data, chunk, sync_key, contract, gop_policy)
                walk.carriers_changed += flips
                positions = ()
                walk.carriers_used += used
            else:
                required = len(pack_blind_payload(chunk)) * 8
                order = _ordered(segment, sync_key, contract)
                if len(order) < required:
                    raise ValueError(f"segment {index} has insufficient CABAC carriers")
                positions = tuple(order[:required])
                output = data
        if mode != "embed":
            walk.carriers_used += len(positions)
            digest = _carrier_segment_digest(segment, positions)
            walk.global_positions.extend(_globalize(positions, slot_offset, segment.geometry.mbs_per_picture))
        else:
            digest = ""
        walk.chunks.append(chunk)
        walk.layout.append(ChunkSlot(len(walk.layout), index, offset, planned))
        walk.records.append(SegmentRecord(index, frame_count, ROLE_CARRIER, capacity, planned, digest))
        walk.outputs.append(output)
        offset += planned
        slot_offset += coded
        _emit(progress_callback, mode, "segment_completed", segment_index=index, capacity_bits=capacity)
    if total is None or offset != total:
        missing = "all" if total is None else f"{total - offset} of {total}"
        raise ValueError(
            f"carrier capacity is insufficient for the adaptive plan: {missing} payload bytes "
            "did not fit the video's segments"
        )
    walk.payload = b"".join(chunk[CHUNK_HEADER.size:] for chunk in walk.chunks)
    if payload_crc(walk.payload) != total_crc:
        raise ValueError("assembled payload checksum mismatch")
    return walk


def _require_plan(plan: Any) -> AdaptiveChunkPlan:
    if not isinstance(plan, AdaptiveChunkPlan):
        raise TypeError("plan must be an AdaptiveChunkPlan")
    return plan


@_reject_malformed
def derive_adaptive_video_context(
    video_path: str | Path, payload: bytes, sync_key: bytes, contract: Any, *,
    plan: AdaptiveChunkPlan, frames_per_segment: int = DEFAULT_STREAM_SEGMENT_FRAMES,
    ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
    progress_callback: ProgressCallback | None = None, gop_policy: str = ALL_INTRA,
    digest_policy: str = DIGEST_CABAC_V1,
) -> AdaptiveVideoContext:
    _require_digest(digest_policy)
    contract = _require_contract(contract)
    _require_key(sync_key)
    plan = _require_plan(plan)
    if not isinstance(payload, bytes) or not payload:
        raise ValueError("payload must be non-empty bytes")
    source = _source(video_path, "video_path")
    with tempfile.TemporaryDirectory(prefix="zkstego-cabac-adaptive-context-") as temp_name:
        segments, frame_counts, structures = _prepare(
            source, temp_name, frames_per_segment, ffmpeg, ffprobe, gop_policy,
            progress_callback, "carrier_context",
        )
        walk = _adaptive_walk(segments, frame_counts, structures, payload=payload, payload_bytes=None,
                              plan=plan, sync_key=sync_key, contract=contract, gop_policy=gop_policy,
                              mode="context", expected_layout=None, progress_callback=progress_callback)
    return AdaptiveVideoContext(
        positions_hash=_hash_positions(walk.global_positions),
        canonical_video_sha256=combine_adaptive_segment_digests(
            walk.records, frames_per_segment, plan, len(payload)),
        global_positions=tuple(walk.global_positions),
        segments_used=len(walk.layout),
        frames_per_segment=frames_per_segment,
        segment_capacity_bits=tuple(walk.capacities),
        layout=tuple(walk.layout),
    )


@_reject_malformed
def embed_adaptive_video_payload(
    cover_video_path: str | Path, output_video_path: str | Path, payload: bytes, sync_key: bytes,
    contract: Any, *, plan: AdaptiveChunkPlan, expected_layout: tuple[ChunkSlot, ...] | None = None,
    frames_per_segment: int = DEFAULT_STREAM_SEGMENT_FRAMES, ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe", progress_callback: ProgressCallback | None = None,
    gop_policy: str = ALL_INTRA, digest_policy: str = DIGEST_CABAC_V1,
) -> AdaptiveVideoEmbedResult:
    _require_digest(digest_policy)
    contract = _require_contract(contract)
    _require_key(sync_key)
    plan = _require_plan(plan)
    if not isinstance(payload, bytes) or not payload:
        raise ValueError("payload must be non-empty bytes")
    source = _source(cover_video_path, "cover_video_path")
    output = _output(output_video_path, source)
    with tempfile.TemporaryDirectory(prefix="zkstego-cabac-adaptive-", dir=output.parent) as temp_name:
        segments, frame_counts, structures = _prepare(
            source, temp_name, frames_per_segment, ffmpeg, ffprobe, gop_policy,
            progress_callback, "embed",
        )
        walk = _adaptive_walk(segments, frame_counts, structures, payload=payload, payload_bytes=None,
                              plan=plan, sync_key=sync_key, contract=contract, gop_policy=gop_policy,
                              mode="embed", expected_layout=expected_layout,
                              progress_callback=progress_callback)
        if expected_layout is not None and tuple(walk.layout) != tuple(expected_layout):
            raise RuntimeError("recomputed plan differs from the derived layout")
        _finish(walk.outputs, Path(temp_name), output)
    return AdaptiveVideoEmbedResult(
        output_path=str(output), payload_bytes=len(payload), segments_used=len(walk.layout),
        carriers_used=walk.carriers_used, segment_capacity_bits=tuple(walk.capacities),
        layout=tuple(walk.layout), carriers_changed=walk.carriers_changed,
    )


@_reject_malformed
def extract_adaptive_video_payload(
    video_path: str | Path, sync_key: bytes, contract: Any, *, plan: AdaptiveChunkPlan,
    payload_bytes: int | None = None, frames_per_segment: int = DEFAULT_STREAM_SEGMENT_FRAMES,
    ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
    progress_callback: ProgressCallback | None = None, gop_policy: str = ALL_INTRA,
    digest_policy: str = DIGEST_CABAC_V1,
) -> AdaptiveVideoPayloadResult:
    _require_digest(digest_policy)
    contract = _require_contract(contract)
    _require_key(sync_key)
    plan = _require_plan(plan)
    if payload_bytes is not None:
        _positive("payload_bytes", payload_bytes)
    source = _source(video_path, "video_path")
    with tempfile.TemporaryDirectory(prefix="zkstego-cabac-adaptive-extract-") as temp_name:
        segments, frame_counts, structures = _prepare(
            source, temp_name, frames_per_segment, ffmpeg, ffprobe, gop_policy,
            progress_callback, "extract",
        )
        walk = _adaptive_walk(segments, frame_counts, structures, payload=None, payload_bytes=payload_bytes,
                              plan=plan, sync_key=sync_key, contract=contract, gop_policy=gop_policy,
                              mode="extract", expected_layout=None, progress_callback=progress_callback)
    if plan_layout(len(walk.payload), walk.capacities, plan) != tuple(walk.layout):
        raise ValueError("extracted layout differs from the plan of the recomputed capacities")
    return AdaptiveVideoPayloadResult(
        payload=walk.payload,
        segments_used=len(walk.layout),
        carriers_used=walk.carriers_used,
        positions_hash=_hash_positions(walk.global_positions),
        canonical_video_sha256=combine_adaptive_segment_digests(
            walk.records, frames_per_segment, plan, len(walk.payload)),
        global_positions=tuple(walk.global_positions),
        chunks=tuple(walk.chunks),
        segment_capacity_bits=tuple(walk.capacities),
        layout=tuple(walk.layout),
    )
