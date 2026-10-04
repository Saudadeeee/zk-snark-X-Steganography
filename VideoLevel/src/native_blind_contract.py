"""Shared Python specification for the native CAVLC blind channel, protocol v3.

This module deliberately contains no H.264 parsing or patching.  It is the
byte-for-byte contract that any Python adapter must satisfy before it can
interoperate with the native trailing-one-sign implementation. The locked
native deployment ABI is 64-bit ``size_t``; a 32-bit native target needs a
separate, versioned contract rather than silently narrowing identities.

Protocol v3 key schedule (RFC 5869 HKDF-SHA-256, one 32-byte stego key ``K``;
the labels are unchanged from v2, so schedules and keystreams equal v2)::

    PRK            = HMAC-SHA256(key = b"zkstego-cavlc-v2-salt", msg = K)
    schedule_key   = HKDF-Expand(PRK, b"zkstego/cavlc/v2/schedule", 32)
    whitening_key  = HKDF-Expand(PRK, b"zkstego/cavlc/v2/whitening", 32)

Schedule: ``score = HMAC-SHA256(schedule_key, identity)``, sorted by
``(score, identity)``.  Frame: ``[0x03][len BE16][payload]`` with no MAC: the
channel hides and locates the payload, and the Groth16 proof inside the payload
is what a verifier checks (v2 carried a 16-byte HMAC tag here).  Whitening:
keystream block ``j = HMAC-SHA256(whitening_key, uint64_be(j))``; the
embedded bit ``i`` (global across all IDR segments) is
``frame_bit[i] XOR keystream_bit[i]``, both MSB-first.

Segment protocol (the only channel protocol): every IDR NAL is one segment
(stored SPS/PPS + that IDR).  Segment ``s`` carries the frame bits
``[n, n + min(max_bits_per_idr, candidates_s))`` in its schedule order, where
``n`` counts the bits already carried by earlier segments.  Candidate
identities are relative to the codec's per-segment analysis input; the
``zkstego_inspect <video> --segments <max-bits-per-IDR>`` JSON ("segments-1")
lists them with their file location, and :func:`segment_schedule` reproduces
the native encoder's placements from it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, NamedTuple

HKDF_SALT = b"zkstego-cavlc-v2-salt"
SCHEDULE_INFO = b"zkstego/cavlc/v2/schedule"
WHITENING_INFO = b"zkstego/cavlc/v2/whitening"
SUBKEY_BYTES = 32
FRAME_VERSION = 3
FRAME_HEADER_BYTES = 3
KEYSTREAM_BLOCK_BYTES = 32
MAX_SIZE_T = (1 << 64) - 1
MAX_UINT32 = (1 << 32) - 1
SEGMENTS_SCHEMA = "segments-1"


@dataclass(frozen=True, order=True)
class NativeCavlcCandidate:
    nal_index: int
    macroblock_address: int
    category: int
    block_index: int
    rbsp_bit_offset: int

    def __post_init__(self) -> None:
        values = (self.nal_index, self.macroblock_address, self.category, self.block_index, self.rbsp_bit_offset)
        if any(type(value) is not int for value in values):
            raise ValueError("native CAVLC candidate fields must be integers")
        if not 0 <= self.nal_index <= MAX_SIZE_T or not 0 <= self.rbsp_bit_offset <= MAX_SIZE_T:
            raise ValueError("native CAVLC candidate size_t field is out of range")
        if not 0 <= self.macroblock_address <= MAX_UINT32:
            raise ValueError("native CAVLC candidate macroblock address is out of range")
        block_limits = {0: 1, 1: 16, 2: 2, 3: 8}
        if self.category not in block_limits or not 0 <= self.block_index < block_limits[self.category]:
            raise ValueError("native CAVLC candidate category or block index is invalid")

    def serialize(self) -> bytes:
        return f"{self.nal_index}:{self.macroblock_address}:{self.category}:{self.block_index}:{self.rbsp_bit_offset}".encode("ascii")


@dataclass(frozen=True)
class ChannelKeys:
    """The two independent subkeys derived from one 32-byte stego key."""

    schedule_key: bytes
    whitening_key: bytes


def hkdf_extract(salt: bytes, input_key_material: bytes) -> bytes:
    """RFC 5869 HKDF-Extract with SHA-256 (an empty salt means HashLen zeros)."""
    return hmac.new(salt or bytes(32), input_key_material, hashlib.sha256).digest()


def hkdf_expand(pseudorandom_key: bytes, info: bytes, length: int) -> bytes:
    """RFC 5869 HKDF-Expand with SHA-256."""
    if len(pseudorandom_key) < 32:
        raise ValueError("HKDF pseudorandom key must be at least 32 bytes")
    if not 0 <= length <= 255 * 32:
        raise ValueError("HKDF output length exceeds 255 SHA-256 blocks")
    output, block = b"", b""
    counter = 1
    while len(output) < length:
        block = hmac.new(pseudorandom_key, block + info + bytes((counter,)), hashlib.sha256).digest()
        output += block
        counter += 1
    return output[:length]


def hkdf_sha256(salt: bytes, input_key_material: bytes, info: bytes, length: int) -> bytes:
    return hkdf_expand(hkdf_extract(salt, input_key_material), info, length)


def _require_secret(secret_key: bytes) -> None:
    if not isinstance(secret_key, bytes) or len(secret_key) != 32:
        raise ValueError("secret_key must be exactly 32 bytes")


def derive_channel_keys(secret_key: bytes) -> ChannelKeys:
    _require_secret(secret_key)
    prk = hkdf_extract(HKDF_SALT, secret_key)
    return ChannelKeys(
        schedule_key=hkdf_expand(prk, SCHEDULE_INFO, SUBKEY_BYTES),
        whitening_key=hkdf_expand(prk, WHITENING_INFO, SUBKEY_BYTES),
    )


def score_candidate(candidate: NativeCavlcCandidate, secret_key: bytes) -> bytes:
    schedule_key = derive_channel_keys(secret_key).schedule_key
    return hmac.new(schedule_key, candidate.serialize(), hashlib.sha256).digest()


def select_candidates(
    candidates: list[NativeCavlcCandidate], secret_key: bytes, required_bits: int
) -> list[NativeCavlcCandidate]:
    if required_bits < 0 or required_bits > len(candidates):
        raise ValueError("blind schedule capacity is insufficient")
    schedule_key = derive_channel_keys(secret_key).schedule_key
    identities: set[bytes] = set()
    physical_targets: set[tuple[int, int]] = set()
    scored: list[tuple[bytes, bytes, NativeCavlcCandidate]] = []
    for candidate in candidates:
        identity = candidate.serialize()
        if identity in identities:
            raise ValueError("blind schedule candidate identity is duplicated")
        target = (candidate.nal_index, candidate.rbsp_bit_offset)
        if target in physical_targets:
            raise ValueError("blind schedule candidate patch target is duplicated")
        identities.add(identity)
        physical_targets.add(target)
        scored.append((hmac.new(schedule_key, identity, hashlib.sha256).digest(), identity, candidate))
    return [candidate for _score, _identity, candidate in sorted(scored)[:required_bits]]


def whitening_keystream(secret_key: bytes, byte_count: int, first_byte: int = 0) -> bytes:
    """Keystream bytes [first_byte, first_byte + byte_count) of the whitening stream."""
    if byte_count < 0 or first_byte < 0:
        raise ValueError("whitening keystream range is invalid")
    whitening_key = derive_channel_keys(secret_key).whitening_key
    first_block = first_byte // KEYSTREAM_BLOCK_BYTES
    end_block = -(-(first_byte + byte_count) // KEYSTREAM_BLOCK_BYTES)
    stream = b"".join(
        hmac.new(whitening_key, block.to_bytes(8, "big"), hashlib.sha256).digest()
        for block in range(first_block, end_block)
    )
    start = first_byte - first_block * KEYSTREAM_BLOCK_BYTES
    return stream[start:start + byte_count]


def whitening_keystream_bits(secret_key: bytes, bit_count: int, first_bit: int = 0) -> list[int]:
    """Keystream bits [first_bit, first_bit + bit_count), MSB-first."""
    if bit_count < 0 or first_bit < 0:
        raise ValueError("whitening keystream range is invalid")
    first_byte, end_byte = first_bit // 8, -(-(first_bit + bit_count) // 8)
    stream = whitening_keystream(secret_key, end_byte - first_byte, first_byte)
    return [(stream[index // 8 - first_byte] >> (7 - index % 8)) & 1
            for index in range(first_bit, first_bit + bit_count)]


def whiten_bits(bits: list[int], secret_key: bytes, first_bit: int = 0) -> list[int]:
    """XOR frame bits with the keystream; the same call un-whitens embedded bits."""
    if any(bit not in (0, 1) for bit in bits):
        raise ValueError("CAVLC frame bits must be zero or one")
    keystream = whitening_keystream_bits(secret_key, len(bits), first_bit)
    return [bit ^ key_bit for bit, key_bit in zip(bits, keystream)]


unwhiten_bits = whiten_bits


def bytes_to_bits(data: bytes) -> list[int]:
    return [(byte >> shift) & 1 for byte in data for shift in range(7, -1, -1)]


def bits_to_bytes(bits: list[int]) -> bytes:
    if len(bits) % 8:
        raise ValueError("CAVLC frame bits must be byte-aligned")
    return bytes(sum(bits[index + offset] << (7 - offset) for offset in range(8)) for index in range(0, len(bits), 8))


def whiten_frame(frame: bytes, secret_key: bytes) -> bytes:
    """Whitened (embedded) byte image of a whole frame; the same call un-whitens."""
    return bytes(a ^ b for a, b in zip(frame, whitening_keystream(secret_key, len(frame))))


unwhiten_frame = whiten_frame


def pack_frame(payload: bytes) -> bytes:
    """Plaintext v3 frame (before whitening): version, big-endian length, payload."""
    if len(payload) > 0xFFFF:
        raise ValueError("CAVLC payload exceeds 65535 bytes")
    return bytes((FRAME_VERSION,)) + len(payload).to_bytes(2, "big") + payload


def unpack_frame(frame: bytes, maximum_payload_bytes: int) -> bytes:
    """Check a plaintext (already un-whitened) v3 frame header and return its payload."""
    if maximum_payload_bytes < 0 or maximum_payload_bytes > 0xFFFF:
        raise ValueError("CAVLC payload maximum exceeds 65535 bytes")
    if len(frame) < FRAME_HEADER_BYTES or frame[0] != FRAME_VERSION:
        raise ValueError("CAVLC frame version is invalid")
    length = int.from_bytes(frame[1:3], "big")
    if length > maximum_payload_bytes or len(frame) != FRAME_HEADER_BYTES + length:
        raise ValueError("CAVLC frame length is invalid")
    return frame[FRAME_HEADER_BYTES:]


def embedded_frame_bits(payload: bytes, secret_key: bytes) -> list[int]:
    """Bits written into the selected sign positions, in schedule order."""
    return whiten_bits(bytes_to_bits(pack_frame(payload)), secret_key)


def recover_payload(embedded_bits: list[int], secret_key: bytes, maximum_payload_bytes: int) -> bytes:
    """Un-whiten bits read in schedule order, then check the v3 frame header."""
    frame = bits_to_bytes(unwhiten_bits(list(embedded_bits), secret_key))
    return unpack_frame(frame, maximum_payload_bytes)


def parse_candidate_identity(identity: str) -> NativeCavlcCandidate:
    """Inverse of :meth:`NativeCavlcCandidate.serialize` (``nal:mb:category:block:bit``)."""
    fields = identity.split(":") if isinstance(identity, str) else []
    if len(fields) != 5 or not all(field.isascii() and field.isdigit() for field in fields):
        raise ValueError("native CAVLC candidate identity is malformed")
    candidate = NativeCavlcCandidate(*(int(field) for field in fields))
    if candidate.serialize().decode("ascii") != identity:
        raise ValueError("native CAVLC candidate identity is not canonical")
    return candidate


@dataclass(frozen=True)
class SegmentCandidate:
    """One sign candidate of an IDR segment, as listed by ``--segments``.

    ``identity`` is segment-relative (what the schedule scores); ``nal_index``
    and ``rbsp_bit_offset`` locate the same sign bit in the whole file.
    """

    identity: NativeCavlcCandidate
    nal_index: int
    rbsp_bit_offset: int
    bit: int


class SchedulePlacement(NamedTuple):
    segment: int
    candidate: SegmentCandidate
    frame_bit_index: int


def _non_negative_int(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"segments JSON field {name} must be a non-negative integer")
    return value


def _segment_candidate(item: Any) -> SegmentCandidate:
    if not isinstance(item, dict):
        raise ValueError("segments JSON candidate must be an object")
    identity = parse_candidate_identity(item.get("id"))
    candidate = SegmentCandidate(
        identity=identity,
        nal_index=_non_negative_int(item.get("nal_index"), "nal_index"),
        rbsp_bit_offset=_non_negative_int(item.get("rbsp_bit_offset"), "rbsp_bit_offset"),
        bit=_non_negative_int(item.get("bit"), "bit"),
    )
    if candidate.bit > 1 or candidate.rbsp_bit_offset != identity.rbsp_bit_offset:
        raise ValueError("segments JSON candidate location does not match its identity")
    return candidate


def segment_schedule(
    segments_json: str | bytes | dict[str, Any],
    secret_key: bytes,
    frame_bit_count: int,
    max_bits_per_idr: int,
) -> list[SchedulePlacement]:
    """Ordered placements of the embedded frame bits, matching the native encoder.

    For each segment in order the native codec selects the lowest
    ``min(max_bits_per_idr, len(candidates))`` candidates by
    ``(HMAC(schedule_key, identity), identity)``; the first of them carry the
    next global frame bits until ``frame_bit_count`` bits are placed.  Scheduled
    positions past the end of the frame keep their cover sign and are not
    returned.  Embedded bit ``i`` is ``embedded_frame_bits(payload, key)[i]``.
    """
    data = json.loads(segments_json) if isinstance(segments_json, (str, bytes, bytearray)) else segments_json
    if not isinstance(data, dict) or data.get("schema") != SEGMENTS_SCHEMA:
        raise ValueError(f"segments JSON must use schema {SEGMENTS_SCHEMA!r}")
    if type(max_bits_per_idr) is not int or max_bits_per_idr <= 0:
        raise ValueError("max_bits_per_idr must be a positive integer")
    if type(frame_bit_count) is not int or frame_bit_count < 0:
        raise ValueError("frame_bit_count must be a non-negative integer")
    _require_secret(secret_key)
    segments = data.get("segments")
    if not isinstance(segments, list):
        raise ValueError("segments JSON must list segments")
    placements: list[SchedulePlacement] = []
    for expected_index, segment in enumerate(segments):
        if len(placements) == frame_bit_count:
            break
        if not isinstance(segment, dict) or segment.get("segment") != expected_index:
            raise ValueError("segments JSON segments must be numbered in order")
        candidates = [_segment_candidate(item) for item in segment.get("candidates", [])]
        by_identity = {candidate.identity: candidate for candidate in candidates}
        capacity = min(max_bits_per_idr, len(candidates))
        for identity in select_candidates([c.identity for c in candidates], secret_key, capacity):
            if len(placements) == frame_bit_count:
                break
            placements.append(SchedulePlacement(expected_index, by_identity[identity], len(placements)))
    if len(placements) < frame_bit_count:
        raise ValueError("IDR stream capacity is insufficient for payload")
    return placements
