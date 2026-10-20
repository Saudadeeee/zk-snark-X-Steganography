"""Exact batched arithmetic in R_q = Z_q[X]/(X^N + 1) through float64 matrix products.

Multiplication by ``a`` is the negacyclic Toeplitz matrix ``T_a``.  Each
reduced coefficient is split into two 15-bit limbs, so every entry of a limb
matrix and every limb of the other operand is below ``2^15`` and a product of
``K`` limb terms is an integer of magnitude below ``K * 2^30``.  At most
``MAX_TERMS`` terms are summed (checked), which keeps every partial sum an
integer below ``2^53``: float64 represents it exactly, so the BLAS result is exact and
independent of the summation order.  The limbs are recombined with ``int64``
arithmetic modulo ``q``.

Only moduli below ``2^30`` take this path; :func:`ring.poly_mul` stays the
reference implementation and the tests compare both.
"""

from __future__ import annotations

import numpy as np

LIMB_BITS = 15
MAX_MODULUS = 1 << (2 * LIMB_BITS)
# The middle limb weight adds two products, so 2 K (2^15 - 1)^2 < 2^53 is required.
MAX_TERMS = (1 << 53) // (2 * ((1 << LIMB_BITS) - 1) ** 2)


def _check_modulus(q: int) -> None:
    if not 2 < q <= MAX_MODULUS:
        raise ValueError("fast_ring needs a modulus below 2^30")


def _limbs(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    low = (values & ((1 << LIMB_BITS) - 1)).astype(np.float64)
    high = (values >> LIMB_BITS).astype(np.float64)
    return low, high


def _toeplitz_block(limb: np.ndarray) -> np.ndarray:
    """``T_a`` for one limb polynomial: entry (i, j) is a[i-j], or -a[N+i-j] when i < j."""
    degree = len(limb)
    # ext[k] = T[i, j] for k = i - j + N - 1.
    extended = np.concatenate([-limb[1:], limb])
    start = extended[degree - 1:]
    step = extended.strides[0]
    return np.lib.stride_tricks.as_strided(start, (degree, degree), (step, -step), writeable=False)


def _stacked_toeplitz(polys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Limb matrices ``[T_a0 | T_a1 | ...]`` of shape (N, M*N) for a (M, N) array."""
    count, degree = polys.shape
    low, high = _limbs(polys)
    stacked = (np.empty((degree, count * degree)), np.empty((degree, count * degree)))
    for target, limbs in zip(stacked, (low, high)):
        for index in range(count):
            target[:, index * degree:(index + 1) * degree] = _toeplitz_block(limbs[index])
    return stacked


def _recombine(products: dict[int, np.ndarray], q: int) -> np.ndarray:
    """Map limb products of weight 2^(15 w) back to residues modulo q."""
    total = np.zeros(products[0].shape, dtype=np.int64)
    for weight, value in products.items():
        exact = np.rint(value).astype(np.int64) % q
        total = (total + exact * (pow(2, LIMB_BITS * weight, q))) % q
    return total


def _reduced(values: np.ndarray, q: int) -> np.ndarray:
    values = np.asarray(values, dtype=np.int64)
    if values.size and (int(values.min()) < 0 or int(values.max()) >= q):
        raise ValueError("fast_ring operands must be reduced modulo q")
    return values


def _check_terms(count: int) -> None:
    if count > MAX_TERMS:
        raise ValueError("too many terms for an exact float64 sum")


def _limb_product(toeplitz: tuple[np.ndarray, np.ndarray], operand: np.ndarray, q: int) -> np.ndarray:
    """Exact ``[T_a0 | T_a1 | ...] @ operand`` modulo q for a reduced (K, X) operand."""
    t_low, t_high = toeplitz
    o_low, o_high = _limbs(operand)
    products = {
        0: t_low @ o_low,
        1: t_low @ o_high + t_high @ o_low,
        2: t_high @ o_high,
    }
    return _recombine(products, q)


def matvec(matrix: np.ndarray, vector: np.ndarray, q: int) -> np.ndarray:
    """Return ``sum_c matrix[r, c] * vector[c]`` for a (R, C, N) matrix and a (C, N) vector."""
    _check_modulus(q)
    matrix, vector = _reduced(matrix, q), _reduced(vector, q)
    rows, cols, degree = matrix.shape
    if vector.shape != (cols, degree):
        raise ValueError("matrix and vector shapes are incompatible")
    _check_terms(cols * degree)
    # sum_c T_{v_c} m_{r,c}: stack the Toeplitz blocks of v and the columns of m.
    operand = matrix.transpose(1, 2, 0).reshape(cols * degree, rows)
    return _limb_product(_stacked_toeplitz(vector), operand, q).T.copy()


def scale(poly: np.ndarray, vector: np.ndarray, q: int) -> np.ndarray:
    """Return ``poly * vector[i]`` for every row of a (M, N) vector."""
    _check_modulus(q)
    poly, vector = _reduced(poly, q), _reduced(vector, q)
    if vector.ndim != 2 or poly.shape != (vector.shape[1],):
        raise ValueError("scale needs a polynomial and a (M, N) vector")
    _check_terms(len(poly))
    return _limb_product(_stacked_toeplitz(poly[np.newaxis, :]), vector.T, q).T.copy()


def mul(first: np.ndarray, second: np.ndarray, q: int) -> np.ndarray:
    """Negacyclic product of two reduced polynomials."""
    return scale(first, np.asarray(second, dtype=np.int64)[np.newaxis, :], q)[0]


def dot(first: np.ndarray, second: np.ndarray, q: int) -> np.ndarray:
    """Return ``sum_c first[c] * second[c]`` for two (C, N) vectors."""
    return matvec(np.asarray(first, dtype=np.int64)[np.newaxis], second, q)[0]
