"""Strict chunk framing for payloads distributed across video segments."""

from __future__ import annotations

import math
import struct
import zlib
from collections.abc import Sequence

CHUNK_MAGIC = b"ZKBC"
CHUNK_VERSION = 1
CHUNK_HEADER = struct.Struct(">4sBHHI HII")
MAX_CHUNKED_PAYLOAD_BYTES = 16 * 1024 * 1024
MAX_CHUNK_COUNT = 65_535
MAX_CHUNK_BYTES = 65_535


def payload_chunk_count(chunk: bytes) -> int:
    """Validate one piece and return the declared number of video segments."""
    if not isinstance(chunk, bytes):
        raise TypeError("chunk must be bytes")
    if len(chunk) <= CHUNK_HEADER.size:
        raise ValueError("chunk is truncated or has an empty body")
    magic, version, index, count, total_size, chunk_size, _, part_crc = (
        CHUNK_HEADER.unpack_from(chunk)
    )
    if magic != CHUNK_MAGIC or version != CHUNK_VERSION:
        raise ValueError("chunk magic or version is unsupported")
    if count == 0 or index >= count:
        raise ValueError("chunk index or count is invalid")
    if total_size == 0 or total_size > MAX_CHUNKED_PAYLOAD_BYTES:
        raise ValueError("declared payload size is invalid")
    if chunk_size == 0 or chunk_size > MAX_CHUNK_BYTES:
        raise ValueError("declared chunk size is invalid")
    expected_count = math.ceil(total_size / chunk_size)
    expected_part_size = (
        chunk_size if index < expected_count - 1 else total_size - chunk_size * index
    )
    part = chunk[CHUNK_HEADER.size :]
    if count != expected_count or len(part) != expected_part_size:
        raise ValueError("chunk length or declared count is inconsistent")
    if zlib.crc32(part) & 0xFFFFFFFF != part_crc:
        raise ValueError(f"chunk {index} checksum mismatch")
    return count


def pack_payload_chunks(payload: bytes, *, chunk_size: int) -> list[bytes]:
    """Frame a payload as ordered, checksummed chunks for separate carriers."""
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    if not payload:
        raise ValueError("payload must not be empty")
    if len(payload) > MAX_CHUNKED_PAYLOAD_BYTES:
        raise ValueError("payload exceeds the configured chunked limit")
    if (
        isinstance(chunk_size, bool)
        or not isinstance(chunk_size, int)
        or not 1 <= chunk_size <= MAX_CHUNK_BYTES
    ):
        raise ValueError(f"chunk_size must be between 1 and {MAX_CHUNK_BYTES}")

    count = math.ceil(len(payload) / chunk_size)
    if count > MAX_CHUNK_COUNT:
        raise ValueError("payload requires too many chunks")
    total_checksum = zlib.crc32(payload) & 0xFFFFFFFF
    chunks: list[bytes] = []
    for index in range(count):
        start = index * chunk_size
        part = payload[start : start + chunk_size]
        header = CHUNK_HEADER.pack(
            CHUNK_MAGIC,
            CHUNK_VERSION,
            index,
            count,
            len(payload),
            chunk_size,
            total_checksum,
            zlib.crc32(part) & 0xFFFFFFFF,
        )
        chunks.append(header + part)
    return chunks


def assemble_payload_chunks(chunks: Sequence[bytes]) -> bytes:
    """Validate and concatenate the complete ordered chunk set."""
    if not isinstance(chunks, Sequence) or isinstance(chunks, (bytes, bytearray)):
        raise TypeError("chunks must be a sequence of byte strings")
    if not chunks:
        raise ValueError("at least one payload chunk is required")

    parsed: list[tuple[tuple[int, int, int, int, int], bytes]] = []
    for chunk in chunks:
        if not isinstance(chunk, bytes):
            raise TypeError("each chunk must be bytes")
        if len(chunk) <= CHUNK_HEADER.size:
            raise ValueError("chunk is truncated or has an empty body")
        magic, version, index, count, total_size, chunk_size, total_crc, part_crc = (
            CHUNK_HEADER.unpack_from(chunk)
        )
        if magic != CHUNK_MAGIC or version != CHUNK_VERSION:
            raise ValueError("chunk magic or version is unsupported")
        if count == 0 or index >= count:
            raise ValueError("chunk index or count is invalid")
        if total_size == 0 or total_size > MAX_CHUNKED_PAYLOAD_BYTES:
            raise ValueError("declared payload size is invalid")
        if chunk_size == 0 or chunk_size > MAX_CHUNK_BYTES:
            raise ValueError("declared chunk size is invalid")

        part = chunk[CHUNK_HEADER.size :]
        expected_count = math.ceil(total_size / chunk_size)
        expected_part_size = (
            chunk_size if index < expected_count - 1 else total_size - chunk_size * index
        )
        if count != expected_count or len(part) != expected_part_size:
            raise ValueError("chunk length or declared count is inconsistent")
        if zlib.crc32(part) & 0xFFFFFFFF != part_crc:
            raise ValueError(f"chunk {index} checksum mismatch")
        parsed.append(((index, count, total_size, chunk_size, total_crc), part))

    first_metadata = parsed[0][0][1:]
    if len(parsed) != parsed[0][0][1]:
        raise ValueError("chunk count does not match the supplied set")
    parts: list[bytes] = []
    for expected_index, (metadata, part) in enumerate(parsed):
        index, count, total_size, chunk_size, total_crc = metadata
        if metadata[1:] != first_metadata:
            raise ValueError("chunk metadata differs within the set")
        if index != expected_index:
            raise ValueError("chunks are not in canonical index order")
        parts.append(part)

    payload = b"".join(parts)
    if len(payload) != total_size:
        raise ValueError("assembled payload length mismatch")
    if zlib.crc32(payload) & 0xFFFFFFFF != total_crc:
        raise ValueError("assembled payload checksum mismatch")
    return payload
