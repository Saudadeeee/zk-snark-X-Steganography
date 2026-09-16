"""Lattice-based cryptographic primitives for the post-quantum video path.

This module uses the ML-DSA-65 and ML-KEM-768 implementations provided by
``pqcrypto``.  A complete ML-DSA attestation is intentionally kept in a
sidecar: its multi-kilobyte signature cannot fit into the constrained CAVLC
payload used by this project.  The video carries a 32-byte commitment that
binds it to the exact signed receipt.

ML-DSA is an authentication primitive, not a replacement for a general
zero-knowledge proof.  The lattice path therefore calls its artifact an
*attestation receipt*, never a ZK proof.
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pqcrypto.kem import ml_kem_768
from pqcrypto.sign import ml_dsa_65


LATTICE_SIGNATURE_ALGORITHM = "ML-DSA-65"
LATTICE_KEM_ALGORITHM = "ML-KEM-768"
LATTICE_RECEIPT_VERSION = "1.0.0"
LATTICE_REFERENCE_MAGIC = b"LQ1"
LATTICE_REFERENCE_SIZE = 32


def _canonical_json_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha3_512_hex(data: bytes) -> str:
    return hashlib.sha3_512(data).hexdigest()


def _sha3_256(data: bytes) -> bytes:
    return hashlib.sha3_256(data).digest()


class LatticeSigner:
    """Strict ML-DSA-65 key handling and detached signatures."""

    @staticmethod
    def generate_keypair() -> tuple[bytes, bytes]:
        public_key, private_key = ml_dsa_65.keygen()
        return bytes(public_key), bytes(private_key)

    @staticmethod
    def sign(private_key: bytes, data: bytes) -> bytes:
        if not isinstance(private_key, bytes) or len(private_key) != ml_dsa_65.SECRET_KEY_SIZE:
            raise ValueError(f"ML-DSA-65 private key must be {ml_dsa_65.SECRET_KEY_SIZE} bytes")
        if not isinstance(data, bytes):
            raise TypeError("signed data must be bytes")
        return bytes(ml_dsa_65.sign(private_key, data))

    @staticmethod
    def verify(public_key: bytes, data: bytes, signature: bytes) -> bool:
        if not isinstance(public_key, bytes) or len(public_key) != ml_dsa_65.PUBLIC_KEY_SIZE:
            raise ValueError(f"ML-DSA-65 public key must be {ml_dsa_65.PUBLIC_KEY_SIZE} bytes")
        if not isinstance(signature, bytes) or len(signature) != ml_dsa_65.SIGNATURE_SIZE:
            return False
        if not isinstance(data, bytes):
            raise TypeError("verified data must be bytes")
        try:
            ml_dsa_65.verify(public_key, data, signature)
        except ValueError:
            return False
        return True


class LatticeKem:
    """ML-KEM-768 encapsulation for authenticated transport key establishment."""

    @staticmethod
    def generate_keypair() -> tuple[bytes, bytes]:
        public_key, private_key = ml_kem_768.keygen()
        return bytes(public_key), bytes(private_key)

    @staticmethod
    def encapsulate(public_key: bytes) -> tuple[bytes, bytes]:
        if not isinstance(public_key, bytes) or len(public_key) != ml_kem_768.PUBLIC_KEY_SIZE:
            raise ValueError(f"ML-KEM-768 public key must be {ml_kem_768.PUBLIC_KEY_SIZE} bytes")
        capsule, shared_secret = ml_kem_768.encaps(public_key)
        return bytes(capsule), bytes(shared_secret)

    @staticmethod
    def decapsulate(private_key: bytes, capsule: bytes) -> bytes:
        if not isinstance(private_key, bytes) or len(private_key) != ml_kem_768.SECRET_KEY_SIZE:
            raise ValueError(f"ML-KEM-768 private key must be {ml_kem_768.SECRET_KEY_SIZE} bytes")
        if not isinstance(capsule, bytes) or len(capsule) != ml_kem_768.CIPHERTEXT_SIZE:
            raise ValueError(f"ML-KEM-768 capsule must be {ml_kem_768.CIPHERTEXT_SIZE} bytes")
        return bytes(ml_kem_768.decaps(private_key, capsule))


@dataclass(frozen=True)
class LatticeReceipt:
    """ML-DSA attestation for a message, stored outside the video payload."""

    version: str
    signature_algorithm: str
    signer_id: str
    message_hash: str
    signature: str

    @classmethod
    def create(cls, message: bytes, private_key: bytes, *, signer_id: str = "ml-dsa-65") -> "LatticeReceipt":
        if not isinstance(message, bytes) or not message:
            raise ValueError("message must be non-empty bytes")
        unsigned = {
            "version": LATTICE_RECEIPT_VERSION,
            "signature_algorithm": LATTICE_SIGNATURE_ALGORITHM,
            "signer_id": signer_id,
            "message_hash": _sha3_512_hex(message),
        }
        signature = LatticeSigner.sign(private_key, _canonical_json_bytes(unsigned))
        return cls(signature=base64.b64encode(signature).decode("ascii"), **unsigned)

    def _unsigned_dict(self) -> dict[str, str]:
        return {
            "version": self.version,
            "signature_algorithm": self.signature_algorithm,
            "signer_id": self.signer_id,
            "message_hash": self.message_hash,
        }

    def to_dict(self) -> dict[str, str]:
        return {**self._unsigned_dict(), "signature": self.signature}

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "LatticeReceipt":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LatticeReceipt":
        return cls(
            version=str(data["version"]),
            signature_algorithm=str(data["signature_algorithm"]),
            signer_id=str(data["signer_id"]),
            message_hash=str(data["message_hash"]),
            signature=str(data["signature"]),
        )

    def commitment(self) -> bytes:
        """Return the exact 32-byte value embedded into the stego payload."""
        return _sha3_256(_canonical_json_bytes(self.to_dict()))

    def verify(self, message: bytes, public_key: bytes) -> bool:
        if self.version != LATTICE_RECEIPT_VERSION or self.signature_algorithm != LATTICE_SIGNATURE_ALGORITHM:
            return False
        if not isinstance(message, bytes) or _sha3_512_hex(message) != self.message_hash:
            return False
        try:
            signature = base64.b64decode(self.signature.encode("ascii"), validate=True)
        except ValueError:
            return False
        return LatticeSigner.verify(public_key, _canonical_json_bytes(self._unsigned_dict()), signature)


def pack_lattice_reference(message: bytes, receipt_commitment: bytes) -> bytes:
    """Pack a message and signed-receipt binding for H.264 embedding."""
    if not isinstance(message, bytes) or not message:
        raise ValueError("message must be non-empty bytes")
    if not isinstance(receipt_commitment, bytes) or len(receipt_commitment) != LATTICE_REFERENCE_SIZE:
        raise ValueError(f"receipt_commitment must be exactly {LATTICE_REFERENCE_SIZE} bytes")
    return LATTICE_REFERENCE_MAGIC + struct.pack(">I", len(message)) + message + receipt_commitment


def unpack_lattice_reference(blob: bytes) -> tuple[bytes, bytes]:
    """Unpack a lattice video reference and reject trailing ambiguity."""
    header_size = len(LATTICE_REFERENCE_MAGIC) + 4
    if len(blob) < header_size + LATTICE_REFERENCE_SIZE or not blob.startswith(LATTICE_REFERENCE_MAGIC):
        raise ValueError("invalid lattice reference header")
    message_length = struct.unpack(">I", blob[len(LATTICE_REFERENCE_MAGIC):header_size])[0]
    expected_length = header_size + message_length + LATTICE_REFERENCE_SIZE
    if message_length == 0 or len(blob) != expected_length:
        raise ValueError("invalid lattice reference length")
    return blob[header_size:header_size + message_length], blob[-LATTICE_REFERENCE_SIZE:]
