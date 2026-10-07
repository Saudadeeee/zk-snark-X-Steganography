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

Optional channel parameters (out of band, like the per-IDR cap; the defaults
are exactly the protocol above):

* selection policy ``random`` (above) or ``low-drift``: rank by
  ``(tier, score, identity)`` and take the first ``min(cap, n)`` per segment.
  ``tier = r + d + f`` (:func:`candidate_tier`) uses only syntax a sign flip
  never changes: picture third of the MB row, DC category, low-frequency AC.
  ``--segments`` lists ``mb_row``, ``mb_height``, ``freq`` and ``tier``.
* key mode ``master`` (above) or ``per-video``::

      video_nonce   = SHA256(b"zkstego/video-nonce/v1" || for each NAL of the first
                      segment (stored SPS/PPS, then its IDR): u32be(1 + len(rbsp')) ||
                      header || rbsp')     # rbsp' = IDR RBSP with ALL candidate signs cleared
      PRK           = HKDF-Extract(b"zkstego-cavlc-v4-salt", K)
      video_key     = HKDF-Expand(PRK, b"zkstego/cavlc/v4/video" || video_nonce, 32)
      schedule_key  = HKDF-Expand(video_key, b"zkstego/cavlc/v4/schedule", 32)
      whitening_key = HKDF-Expand(video_key, b"zkstego/cavlc/v4/whitening", 32)

  A verification token is ``schedule_key || whitening_key`` (64 bytes): it
  extracts from and digests that one video without ``K``.  Every function
  below that takes ``secret_key`` also accepts derived :class:`ChannelKeys`
  (``derive_video_channel_keys`` or ``ChannelKeys.from_token``); the nonce of a
  file is computed by :func:`src.video_binding.video_nonce`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NamedTuple, Union

HKDF_SALT = b"zkstego-cavlc-v2-salt"
SCHEDULE_INFO = b"zkstego/cavlc/v2/schedule"
WHITENING_INFO = b"zkstego/cavlc/v2/whitening"
PER_VIDEO_HKDF_SALT = b"zkstego-cavlc-v4-salt"
PER_VIDEO_INFO = b"zkstego/cavlc/v4/video"
PER_VIDEO_SCHEDULE_INFO = b"zkstego/cavlc/v4/schedule"
PER_VIDEO_WHITENING_INFO = b"zkstego/cavlc/v4/whitening"
VIDEO_NONCE_DOMAIN = b"zkstego/video-nonce/v1"
VERIFICATION_TOKEN_BYTES = 64
SELECTION_POLICIES = ("random", "low-drift")
KEY_MODES = ("master", "per-video")
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

    def __post_init__(self) -> None:
        for value in (self.schedule_key, self.whitening_key):
            if not isinstance(value, bytes) or len(value) != SUBKEY_BYTES:
                raise ValueError("channel subkeys must be 32 bytes each")

    @classmethod
    def from_token(cls, token: bytes) -> ChannelKeys:
        """Split a 64-byte per-video verification token (schedule_key || whitening_key)."""
        if not isinstance(token, bytes) or len(token) != VERIFICATION_TOKEN_BYTES:
            raise ValueError("verification token must be exactly 64 bytes")
        return cls(token[:SUBKEY_BYTES], token[SUBKEY_BYTES:])

    def token(self) -> bytes:
        """The verification token of these (per-video) subkeys."""
        return self.schedule_key + self.whitening_key


# A 32-byte master key (v3 subkeys are derived from it) or already derived subkeys.
ChannelSecret = Union[bytes, ChannelKeys]


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


def derive_video_channel_keys(secret_key: bytes, video_nonce: bytes) -> ChannelKeys:
    """Per-video subkeys of ``K`` for one video nonce (key mode ``per-video``)."""
    _require_secret(secret_key)
    if not isinstance(video_nonce, bytes) or len(video_nonce) != 32:
        raise ValueError("video nonce must be exactly 32 bytes")
    video_key = hkdf_expand(hkdf_extract(PER_VIDEO_HKDF_SALT, secret_key), PER_VIDEO_INFO + video_nonce, SUBKEY_BYTES)
    return ChannelKeys(
        schedule_key=hkdf_expand(video_key, PER_VIDEO_SCHEDULE_INFO, SUBKEY_BYTES),
        whitening_key=hkdf_expand(video_key, PER_VIDEO_WHITENING_INFO, SUBKEY_BYTES),
    )


def channel_keys(secret_key: ChannelSecret) -> ChannelKeys:
    """Subkeys of a master key (v3 derivation), or derived subkeys unchanged."""
    if isinstance(secret_key, ChannelKeys):
        return secret_key
    return derive_channel_keys(secret_key)


def require_policy(policy: str) -> str:
    if policy not in SELECTION_POLICIES:
        raise ValueError("selection policy must be 'random' or 'low-drift'")
    return policy


def require_key_mode(key_mode: str) -> str:
    if key_mode not in KEY_MODES:
        raise ValueError("key mode must be 'master' or 'per-video'")
    return key_mode


def channel_flags(select: str = "random", key_mode: str = "master") -> list[str]:
    """Trailing ``zkstego_blind_bits`` flags for these parameters (none for the defaults)."""
    flags: list[str] = []
    if require_policy(select) != "random":
        flags += ["--select", select]
    if require_key_mode(key_mode) != "master":
        flags += ["--key-mode", key_mode]
    return flags


def secret_line(secret: bytes, key_mode: str = "master") -> bytes:
    """The stdin key line of the native CLI: 64 hex for ``K``, ``token:`` + 128 hex for a token."""
    if isinstance(secret, (bytes, bytearray)) and len(secret) == 32:
        return secret.hex().encode("ascii") + b"\n"
    if isinstance(secret, (bytes, bytearray)) and len(secret) == VERIFICATION_TOKEN_BYTES:
        if require_key_mode(key_mode) != "per-video":
            raise ValueError("a verification token requires key mode per-video")
        return b"token:" + secret.hex().encode("ascii") + b"\n"
    raise ValueError("stego key must be 32 bytes (or a 64-byte per-video verification token)")


def candidate_tier(category: int, mb_row: int, mb_height: int, freq: int) -> int:
    """Low-drift tier ``r + d + f`` (lower is selected first); mirrors ``cavlc_candidate_tier``.

    ``r`` = 2 / 1 / 0 for an MB row in the top / middle / bottom third
    (``mb_row*3 < mb_height``, ``mb_row*3 < 2*mb_height``); ``d`` = 2 for LumaDC (0) and
    ChromaDC (2); ``f`` = 1 for Luma4x4/AC (1) and ChromaAC (3) when ``freq = i + j <= 2``.
    """
    if any(type(value) is not int or value < 0 for value in (category, mb_row, mb_height, freq)):
        raise ValueError("tier inputs must be non-negative integers")
    row_term = 2 if mb_row * 3 < mb_height else 1 if mb_row * 3 < 2 * mb_height else 0
    dc_term = 2 if category in (0, 2) else 0
    frequency_term = 1 if category in (1, 3) and freq <= 2 else 0
    return row_term + dc_term + frequency_term


# i + j of each 4x4 zig-zag scan index, and of the 2x2 ChromaDC raster order.
_ZIG_ZAG_FREQUENCY = (0, 1, 1, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 5, 5, 6)
_CHROMA_DC_FREQUENCY = (0, 1, 1, 2)


def scan_frequency(category: int, coefficients_scan: list[int]) -> int:
    """``freq`` of a candidate from its block's scan-order coefficients (full trace JSON).

    The candidate sign belongs to the last non-zero coefficient in scan order; AC-only
    blocks (15 coefficients) start at zig-zag index 1; ChromaDC uses its 2x2 raster order.
    """
    nonzero = [index for index, value in enumerate(coefficients_scan) if value != 0]
    if not nonzero:
        raise ValueError("a sign candidate block has a non-zero coefficient")
    last = nonzero[-1]
    if category == 2:
        if len(coefficients_scan) != 4:
            raise ValueError("ChromaDC block must have 4 coefficients")
        return _CHROMA_DC_FREQUENCY[last]
    if len(coefficients_scan) not in (15, 16):
        raise ValueError("residual block must have 15 or 16 coefficients")
    return _ZIG_ZAG_FREQUENCY[last + (1 if len(coefficients_scan) == 15 else 0)]


def score_candidate(candidate: NativeCavlcCandidate, secret_key: ChannelSecret) -> bytes:
    schedule_key = channel_keys(secret_key).schedule_key
    return hmac.new(schedule_key, candidate.serialize(), hashlib.sha256).digest()


def select_candidates(
    candidates: list[NativeCavlcCandidate],
    secret_key: ChannelSecret,
    required_bits: int,
    policy: str = "random",
    tiers: Mapping[NativeCavlcCandidate, int] | None = None,
) -> list[NativeCavlcCandidate]:
    """Lowest ``required_bits`` candidates by ``(score, identity)``, or ``(tier, score, identity)``.

    ``low-drift`` needs ``tiers`` (candidate -> :func:`candidate_tier`) for every candidate.
    """
    if required_bits < 0 or required_bits > len(candidates):
        raise ValueError("blind schedule capacity is insufficient")
    low_drift = require_policy(policy) == "low-drift"
    if low_drift and (tiers is None or any(candidate not in tiers for candidate in candidates)):
        raise ValueError("low-drift selection needs the tier of every candidate")
    schedule_key = channel_keys(secret_key).schedule_key
    identities: set[bytes] = set()
    physical_targets: set[tuple[int, int]] = set()
    scored: list[tuple[int, bytes, bytes, NativeCavlcCandidate]] = []
    for candidate in candidates:
        identity = candidate.serialize()
        if identity in identities:
            raise ValueError("blind schedule candidate identity is duplicated")
        target = (candidate.nal_index, candidate.rbsp_bit_offset)
        if target in physical_targets:
            raise ValueError("blind schedule candidate patch target is duplicated")
        identities.add(identity)
        physical_targets.add(target)
        tier = tiers[candidate] if low_drift and tiers is not None else 0
        scored.append((tier, hmac.new(schedule_key, identity, hashlib.sha256).digest(), identity, candidate))
    return [candidate for _tier, _score, _identity, candidate in sorted(scored)[:required_bits]]


def whitening_keystream(secret_key: ChannelSecret, byte_count: int, first_byte: int = 0) -> bytes:
    """Keystream bytes [first_byte, first_byte + byte_count) of the whitening stream."""
    if byte_count < 0 or first_byte < 0:
        raise ValueError("whitening keystream range is invalid")
    whitening_key = channel_keys(secret_key).whitening_key
    first_block = first_byte // KEYSTREAM_BLOCK_BYTES
    end_block = -(-(first_byte + byte_count) // KEYSTREAM_BLOCK_BYTES)
    stream = b"".join(
        hmac.new(whitening_key, block.to_bytes(8, "big"), hashlib.sha256).digest()
        for block in range(first_block, end_block)
    )
    start = first_byte - first_block * KEYSTREAM_BLOCK_BYTES
    return stream[start:start + byte_count]


def whitening_keystream_bits(secret_key: ChannelSecret, bit_count: int, first_bit: int = 0) -> list[int]:
    """Keystream bits [first_bit, first_bit + bit_count), MSB-first."""
    if bit_count < 0 or first_bit < 0:
        raise ValueError("whitening keystream range is invalid")
    first_byte, end_byte = first_bit // 8, -(-(first_bit + bit_count) // 8)
    stream = whitening_keystream(secret_key, end_byte - first_byte, first_byte)
    return [(stream[index // 8 - first_byte] >> (7 - index % 8)) & 1
            for index in range(first_bit, first_bit + bit_count)]


def whiten_bits(bits: list[int], secret_key: ChannelSecret, first_bit: int = 0) -> list[int]:
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


def whiten_frame(frame: bytes, secret_key: ChannelSecret) -> bytes:
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


def embedded_frame_bits(payload: bytes, secret_key: ChannelSecret) -> list[int]:
    """Bits written into the selected sign positions, in schedule order."""
    return whiten_bits(bytes_to_bits(pack_frame(payload)), secret_key)


def recover_payload(embedded_bits: list[int], secret_key: ChannelSecret, maximum_payload_bytes: int) -> bytes:
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
    # Low-drift tier inputs (None when the JSON predates them).
    mb_row: int | None = None
    mb_height: int | None = None
    freq: int | None = None

    @property
    def tier(self) -> int:
        if self.mb_row is None or self.mb_height is None or self.freq is None:
            raise ValueError("segments JSON candidate lacks the low-drift tier inputs")
        return candidate_tier(self.identity.category, self.mb_row, self.mb_height, self.freq)


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
    tier_inputs = {name: item.get(name) for name in ("mb_row", "mb_height", "freq")}
    if any(value is not None for value in tier_inputs.values()):
        tier_inputs = {name: _non_negative_int(value, name) for name, value in tier_inputs.items()}
    candidate = SegmentCandidate(
        identity=identity,
        nal_index=_non_negative_int(item.get("nal_index"), "nal_index"),
        rbsp_bit_offset=_non_negative_int(item.get("rbsp_bit_offset"), "rbsp_bit_offset"),
        bit=_non_negative_int(item.get("bit"), "bit"),
        **tier_inputs,
    )
    if candidate.bit > 1 or candidate.rbsp_bit_offset != identity.rbsp_bit_offset:
        raise ValueError("segments JSON candidate location does not match its identity")
    # The native tier is recomputed here; a disagreement means a contract drift.
    if "tier" in item and item["tier"] != candidate.tier:
        raise ValueError("segments JSON candidate tier disagrees with its inputs")
    return candidate


def segment_candidates(segments_json: str | bytes | dict[str, Any]) -> list[list[SegmentCandidate]]:
    """Parsed candidates of every segment of a ``--segments`` document, in order."""
    data = json.loads(segments_json) if isinstance(segments_json, (str, bytes, bytearray)) else segments_json
    if not isinstance(data, dict) or data.get("schema") != SEGMENTS_SCHEMA:
        raise ValueError(f"segments JSON must use schema {SEGMENTS_SCHEMA!r}")
    segments = data.get("segments")
    if not isinstance(segments, list):
        raise ValueError("segments JSON must list segments")
    parsed: list[list[SegmentCandidate]] = []
    for expected_index, segment in enumerate(segments):
        if not isinstance(segment, dict) or segment.get("segment") != expected_index:
            raise ValueError("segments JSON segments must be numbered in order")
        parsed.append([_segment_candidate(item) for item in segment.get("candidates", [])])
    return parsed


def segment_schedule(
    segments_json: str | bytes | dict[str, Any],
    secret_key: ChannelSecret,
    frame_bit_count: int,
    max_bits_per_idr: int,
    policy: str = "random",
) -> list[SchedulePlacement]:
    """Ordered placements of the embedded frame bits, matching the native encoder.

    For each segment in order the native codec selects the lowest
    ``min(max_bits_per_idr, len(candidates))`` candidates by
    ``(HMAC(schedule_key, identity), identity)`` (policy ``random``) or by
    ``(tier, HMAC(schedule_key, identity), identity)`` (policy ``low-drift``); the
    first of them carry the next global frame bits until ``frame_bit_count`` bits
    are placed.  Scheduled positions past the end of the frame keep their cover
    sign and are not returned.  Embedded bit ``i`` is
    ``embedded_frame_bits(payload, key)[i]``.  ``secret_key`` is the 32-byte
    master key, or :class:`ChannelKeys` (per-video subkeys or a token).
    """
    data = json.loads(segments_json) if isinstance(segments_json, (str, bytes, bytearray)) else segments_json
    if not isinstance(data, dict) or data.get("schema") != SEGMENTS_SCHEMA:
        raise ValueError(f"segments JSON must use schema {SEGMENTS_SCHEMA!r}")
    if type(max_bits_per_idr) is not int or max_bits_per_idr <= 0:
        raise ValueError("max_bits_per_idr must be a positive integer")
    if type(frame_bit_count) is not int or frame_bit_count < 0:
        raise ValueError("frame_bit_count must be a non-negative integer")
    low_drift = require_policy(policy) == "low-drift"
    keys = channel_keys(secret_key)
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
        tiers = {c.identity: c.tier for c in candidates} if low_drift else None
        for identity in select_candidates([c.identity for c in candidates], keys, capacity, policy, tiers):
            if len(placements) == frame_bit_count:
                break
            placements.append(SchedulePlacement(expected_index, by_identity[identity], len(placements)))
    if len(placements) < frame_bit_count:
        raise ValueError("IDR stream capacity is insufficient for payload")
    return placements
