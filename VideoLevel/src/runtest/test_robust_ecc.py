"""Convolutional code, Viterbi decoder and CRC of the robust channel."""

from __future__ import annotations

import numpy as np
import pytest

from src.robust import ecc


@pytest.mark.parametrize("rate", [2, 3])
def test_clean_round_trip(rate: int) -> None:
    bits = np.random.default_rng(1).integers(0, 2, 4096).astype(np.uint8)
    coded = ecc.conv_encode(bits, rate)
    assert len(coded) == ecc.coded_length(len(bits), rate)
    soft = 2.0 * coded - 1.0
    assert np.array_equal(ecc.viterbi_decode(soft, rate), bits)


@pytest.mark.parametrize("rate, flip_rate", [(2, 0.01), (3, 0.03)])
def test_random_errors_at_the_designed_rate_are_corrected(rate: int, flip_rate: float) -> None:
    rng = np.random.default_rng(2)
    bits = rng.integers(0, 2, 20_000).astype(np.uint8)
    coded = ecc.conv_encode(bits, rate)
    flips = rng.random(len(coded)) < flip_rate
    soft = np.where(coded ^ flips, 1.0, -1.0)
    assert np.array_equal(ecc.viterbi_decode(soft, rate), bits)


def test_soft_values_beat_hard_decisions() -> None:
    """Gaussian noise: soft decoding succeeds where hard decisions do not."""
    rng = np.random.default_rng(3)
    bits = rng.integers(0, 2, 20_000).astype(np.uint8)
    coded = ecc.conv_encode(bits, 2)
    received = (2.0 * coded - 1.0) + rng.normal(0, 0.6, len(coded))
    assert np.array_equal(ecc.viterbi_decode(received, 2), bits)
    assert not np.array_equal(ecc.viterbi_decode(np.sign(received), 2), bits)


def test_erasures_are_tolerated() -> None:
    rng = np.random.default_rng(4)
    bits = rng.integers(0, 2, 5_000).astype(np.uint8)
    soft = 2.0 * ecc.conv_encode(bits, 3) - 1.0
    soft[rng.random(len(soft)) < 0.4] = 0.0
    assert np.array_equal(ecc.viterbi_decode(soft, 3), bits)


def test_crc_detects_corruption() -> None:
    framed = ecc.with_crc(b"robust envelope")
    assert ecc.strip_crc(framed) == b"robust envelope"
    corrupted = bytes([framed[0] ^ 1]) + framed[1:]
    with pytest.raises(ValueError):
        ecc.strip_crc(corrupted)
    with pytest.raises(ValueError):
        ecc.strip_crc(b"abc")


def test_bits_and_bytes_round_trip() -> None:
    data = bytes(range(256))
    assert ecc.bits_to_bytes(ecc.bytes_to_bits(data)) == data
    with pytest.raises(ValueError):
        ecc.bits_to_bytes(np.ones(7, dtype=np.uint8))


def test_bad_inputs_are_refused() -> None:
    with pytest.raises(ValueError):
        ecc.conv_encode(np.array([0, 2], dtype=np.uint8))
    with pytest.raises(ValueError):
        ecc.viterbi_decode(np.zeros(5), 2)
    with pytest.raises(ValueError):
        ecc.coded_length(10, 4)
