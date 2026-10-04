"""Video binding for the camera proof: what the Groth16 statement is tied to.

Video digest (``zkstego_blind_bits video-digest``; this module is the byte-for-byte
Python reference)::

    carriers = the frame_bits sign positions the stream codec writes under the stego
               key (per IDR segment, the first min(cap, candidates) keyed-schedule
               positions, until the frame ends)
    digest   = SHA256(b"zkstego/video-digest/v1" || u32be(frame_bits) || u32be(cap) ||
               for each NAL in file order: u32be(1 + len(rbsp')) || header || rbsp')

``rbsp'`` is the NAL's RBSP with exactly the carrier bits cleared. Embedding
changes only those bits and emulation-prevention bytes, so the cover and the
stego video have the same digest, while any other edit (another video, a dropped
or appended frame, a re-encode, any non-carrier sign) changes it. Editing a
carrier bit changes the extracted payload instead, which the proof rejects. The
verifier holds the stego key anyway, since it extracts the payload.

Binding (the two public inputs of ``circuits/camera_video.circom``)::

    binding = SHA256(b"zkstego/proof-binding/v1" || mode || video_digest || SHA256(message))
    bindingHi, bindingLo = big-endian halves of binding

Mode 0 binds the video and the message (file workflow). Mode 1 binds only the
message, with a zero video digest: a live stream embeds its proof before the
rest of the video exists, so it cannot commit to it; verifiers report it.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any

from src.native_blind_contract import segment_schedule

VIDEO_DIGEST_DOMAIN = b"zkstego/video-digest/v1"
BINDING_DOMAIN = b"zkstego/proof-binding/v1"
MODE_VIDEO = 0
MODE_MESSAGE_ONLY = 1
DIGEST_BYTES = 32
_NATIVE_LINE = re.compile(r"^ZKSTEGO_VIDEO_DIGEST ([0-9a-f]{64}) carrier_segments=(\d+) nal_units=(\d+)$")


def _start_code_length(data: bytes, offset: int) -> int:
    if data[offset:offset + 3] == b"\x00\x00\x01":
        return 3
    if data[offset:offset + 4] == b"\x00\x00\x00\x01":
        return 4
    return 0


def split_annex_b(data: bytes) -> list[tuple[int, bytes]]:
    """(header byte, EBSP payload) per NAL unit, exactly as the native splitter."""
    units: list[tuple[int, bytes]] = []
    cursor = 0
    while cursor < len(data):
        marker = _start_code_length(data, cursor)
        if not marker:
            cursor += 1
            continue
        header_offset = cursor + marker
        if header_offset >= len(data):
            break
        cursor = header_offset + 1
        while cursor < len(data) and not _start_code_length(data, cursor):
            cursor += 1
        units.append((data[header_offset], data[header_offset + 1:cursor]))
    return units


def ebsp_to_rbsp(ebsp: bytes) -> bytearray:
    """Remove emulation-prevention bytes (00 00 03 followed by a byte <= 03)."""
    rbsp = bytearray()
    zeros = 0
    for index, byte in enumerate(ebsp):
        if zeros >= 2 and byte == 0x03 and index + 1 < len(ebsp) and ebsp[index + 1] <= 0x03:
            zeros = 0
            continue
        rbsp.append(byte)
        zeros = zeros + 1 if byte == 0 else 0
    return rbsp


def _u32(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("video binding field exceeds 32 bits")
    return value.to_bytes(4, "big")


def video_digest(annex_b: bytes, segments: dict[str, Any], stego_key: bytes, frame_bits: int,
                 max_bits_per_idr: int) -> bytes:
    """Reference digest; ``segments`` is ``zkstego_inspect <video> --segments <cap>`` JSON."""
    if frame_bits <= 0 or max_bits_per_idr <= 0:
        raise ValueError("frame_bits and max_bits_per_idr must be positive")
    cleared: dict[int, list[int]] = {}
    for placement in segment_schedule(segments, stego_key, frame_bits, max_bits_per_idr):
        cleared.setdefault(placement.candidate.nal_index, []).append(placement.candidate.rbsp_bit_offset)
    canonical = bytearray(VIDEO_DIGEST_DOMAIN + _u32(frame_bits) + _u32(max_bits_per_idr))
    for index, (header, ebsp) in enumerate(split_annex_b(annex_b)):
        rbsp = ebsp_to_rbsp(ebsp)
        for bit in cleared.get(index, ()):
            rbsp[bit // 8] &= ~(0x80 >> (bit % 8)) & 0xFF
        canonical += _u32(1 + len(rbsp)) + bytes((header,)) + rbsp
    return hashlib.sha256(canonical).digest()


def native_video_digest(native_cli: str | Path, video: str | Path, stego_key: bytes, frame_bits: int,
                        max_bits_per_idr: int, timeout: float = 600.0) -> bytes:
    """Run ``zkstego_blind_bits video-digest`` (the production path); the stego key goes through stdin."""
    if len(stego_key) != 32:
        raise ValueError("stego key must be 32 bytes")
    result = subprocess.run([str(native_cli), "video-digest", str(video), str(frame_bits), str(max_bits_per_idr)],
                            input=stego_key.hex().encode("ascii") + b"\n", capture_output=True, timeout=timeout,
                            check=False)
    if result.returncode != 0:
        raise ValueError("video digest failed: " + result.stderr.decode("utf-8", errors="replace").strip()[-300:])
    match = _NATIVE_LINE.match(result.stdout.decode("ascii", errors="replace").strip())
    if not match:
        raise RuntimeError("native video-digest returned malformed output")
    return bytes.fromhex(match.group(1))


def binding_digest(mode: int, digest: bytes, message: bytes) -> bytes:
    if mode not in (MODE_VIDEO, MODE_MESSAGE_ONLY):
        raise ValueError("binding mode must be 0 (video) or 1 (message only)")
    if len(digest) != DIGEST_BYTES:
        raise ValueError("video digest must be 32 bytes")
    if mode == MODE_MESSAGE_ONLY and digest != bytes(DIGEST_BYTES):
        raise ValueError("message-only binding uses an all-zero video digest")
    return hashlib.sha256(BINDING_DOMAIN + bytes((mode,)) + digest + hashlib.sha256(message).digest()).digest()


def binding_public_inputs(binding: bytes) -> tuple[int, int]:
    """(bindingHi, bindingLo): the 32-byte binding split into two 128-bit field elements."""
    if len(binding) != DIGEST_BYTES:
        raise ValueError("binding must be 32 bytes")
    return int.from_bytes(binding[:16], "big"), int.from_bytes(binding[16:], "big")
