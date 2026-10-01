"""Canonical coefficient transformations for H.264 carrier commitments.

This module only normalizes carrier coefficients. It does not by itself
define a complete video commitment or prove that carrier positions came from
an authenticated source; callers must bind the ordered positions separately.
"""

from __future__ import annotations

import hashlib
import struct
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal


CoefficientBlock = tuple[int, int, Sequence[int]]
CarrierPosition = tuple[int, int, int]
ModifiedBlock = tuple[int, int, list[int]]
MagnitudePair = Literal["even_down", "native_odd_anchor_v1"]


def canonicalize_carrier_coefficients(
    coefficients: Sequence[CoefficientBlock],
    carrier_positions: Sequence[CarrierPosition],
    *,
    magnitude_pair: MagnitudePair = "even_down",
) -> list[ModifiedBlock]:
    """Return only coefficient blocks changed by canonicalizing carriers.

    Non-negative carrier indexes identify magnitude-LSB carriers. The legacy
    ``even_down`` profile rounds magnitude down to even (with unit magnitude
    mapped to two). ``native_odd_anchor_v1`` maps the disjoint eligible pairs
    (5, 6), (7, 8), ... to their odd member, preserving sign. Negative
    indexes encode trailing-one sign carriers using ``~index`` and normalize
    to positive one. The supplied coefficient structures are never mutated.

    The returned block tuples can be passed directly to
    ``BitstreamReconstructor.reconstruct_video``. Callers still need the
    original frame/parser context to produce a canonicalized bitstream.
    """
    coefficient_lookup: dict[tuple[int, int], Sequence[int]] = {}
    if magnitude_pair not in ("even_down", "native_odd_anchor_v1"):
        raise ValueError("unknown magnitude pair profile")
    for item in coefficients:
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            raise ValueError("coefficient entries must be (macroblock, block, levels)")
        macroblock, block, levels = item
        if (
            isinstance(macroblock, bool)
            or not isinstance(macroblock, int)
            or isinstance(block, bool)
            or not isinstance(block, int)
            or not isinstance(levels, Sequence)
        ):
            raise ValueError("coefficient entry has invalid indexes or levels")
        key = (macroblock, block)
        if key in coefficient_lookup:
            raise ValueError(f"duplicate coefficient block: {key}")
        coefficient_lookup[key] = levels

    normalized_by_block: dict[tuple[int, int], list[int]] = {}
    seen_carriers: set[tuple[int, int, int]] = set()
    for item in carrier_positions:
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            raise ValueError("carrier positions must be (macroblock, block, coefficient)")
        macroblock, block, carrier_index = item
        if (
            isinstance(macroblock, bool)
            or not isinstance(macroblock, int)
            or isinstance(block, bool)
            or not isinstance(block, int)
            or isinstance(carrier_index, bool)
            or not isinstance(carrier_index, int)
        ):
            raise ValueError("carrier position indexes must be integers")
        position = (macroblock, block, carrier_index)
        if position in seen_carriers:
            raise ValueError(f"duplicate carrier position: {position}")
        seen_carriers.add(position)

        key = (macroblock, block)
        levels = coefficient_lookup.get(key)
        if levels is None:
            raise ValueError(f"unknown coefficient block: {key}")
        coefficient_index = ~carrier_index if carrier_index < 0 else carrier_index
        if not 0 <= coefficient_index < len(levels):
            raise ValueError(f"carrier coefficient index is out of range: {position}")

        value = levels[coefficient_index]
        if isinstance(value, bool) or not isinstance(value, int) or value == 0:
            raise ValueError(f"carrier coefficient must be a non-zero integer: {position}")
        if carrier_index < 0:
            if abs(value) != 1:
                raise ValueError(f"sign carrier must be a trailing one: {position}")
            canonical_value = 1
        else:
            magnitude = abs(value)
            if magnitude_pair == "native_odd_anchor_v1":
                if magnitude < 5:
                    raise ValueError(f"native pair carrier is below magnitude five: {position}")
                magnitude = magnitude if magnitude & 1 else magnitude - 1
            else:
                magnitude &= ~1
                if magnitude == 0:
                    magnitude = 2
            canonical_value = magnitude if value > 0 else -magnitude

        if canonical_value == value:
            continue
        normalized = normalized_by_block.get(key)
        if normalized is None:
            normalized = list(levels)
            normalized_by_block[key] = normalized
        normalized[coefficient_index] = canonical_value

    return [
        (macroblock, block, levels)
        for (macroblock, block), levels in sorted(normalized_by_block.items())
    ]


