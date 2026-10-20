"""Exact arithmetic in R_q = Z_q[X]/(X^N + 1).

Polynomials are ``int64`` arrays of N coefficients in ``[0, q)``.  The modulus
is a prime ``q = 5 (mod 8)``, so X^N + 1 splits into exactly two irreducible
factors and every nonzero element of infinity norm below ``sqrt(q/2)`` is
invertible (Lyubashevsky-Seiler, EUROCRYPT 2018, Corollary 1.2 with k = 2).
That rules out a full NTT; products use exact big-integer Kronecker
substitution instead.
"""

from __future__ import annotations

import numpy as np

_MILLER_RABIN_BASES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)
MAX_MODULUS_BITS = 62


def _is_prime(value: int) -> bool:
    if value < 2:
        return False
    for base in _MILLER_RABIN_BASES:
        if value % base == 0:
            return value == base
    odd, twos = value - 1, 0
    while odd % 2 == 0:
        odd //= 2
        twos += 1
    for base in _MILLER_RABIN_BASES:
        witness = pow(base, odd, value)
        if witness in (1, value - 1):
            continue
        for _ in range(twos - 1):
            witness = witness * witness % value
            if witness == value - 1:
                break
        else:
            return False
    return True


def validate_modulus(q: int) -> None:
    """Require the two-factor splitting condition used by the binding argument."""
    if not isinstance(q, int) or q.bit_length() > MAX_MODULUS_BITS:
        raise ValueError("modulus must be an integer below 2^62")
    if q % 8 != 5 or not _is_prime(q):
        raise ValueError("modulus must be a prime congruent to 5 modulo 8")


def sqrt_minus_one(q: int) -> int:
    """Return r with r^2 = -1 (mod q); X^N + 1 = (X^(N/2) - r)(X^(N/2) + r)."""
    validate_modulus(q)
    # 2 is a quadratic non-residue for q = 5 (mod 8).
    root = pow(2, (q - 1) // 4, q)
    if root * root % q != q - 1:
        raise ArithmeticError("failed to derive a square root of -1")
    return root


def center(values: np.ndarray, q: int) -> np.ndarray:
    """Map residues to the symmetric interval [-(q-1)/2, (q-1)/2]."""
    reduced = np.asarray(values, dtype=np.int64) % q
    return np.where(reduced > q // 2, reduced - q, reduced)


def _pack(poly: np.ndarray, limb_bytes: int) -> int:
    raw = poly.astype("<u8").view(np.uint8).reshape(len(poly), 8)
    if limb_bytes <= 8:
        limbs = raw[:, :limb_bytes]
    else:
        limbs = np.zeros((len(poly), limb_bytes), dtype=np.uint8)
        limbs[:, :8] = raw
    return int.from_bytes(limbs.tobytes(), "little")


def poly_mul(a: np.ndarray, b: np.ndarray, q: int) -> np.ndarray:
    """Negacyclic product of two reduced polynomials."""
    degree = len(a)
    if len(b) != degree:
        raise ValueError("polynomial degrees differ")
    limb_bytes = (degree * (q - 1) ** 2).bit_length() // 8 + 1
    product = _pack(a, limb_bytes) * _pack(b, limb_bytes)
    raw = product.to_bytes(2 * degree * limb_bytes, "little")
    wide = [
        int.from_bytes(raw[offset:offset + limb_bytes], "little")
        for offset in range(0, len(raw), limb_bytes)
    ]
    return np.array(
        [(wide[index] - wide[index + degree]) % q for index in range(degree)],
        dtype=np.int64,
    )


def mat_vec(matrix: np.ndarray, vector: np.ndarray, q: int) -> np.ndarray:
    """Multiply a (rows, cols, N) matrix by a (cols, N) vector."""
    rows, cols, degree = matrix.shape
    if vector.shape != (cols, degree):
        raise ValueError("matrix and vector shapes are incompatible")
    result = np.zeros((rows, degree), dtype=np.int64)
    for row in range(rows):
        for col in range(cols):
            result[row] = (result[row] + poly_mul(matrix[row, col], vector[col], q)) % q
    return result


def is_invertible(poly: np.ndarray, q: int) -> bool:
    """Decide invertibility through the two CRT components of R_q."""
    root = sqrt_minus_one(q)
    half = len(poly) // 2
    low = [int(value) % q for value in poly[:half]]
    high = [int(value) % q for value in poly[half:]]
    plus = any((lo + root * hi) % q for lo, hi in zip(low, high))
    minus = any((lo - root * hi) % q for lo, hi in zip(low, high))
    return plus and minus
