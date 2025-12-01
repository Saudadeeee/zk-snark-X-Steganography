"""
Minimal Schnorr proof system (Fiat–Shamir) for benchmarking against zkSNARKs.

The implementation works over the multiplicative group modulo a fixed
prime so that it has zero external dependencies. It is **not** intended
as a production-grade cryptographic primitive, but it provides a
deterministic, reproducible baseline for comparing proof sizes and
latency with the Groth16 pipeline.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# 255-bit prime close to 2^255; treated as the group modulus.
PRIME_MODULUS = 2**255 - 19
# Use phi(p) approximated as p - 1 for scalar arithmetic.
GROUP_ORDER = PRIME_MODULUS - 1
# Small generator that produces a large cycle under mod PRIME_MODULUS.
GENERATOR = 5


def _hash_to_scalar(*payloads: bytes, order: int = GROUP_ORDER) -> int:
    """Hash arbitrary byte payloads into a scalar modulo `order`."""
    hasher = hashlib.sha256()
    for chunk in payloads:
        hasher.update(chunk)
    digest = hasher.digest()
    return int.from_bytes(digest, "big") % order


@dataclass
class SchnorrProof:
    """Container returned by Schnorr prover."""

    commitment: int
    response: int

    def to_dict(self) -> Dict[str, str]:
        return {
            "commitment": hex(self.commitment),
            "response": hex(self.response),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "SchnorrProof":
        return cls(
            commitment=int(data["commitment"], 16),
            response=int(data["response"], 16),
        )


class SchnorrProofSystem:
    """
    Stateless Schnorr prover/verifier that runs entirely in Python.

    Attributes:
        generator: Group generator g.
        modulus:  Prime modulus p defining the multiplicative group.
        order:    Group order q used for scalar arithmetic.
    """

    def __init__(
        self,
        generator: int = GENERATOR,
        modulus: int = PRIME_MODULUS,
        order: int = GROUP_ORDER,
    ) -> None:
        self.generator = generator
        self.modulus = modulus
        self.order = order

    # ------------------------------------------------------------------ #
    # Key management
    # ------------------------------------------------------------------ #
    def generate_keypair(self) -> Tuple[int, int]:
        """Generate a random Schnorr keypair (secret scalar, public point)."""
        secret = secrets.randbelow(self.order - 2) + 1
        public = pow(self.generator, secret, self.modulus)
        return secret, public

    def derive_public(self, secret: int) -> int:
        """Derive the public key associated with `secret`."""
        return pow(self.generator, secret % self.order, self.modulus)

    # ------------------------------------------------------------------ #
    # Proof flow
    # ------------------------------------------------------------------ #
    def prove(
        self,
        statement_bytes: bytes,
        secret_key: int,
        nonce: Optional[int] = None,
    ) -> SchnorrProof:
        """
        Create a Schnorr proof w.r.t. the committed statement.

        Args:
            statement_bytes: Canonical serialization of the statement.
            secret_key:      Prover's private scalar.
            nonce:           Optional deterministic nonce (testing only).
        """
        sk = secret_key % self.order
        if nonce is None:
            nonce = secrets.randbelow(self.order - 1) + 1
        r = nonce % self.order

        commitment = pow(self.generator, r, self.modulus)
        challenge = _hash_to_scalar(
            commitment.to_bytes(32, "big"),
            statement_bytes,
        )
        response = (r + challenge * sk) % self.order
        return SchnorrProof(commitment=commitment, response=response)

    def verify(
        self,
        statement_bytes: bytes,
        public_key: int,
        proof: SchnorrProof,
    ) -> bool:
        """Verify Schnorr proof for the given statement."""
        challenge = _hash_to_scalar(
            proof.commitment.to_bytes(32, "big"),
            statement_bytes,
        )

        lhs = pow(self.generator, proof.response, self.modulus)
        rhs = (proof.commitment * pow(public_key, challenge, self.modulus)) % self.modulus
        return lhs == rhs

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def serialize_statement(self, data: Dict[str, int]) -> bytes:
        """
        Deterministically serialize a statement dictionary.

        Ensures prover and verifier hash identical bytes before invoking
        the Fiat–Shamir transform.
        """
        normalized = {k: int(v) for k, v in data.items()}
        return json.dumps(normalized, sort_keys=True).encode("utf-8")
