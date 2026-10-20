"""Ring arithmetic and deterministic sampling for the BDLOP lattice-ZK backend."""

from __future__ import annotations

import numpy as np
import pytest

from src.lattice_zk import ring, sampling

TOY_Q = 1_048_573  # prime, 5 mod 8
TOY_N = 64


def _schoolbook(a: np.ndarray, b: np.ndarray, q: int) -> np.ndarray:
    n = len(a)
    out = [0] * n
    for i, x in enumerate(a.tolist()):
        for j, y in enumerate(b.tolist()):
            sign = -1 if i + j >= n else 1
            out[(i + j) % n] = (out[(i + j) % n] + sign * x * y) % q
    return np.array(out, dtype=np.int64)


def _uniform(label: bytes, q: int = TOY_Q, n: int = TOY_N) -> np.ndarray:
    return sampling.uniform_poly(sampling.XofStream(b"test/" + label), q, n)


def test_toy_modulus_satisfies_two_factor_splitting_condition() -> None:
    ring.validate_modulus(TOY_Q)
    with pytest.raises(ValueError):
        ring.validate_modulus(8_380_417)  # ML-DSA prime: fully splitting
    with pytest.raises(ValueError):
        ring.validate_modulus(1_048_581)  # 5 mod 8 but composite


def test_poly_mul_matches_negacyclic_schoolbook() -> None:
    a, b = _uniform(b"a"), _uniform(b"b")
    assert np.array_equal(ring.poly_mul(a, b, TOY_Q), _schoolbook(a, b, TOY_Q))


def test_poly_mul_handles_large_modulus_without_overflow() -> None:
    q = 1_073_741_789  # ~2^30
    a = np.full(256, q - 1, dtype=np.int64)
    assert np.array_equal(ring.poly_mul(a, a, q), _schoolbook(a, a, q))


def test_x_to_the_n_is_minus_one() -> None:
    x_half = np.zeros(TOY_N, dtype=np.int64)
    x_half[TOY_N // 2] = 1
    minus_one = np.zeros(TOY_N, dtype=np.int64)
    minus_one[0] = TOY_Q - 1
    assert np.array_equal(ring.poly_mul(x_half, x_half, TOY_Q), minus_one)


def test_center_maps_to_symmetric_interval() -> None:
    values = np.array([0, 1, TOY_Q // 2, TOY_Q // 2 + 1, TOY_Q - 1], dtype=np.int64)
    assert ring.center(values, TOY_Q).tolist() == [0, 1, TOY_Q // 2, -(TOY_Q // 2), -1]


def test_mat_vec_is_linear() -> None:
    stream = sampling.XofStream(b"test/matrix")
    matrix = np.stack(
        [np.stack([sampling.uniform_poly(stream, TOY_Q, TOY_N) for _ in range(3)]) for _ in range(2)]
    )
    u = np.stack([_uniform(b"u%d" % i) for i in range(3)])
    v = np.stack([_uniform(b"v%d" % i) for i in range(3)])
    left = ring.mat_vec(matrix, (u + v) % TOY_Q, TOY_Q)
    right = (ring.mat_vec(matrix, u, TOY_Q) + ring.mat_vec(matrix, v, TOY_Q)) % TOY_Q
    assert left.shape == (2, TOY_N)
    assert np.array_equal(left, right)


def test_xof_stream_is_deterministic_and_prefix_stable() -> None:
    first = sampling.XofStream(b"seed")
    second = sampling.XofStream(b"seed")
    head = first.read(10)
    tail = first.read(5_000)
    assert head + tail == second.read(5_010)
    assert sampling.XofStream(b"other").read(10) != head


def test_uniform_poly_is_in_range_and_not_constant() -> None:
    poly = _uniform(b"range", n=1024)
    assert poly.dtype == np.int64 and poly.shape == (1024,)
    assert 0 <= int(poly.min()) and int(poly.max()) < TOY_Q
    assert len(set(poly.tolist())) > 1000


def test_ternary_vector_is_balanced() -> None:
    values = sampling.ternary_vector(sampling.XofStream(b"t"), (3, 4096))
    assert values.shape == (3, 4096)
    assert set(np.unique(values).tolist()) == {-1, 0, 1}
    counts = [int((values == v).sum()) for v in (-1, 0, 1)]
    assert all(abs(count - 4096) < 400 for count in counts)


def test_mask_vector_covers_exact_interval() -> None:
    gamma = 1 << 4
    values = sampling.mask_vector(sampling.XofStream(b"m"), gamma, (2, 8192))
    assert int(values.min()) == -gamma + 1 and int(values.max()) == gamma
    with pytest.raises(ValueError):
        sampling.mask_vector(sampling.XofStream(b"m"), 1000, (1, 8))


def test_challenge_has_fixed_weight_and_depends_on_seed() -> None:
    first = sampling.challenge_poly(b"\x01" * 32, 1024, 36)
    again = sampling.challenge_poly(b"\x01" * 32, 1024, 36)
    other = sampling.challenge_poly(b"\x02" * 32, 1024, 36)
    assert np.array_equal(first, again) and not np.array_equal(first, other)
    assert int(np.abs(first).sum()) == 36 and int(np.abs(first).max()) == 1
    assert {-1, 1} <= set(first.tolist())


def test_challenge_differences_are_invertible() -> None:
    challenges = [sampling.challenge_poly(bytes([i]) * 32, TOY_N, 12) for i in range(12)]
    for i, left in enumerate(challenges):
        for right in challenges[i + 1:]:
            assert ring.is_invertible((left - right) % TOY_Q, TOY_Q)
    assert not ring.is_invertible(np.zeros(TOY_N, dtype=np.int64), TOY_Q)


def test_is_invertible_detects_a_zero_divisor() -> None:
    root = ring.sqrt_minus_one(TOY_Q)
    factor = np.zeros(TOY_N, dtype=np.int64)
    factor[TOY_N // 2] = 1
    factor[0] = (TOY_Q - root) % TOY_Q  # X^(N/2) - r divides X^N + 1
    assert not ring.is_invertible(factor, TOY_Q)
