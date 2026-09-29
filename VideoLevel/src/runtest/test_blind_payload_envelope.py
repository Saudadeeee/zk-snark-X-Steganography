"""Tests for self-framing payload bytes recovered from blind carriers."""

import pytest

from src.blind_sync import (
    BLIND_ENVELOPE_HEADER_BYTES,
    pack_blind_payload,
    parse_blind_payload_header,
    unpack_blind_payload,
)


def test_blind_payload_envelope_round_trip():
    payload = bytes.fromhex("f001cafe")
    encoded = pack_blind_payload(payload)

    assert len(encoded[:BLIND_ENVELOPE_HEADER_BYTES]) == BLIND_ENVELOPE_HEADER_BYTES
    assert parse_blind_payload_header(encoded[:BLIND_ENVELOPE_HEADER_BYTES]) == len(payload)
    assert unpack_blind_payload(encoded) == payload


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data[:-1],
        lambda data: data + b"x",
        lambda data: data[:-1] + bytes([data[-1] ^ 1]),
        lambda data: b"NOPE" + data[4:],
        lambda data: data[:4] + bytes([data[4] + 1]) + data[5:],
        lambda data: data[:5] + bytes([data[5] + 1]) + data[6:],
        lambda data: data[:10] + bytes([data[10] ^ 1]) + data[11:],
        lambda data: data[:6] + b"\xff\xff\xff\xff" + data[10:],
    ],
)
def test_blind_payload_envelope_rejects_corruption_and_bad_framing(mutate):
    encoded = pack_blind_payload(b"lattice-proof-bytes")

    with pytest.raises(ValueError):
        unpack_blind_payload(mutate(encoded))


def test_blind_payload_header_rejects_truncation():
    with pytest.raises(ValueError):
        parse_blind_payload_header(b"ZKVP\x01")
