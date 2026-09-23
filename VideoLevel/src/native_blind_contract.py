"""Shared Python specification for the native CAVLC blind schedule and frame.

This module deliberately contains no H.264 parsing or patching.  It is the
byte-for-byte contract that any Python adapter must satisfy before it can
interoperate with the native trailing-one-sign implementation. The locked
native deployment ABI is 64-bit ``size_t``; a 32-bit native target needs a
separate, versioned contract rather than silently narrowing identities.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

SCHEDULE_DOMAIN = b"blind-native-cavlc-v1\x00"
FRAME_DOMAIN = b"blind-native-frame-v1\x00"
FRAME_VERSION = 1
FRAME_TAG_BYTES = 16
MAX_SIZE_T = (1 << 64) - 1
MAX_UINT32 = (1 << 32) - 1


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


def _derived_key(domain: bytes, secret_key: bytes) -> bytes:
    if not isinstance(secret_key, bytes) or len(secret_key) != 32:
        raise ValueError("secret_key must be exactly 32 bytes")
    return domain + secret_key


def score_candidate(candidate: NativeCavlcCandidate, secret_key: bytes) -> bytes:
    return hmac.new(_derived_key(SCHEDULE_DOMAIN, secret_key), candidate.serialize(), hashlib.sha256).digest()


def select_candidates(
    candidates: list[NativeCavlcCandidate], secret_key: bytes, required_bits: int
) -> list[NativeCavlcCandidate]:
    if required_bits < 0 or required_bits > len(candidates):
        raise ValueError("blind schedule capacity is insufficient")
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
        scored.append((score_candidate(candidate, secret_key), identity, candidate))
    return [candidate for _score, _identity, candidate in sorted(scored)[:required_bits]]


def pack_authenticated_frame(payload: bytes, secret_key: bytes) -> bytes:
    if len(payload) > 0xFFFF:
        raise ValueError("authenticated payload exceeds 65535 bytes")
    body = bytes((FRAME_VERSION,)) + len(payload).to_bytes(2, "big") + payload
    tag = hmac.new(_derived_key(FRAME_DOMAIN, secret_key), body, hashlib.sha256).digest()[:FRAME_TAG_BYTES]
    return body + tag


def unpack_authenticated_frame(frame: bytes, secret_key: bytes, maximum_payload_bytes: int) -> bytes:
    if maximum_payload_bytes < 0 or maximum_payload_bytes > 0xFFFF:
        raise ValueError("authenticated payload maximum exceeds 65535 bytes")
    if len(frame) < 3 + FRAME_TAG_BYTES or frame[0] != FRAME_VERSION:
        raise ValueError("authenticated CAVLC frame version is invalid")
    length = int.from_bytes(frame[1:3], "big")
    if length > maximum_payload_bytes or len(frame) != 3 + length + FRAME_TAG_BYTES:
        raise ValueError("authenticated CAVLC frame length is invalid")
    body, tag = frame[:-FRAME_TAG_BYTES], frame[-FRAME_TAG_BYTES:]
    expected = hmac.new(_derived_key(FRAME_DOMAIN, secret_key), body, hashlib.sha256).digest()[:FRAME_TAG_BYTES]
    if not hmac.compare_digest(tag, expected):
        raise ValueError("authenticated CAVLC frame tag is invalid")
    return frame[3:-FRAME_TAG_BYTES]
