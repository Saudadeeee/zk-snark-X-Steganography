"""Canonical fixed-width bit packing; every decoder rejects non-canonical input."""

from __future__ import annotations

import numpy as np

from .params import PAYLOAD_LENGTH_BYTES, BdlopParams


def pack_uints(values: np.ndarray, bits: int) -> bytes:
    """Pack non-negative integers below 2^bits, most significant bit first."""
    flat = np.asarray(values, dtype=np.int64).reshape(-1)
    if flat.size and (int(flat.min()) < 0 or int(flat.max()) >> bits):
        raise ValueError("value does not fit the fixed bit width")
    as_bytes = flat.astype(">u8").view(np.uint8).reshape(-1, 8)
    return np.packbits(np.unpackbits(as_bytes, axis=1)[:, 64 - bits:]).tobytes()


def unpack_uints(data: bytes, count: int, bits: int, bound: int) -> np.ndarray:
    """Inverse of :func:`pack_uints`; values must be below ``bound``."""
    if not isinstance(data, bytes):
        raise TypeError("packed field must be bytes")
    if len(data) != (count * bits + 7) // 8:
        raise ValueError("packed field has the wrong length")
    stream = np.unpackbits(np.frombuffer(data, dtype=np.uint8))
    if stream[count * bits:].any():
        raise ValueError("packed field has nonzero padding")
    wide = np.zeros((count, 64), dtype=np.uint8)
    wide[:, 64 - bits:] = stream[:count * bits].reshape(count, bits)
    values = np.packbits(wide, axis=1).view(">u8").reshape(count).astype(np.int64)
    if count and int(values.max()) >= bound:
        raise ValueError("packed coefficient is out of range")
    return values


def encode_payload(params: BdlopParams, payload: bytes) -> np.ndarray:
    """Encode ``length || payload`` injectively as one message polynomial."""
    if not isinstance(payload, bytes) or len(payload) > params.max_payload_bytes:
        raise ValueError("payload does not fit the message polynomial")
    width = params.payload_bytes_per_coefficient
    framed = len(payload).to_bytes(PAYLOAD_LENGTH_BYTES, "big") + payload
    framed = framed.ljust(params.degree * width, b"\x00")
    raw = np.frombuffer(framed, dtype=np.uint8).reshape(params.degree, width)
    padded = np.zeros((params.degree, 8), dtype=np.uint8)
    padded[:, 8 - width:] = raw
    return padded.view(">u8").reshape(params.degree).astype(np.int64)


def decode_payload(params: BdlopParams, message: np.ndarray) -> bytes:
    """Recover the payload; reject polynomials outside the encoder's image."""
    width = params.payload_bytes_per_coefficient
    values = np.asarray(message, dtype=np.int64)
    if values.shape != (params.degree,) or int(values.min()) < 0 or int(values.max()) >> (8 * width):
        raise ValueError("message polynomial is not a canonical payload encoding")
    framed = values.astype(">u8").view(np.uint8).reshape(params.degree, 8)[:, 8 - width:].tobytes()
    length = int.from_bytes(framed[:PAYLOAD_LENGTH_BYTES], "big")
    body = framed[PAYLOAD_LENGTH_BYTES:]
    if length > params.max_payload_bytes or any(body[length:]):
        raise ValueError("message polynomial is not a canonical payload encoding")
    return body[:length]
