"""Pinned parameter sets for the BDLOP commitment and its opening proof.

Notation follows Baum et al. (SCN 2018): ring degree N, modulus q, M-SIS rank
n, M-LWE rank lam, one message polynomial, randomness width k = n + lam + 1,
ternary randomness, challenges with ``kappa`` coefficients +-1.  The Gaussian
masking of the paper is replaced by ML-DSA style uniform masking in
``[-gamma + 1, gamma]`` with acceptance iff ``||z||_inf <= gamma - kappa - 1``.
"""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from functools import cached_property

from .ring import validate_modulus

_PARAMETER_DOMAIN = b"zkstego/lattice-zk/bdlop-open/v1/parameters\0"
CHALLENGE_SEED_BYTES = 32
MIN_CHALLENGE_SPACE_BITS = 256
PAYLOAD_LENGTH_BYTES = 2
MAX_NAME_BYTES = 0xFFFF
# Widths of the big-endian fields that ``parameter_id`` packs each value into.
_INTEGER_FIELDS = (
    ("degree", 32), ("modulus", 64), ("msis_rank", 32),
    ("mlwe_rank", 32), ("challenge_weight", 32), ("mask_bound", 64),
)


@dataclass(frozen=True)
class BdlopParams:
    name: str
    degree: int
    modulus: int
    msis_rank: int
    mlwe_rank: int
    challenge_weight: int
    mask_bound: int
    setup_seed: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or not self.name.isascii():
            raise ValueError("parameter set name must be a non-empty ASCII string")
        if len(self.name) > MAX_NAME_BYTES:
            raise ValueError("parameter set name is too long")
        for field, bits in _INTEGER_FIELDS:
            value = getattr(self, field)
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < 1 << bits:
                raise ValueError(f"{field} must be an unsigned {bits}-bit integer")
        if self.degree < 4 or self.degree & (self.degree - 1):
            raise ValueError("ring degree must be a power of two")
        validate_modulus(self.modulus)
        if self.msis_rank < 1 or self.mlwe_rank < 1:
            raise ValueError("module ranks must be positive")
        if not 0 < self.challenge_weight <= self.degree:
            raise ValueError("challenge weight is out of range")
        if self.mask_bound & (self.mask_bound - 1) or self.response_bound < 1:
            raise ValueError("mask bound must be a power of two above the shift bound")
        if not isinstance(self.setup_seed, bytes) or len(self.setup_seed) != 32:
            raise ValueError("setup seed must be exactly 32 bytes")
        # Challenge differences (infinity norm <= 2) must be invertible.
        if 2 * math.sqrt(2) >= math.sqrt(self.modulus):
            raise ValueError("modulus is too small for invertible challenge differences")
        # The M-SIS solution derived from two relaxed openings must not wrap.
        if 2 * self.binding_norm_bound >= self.modulus:
            raise ValueError("modulus is too small for the binding norm bound")

    @property
    def width(self) -> int:
        """Randomness width k."""
        return self.msis_rank + self.mlwe_rank + 1

    @property
    def shift_bound(self) -> int:
        """Worst-case ||c * r||_inf for ternary r."""
        return self.challenge_weight

    @property
    def response_bound(self) -> int:
        """Largest accepted |z| coefficient."""
        return self.mask_bound - self.shift_bound - 1

    @property
    def binding_norm_bound(self) -> int:
        """Infinity norm of f' * rbar - f * rbar' for two relaxed openings."""
        return 8 * self.challenge_weight * self.response_bound

    @property
    def modulus_bits(self) -> int:
        return (self.modulus - 1).bit_length()

    @property
    def response_bits(self) -> int:
        return (2 * self.response_bound).bit_length()

    @property
    def commitment_bytes(self) -> int:
        return ((self.msis_rank + 1) * self.degree * self.modulus_bits + 7) // 8

    @property
    def proof_bytes(self) -> int:
        return CHALLENGE_SEED_BYTES + (self.width * self.degree * self.response_bits + 7) // 8

    @property
    def payload_bytes_per_coefficient(self) -> int:
        return (self.modulus_bits - 1) // 8

    @property
    def max_payload_bytes(self) -> int:
        return self.degree * self.payload_bytes_per_coefficient - PAYLOAD_LENGTH_BYTES

    @property
    def challenge_space_bits(self) -> float:
        return math.log2(math.comb(self.degree, self.challenge_weight)) + self.challenge_weight

    @property
    def acceptance_probability(self) -> float:
        """Lower bound on the per-attempt acceptance probability."""
        kept = (2 * self.response_bound + 1) / (2 * self.mask_bound)
        return kept ** (self.width * self.degree)

    @cached_property
    def parameter_id(self) -> bytes:
        """Digest pinning every value that changes the proved relation."""
        name = self.name.encode("ascii")
        encoded = struct.pack(
            ">H", len(name)
        ) + name + struct.pack(
            ">IQIIIQ",
            self.degree,
            self.modulus,
            self.msis_rank,
            self.mlwe_rank,
            self.challenge_weight,
            self.mask_bound,
        ) + self.setup_seed
        return hashlib.sha3_256(_PARAMETER_DOMAIN + encoded).digest()

    def require_production_strength(self) -> None:
        """Reject toy sets where a negligible soundness error is required."""
        if self.challenge_space_bits < MIN_CHALLENGE_SPACE_BITS:
            raise ValueError("challenge space is below 2^256")


def _setup_seed(label: str) -> bytes:
    return hashlib.sha3_256(_PARAMETER_DOMAIN + b"setup-seed\0" + label.encode("ascii")).digest()


# Production set.  Core-SVP estimates from research/bdlop_params/estimate.py
# (CRYSTALS security-estimates model): M-SIS binding 140 classical / 127
# quantum bits in the infinity norm, M-LWE hiding 138 / 125 bits.
BDLOP_OPEN_128 = BdlopParams(
    name="bdlop-open-128-v1",
    degree=256,
    modulus=(1 << 30) - 35,
    msis_rank=6,
    mlwe_rank=6,
    challenge_weight=60,
    mask_bound=1 << 17,
    setup_seed=_setup_seed("bdlop-open-128-v1"),
)

# Fast, insecure set for unit tests only.
TOY = BdlopParams(
    name="bdlop-open-toy-v1",
    degree=64,
    modulus=1_048_573,
    msis_rank=1,
    mlwe_rank=1,
    challenge_weight=12,
    mask_bound=1 << 12,
    setup_seed=_setup_seed("bdlop-open-toy-v1"),
)
