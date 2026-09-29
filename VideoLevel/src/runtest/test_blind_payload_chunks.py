"""Tests for versioned, ordered framing of proof payload pieces."""

from __future__ import annotations

import pytest

from src.blind_payload_chunks import (
    assemble_payload_chunks,
    pack_payload_chunks,
    payload_chunk_count,
)


def test_payload_chunks_round_trip_exact_bytes():
    payload = bytes(range(256)) * 11 + b"tail"

    chunks = pack_payload_chunks(payload, chunk_size=317)

    assert len(chunks) == 9
    assert payload_chunk_count(chunks[0]) == len(chunks)
    assert assemble_payload_chunks(chunks) == payload


def test_payload_chunk_assembly_rejects_reordering_and_missing_chunks():
    chunks = pack_payload_chunks(b"a" * 31, chunk_size=10)

    with pytest.raises(ValueError, match="order"):
        assemble_payload_chunks([chunks[1], chunks[0], chunks[2], chunks[3]])
    with pytest.raises(ValueError, match="count"):
        assemble_payload_chunks(chunks[:-1])


def test_payload_chunk_assembly_rejects_corrupt_chunk():
    chunks = pack_payload_chunks(b"payload for tamper test", chunk_size=7)
    tampered = list(chunks)
    tampered[1] = tampered[1][:-1] + bytes([tampered[1][-1] ^ 1])

    with pytest.raises(ValueError, match="checksum"):
        assemble_payload_chunks(tampered)


@pytest.mark.parametrize(
    ("payload", "chunk_size", "exception"),
    [
        (b"", 4, ValueError),
        ("not bytes", 4, TypeError),
        (b"payload", 0, ValueError),
        (b"payload", 65_536, ValueError),
        (b"payload", True, ValueError),
    ],
)
def test_payload_chunk_packing_rejects_invalid_inputs(payload, chunk_size, exception):
    with pytest.raises(exception):
        pack_payload_chunks(payload, chunk_size=chunk_size)


def test_payload_chunk_assembly_rejects_empty_or_malformed_input():
    with pytest.raises(ValueError, match="at least one"):
        assemble_payload_chunks([])
    with pytest.raises(ValueError, match="truncated"):
        assemble_payload_chunks([b"short"])


def test_payload_chunk_count_rejects_invalid_first_segment_chunk():
    chunks = pack_payload_chunks(b"payload", chunk_size=4)
    tampered = chunks[0][:-1] + bytes([chunks[0][-1] ^ 1])

    with pytest.raises(ValueError, match="checksum"):
        payload_chunk_count(tampered)