def canonical_video_sha256(
    video_path: str | Path,
    carrier_positions: Sequence[CarrierPosition],
    *,
    parser: Any | None = None,
    frame_verified_data: Mapping[int, tuple[dict, dict, bytes]] | None = None,
    magnitude_pair: MagnitudePair = "even_down",
) -> str:
    """Hash the carrier-normalized H.264 syntax without re-encoding slices.

    Carrier locations must be supplied in the same global macroblock/block
    coordinate system used by the embedder. Non-carrier NAL/RBSP bits are
    committed verbatim. Each luma residual block containing a carrier is
    represented by its canonicalized coefficient vector instead of its
    variable-length CAVLC codeword. The source video is never modified.
    """
    source = Path(video_path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError("video_path must identify a regular file")

    def digest_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    if (parser is None) != (frame_verified_data is None):
        raise ValueError("parser and frame_verified_data must be provided together")
    if magnitude_pair not in ("even_down", "native_odd_anchor_v1"):
        raise ValueError("unknown magnitude pair profile")

    if not carrier_positions:
        return digest_file(source)

    if parser is None:
        from .bitstream.bitstream_ops import BitstreamReconstructor
        from .bitstream.h264 import H264BitstreamParser
        from .core.pipeline import extract_all_idr_blocks

        parser = H264BitstreamParser(str(source))
        parser.parse()
        _, frame_data, _, _, _ = extract_all_idr_blocks(
            str(source), BitstreamReconstructor(), parser=parser
        )
    else:
        frame_data = frame_verified_data
    if magnitude_pair == "even_down":
        return canonical_h264_digest(parser.nal_units, frame_data, carrier_positions)
    return canonical_h264_digest(
        parser.nal_units, frame_data, carrier_positions,
        magnitude_pair=magnitude_pair,
    )


def canonical_h264_digest(
    nal_units: Sequence[Any],
    frame_verified_data: Mapping[int, tuple[dict, dict, bytes]],
    carrier_positions: Sequence[CarrierPosition],
    *,
    magnitude_pair: MagnitudePair = "even_down",
) -> str:
    """Hash parsed NALs while replacing carrier-containing residual blocks.

    The representation is length-delimited and domain-separated. It preserves
    all non-carrier RBSP bits exactly while serializing complete affected
    coefficient blocks as signed 64-bit values. Thus a different CAVLC
    codeword length for the normalized carrier does not shift or invalidate
    later syntax bits.
    """
    from .bitstream.bitstream_ops import BitArray

    positions = list(carrier_positions)
    if len(set(tuple(position) for position in positions)) != len(positions):
        raise ValueError("duplicate carrier position")

    frame_offsets = sorted(frame_verified_data)
    frame_positions: dict[int, list[CarrierPosition]] = {offset: [] for offset in frame_offsets}
    # Parsed global macroblock ranges must be disjoint. Once checked, binary
    # search maps each carrier to one IDR instead of scanning every carrier in
    # every frame (which is prohibitive for a proof-sized payload).
    for index, offset in enumerate(frame_offsets):
        next_offset = frame_offsets[index + 1] if index + 1 < len(frame_offsets) else None
        _, frame_blocks, _ = frame_verified_data[offset]
        if any(
            macroblock < offset or (next_offset is not None and macroblock >= next_offset)
            for macroblock, _ in frame_blocks
        ):
            raise ValueError(f"IDR block range overlaps another frame: {offset}")
    missing_positions: set[CarrierPosition] = set()
    for position in positions:
        index = bisect_right(frame_offsets, position[0]) - 1
        if index < 0:
            missing_positions.add(position)
            continue
        offset = frame_offsets[index]
        _, frame_blocks, _ = frame_verified_data[offset]
        if (position[0], position[1]) not in frame_blocks:
            missing_positions.add(position)
            continue
        frame_positions[offset].append(position)
    if missing_positions:
        raise ValueError(f"carrier position is absent from parsed IDR blocks: {sorted(missing_positions)}")

    if magnitude_pair == "native_odd_anchor_v1":
        domain = b"zkstego/canonical-h264-carrier-normalization/native-odd-anchor-v1\x00"
    elif magnitude_pair == "even_down":
        domain = b"zkstego/canonical-h264-carrier-normalization/v1\x00"
    else:
        raise ValueError("unknown magnitude pair profile")
    digest = hashlib.sha256(domain)
    nal_index = 0
    idr_index = 0
    for nal in nal_units:
        nal_type = int(nal.nal_unit_type)
        digest.update(b"NAL\x00")
        digest.update(
            struct.pack(
                ">QBBBB",
                nal_index,
                nal_type,
                int(nal.forbidden_zero_bit),
                int(nal.nal_ref_idc),
                int(nal.start_code_size),
            )
        )
        nal_index += 1
        if nal_type != 5:
            raw_rbsp = bytes(nal.rbsp_byte)
            digest.update(b"RAW\x00" + struct.pack(">Q", len(raw_rbsp)) + raw_rbsp)
            continue

        if idr_index >= len(frame_offsets):
            raise ValueError("more IDR NAL units than parsed IDR frame data")
        frame_offset = frame_offsets[idr_index]
        idr_index += 1
        offsets, frame_blocks, frame_rbsp = frame_verified_data[frame_offset]
        if bytes(nal.rbsp_byte) != bytes(frame_rbsp):
            raise ValueError("IDR NAL does not match its parsed frame data")
        current_positions = frame_positions[frame_offset]
        if not current_positions:
            raw_rbsp = bytes(nal.rbsp_byte)
            digest.update(b"RAW\x00" + struct.pack(">Q", len(raw_rbsp)) + raw_rbsp)
            continue

        normalization = canonicalize_carrier_coefficients(
            [(mb, block, levels) for (mb, block), levels in frame_blocks.items()],
            current_positions,
            magnitude_pair=magnitude_pair,
        )
        normalized_blocks = {
            (mb, block): levels for mb, block, levels in normalization
        }
        affected_keys = sorted({(mb, block) for mb, block, _ in current_positions})
        bitstream = BitArray(bytes(nal.rbsp_byte))
        syntax_end = _rbsp_syntax_bit_length(bytes(nal.rbsp_byte))
        cursor = 0
        for key in sorted(affected_keys, key=lambda block_key: offsets.get(block_key, {}).get("start_bit", -1)):
            block_offset = offsets.get(key)
            if not isinstance(block_offset, dict):
                raise ValueError(f"carrier block has no CAVLC bit range: {key}")
            start = block_offset.get("start_bit")
            end = block_offset.get("end_bit")
            if (
                isinstance(start, bool)
                or not isinstance(start, int)
                or isinstance(end, bool)
                or not isinstance(end, int)
                or not cursor <= start < end <= syntax_end
            ):
                raise ValueError(f"carrier block has an invalid CAVLC bit range: {key}")
            _update_raw_bit_segment(digest, bitstream, cursor, start)
            levels = normalized_blocks.get(key, frame_blocks[key])
            digest.update(b"BLOCK\x00" + struct.pack(">QII", key[0], key[1], len(levels)))
            for level in levels:
                if isinstance(level, bool) or not isinstance(level, int):
                    raise ValueError(f"carrier block contains a non-integer coefficient: {key}")
                digest.update(struct.pack(">q", level))
            cursor = end
        _update_raw_bit_segment(digest, bitstream, cursor, syntax_end)

    if idr_index != len(frame_offsets):
        raise ValueError("parsed IDR frame data does not match the NAL stream")
    return digest.hexdigest()


def _rbsp_syntax_bit_length(rbsp: bytes) -> int:
    """Return the position after the RBSP stop bit, excluding alignment zeros."""
    for byte_index in range(len(rbsp) - 1, -1, -1):
        value = rbsp[byte_index]
        if value:
            trailing_zero_count = (value & -value).bit_length() - 1
            return byte_index * 8 + 8 - trailing_zero_count
    raise ValueError("RBSP contains no stop bit")


def _update_raw_bit_segment(digest: Any, bitstream: Any, start: int, end: int) -> None:
    """Add one length-delimited packed raw RBSP segment to a digest."""
    import numpy as np

    bits = bitstream[start:end]
    digest.update(b"BITS\x00" + struct.pack(">Q", end - start))
    if bits:
        digest.update(np.packbits(np.asarray(bits, dtype=np.uint8)).tobytes())
