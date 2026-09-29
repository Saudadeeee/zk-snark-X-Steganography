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
import secrets
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

# Transparent lattice proof parameters.  These are deliberately explicit in
# every proof artifact so verifier code never silently negotiates a weaker
# relation.  They define a compact SIS proof-of-knowledge relation, not a
# NIST-standard general-purpose zkSNARK parameter set.
LATTICE_ZKP_VERSION = "1.0.0"
LATTICE_ZKP_PROTOCOL = "sis-linear-fiat-shamir-v1"
LATTICE_ZKP_Q = 8_380_417  # The prime modulus used by ML-DSA.
LATTICE_ZKP_ROWS = 64
LATTICE_ZKP_COLS = 128
LATTICE_ZKP_ROUNDS = 128
LATTICE_ZKP_WITNESS_BOUND = 1
LATTICE_ZKP_MASK_BOUND = 1 << 20
LATTICE_ZKP_RESPONSE_BOUND = LATTICE_ZKP_MASK_BOUND - LATTICE_ZKP_WITNESS_BOUND
_LATTICE_ZKP_DOMAIN = b"zkstego/lattice-zkp/sis-linear-fs/v1/"


def _canonical_json_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha3_512_hex(data: bytes) -> str:
    return hashlib.sha3_512(data).hexdigest()


def _sha3_256(data: bytes) -> bytes:
    return hashlib.sha3_256(data).digest()


def _b64encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64decode(value: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError("encoded proof field must be a string")
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except ValueError as error:
        raise ValueError("invalid base64 proof field") from error


def _pack_mod_q(values: list[int]) -> bytes:
    if any(not isinstance(value, int) or not 0 <= value < LATTICE_ZKP_Q for value in values):
        raise ValueError("invalid modular vector")
    return b"".join(struct.pack(">I", value) for value in values)


def _unpack_mod_q(data: bytes, expected_count: int) -> list[int]:
    if len(data) != expected_count * 4:
        raise ValueError("invalid modular vector length")
    values = list(struct.unpack(f">{expected_count}I", data))
    if any(value >= LATTICE_ZKP_Q for value in values):
        raise ValueError("modular vector coefficient is outside q")
    return values


def _pack_signed(values: list[int]) -> bytes:
    if any(not isinstance(value, int) or not -LATTICE_ZKP_RESPONSE_BOUND <= value <= LATTICE_ZKP_RESPONSE_BOUND for value in values):
        raise ValueError("invalid response vector")
    return b"".join(struct.pack(">i", value) for value in values)


def _unpack_signed(data: bytes, expected_count: int) -> list[int]:
    if len(data) != expected_count * 4:
        raise ValueError("invalid response vector length")
    values = list(struct.unpack(f">{expected_count}i", data))
    if any(abs(value) > LATTICE_ZKP_RESPONSE_BOUND for value in values):
        raise ValueError("response vector exceeds rejection bound")
    return values


def _message_hash(message: bytes) -> bytes:
    if not isinstance(message, bytes) or not message:
        raise ValueError("message must be non-empty bytes")
    return hashlib.sha3_256(_LATTICE_ZKP_DOMAIN + b"message/" + message).digest()


def _derive_matrix(message_hash: bytes) -> list[list[int]]:
    """Derive the public SIS matrix from the exact payload hash."""
    count = LATTICE_ZKP_ROWS * LATTICE_ZKP_COLS
    stream = hashlib.shake_256(_LATTICE_ZKP_DOMAIN + b"matrix/" + message_hash).digest(count * 4)
    values = [struct.unpack_from(">I", stream, offset)[0] % LATTICE_ZKP_Q for offset in range(0, len(stream), 4)]
    return [values[index:index + LATTICE_ZKP_COLS] for index in range(0, count, LATTICE_ZKP_COLS)]


def _derive_witness(witness_key: bytes, message_hash: bytes) -> list[int]:
    if not isinstance(witness_key, bytes) or len(witness_key) != 32:
        raise ValueError("lattice ZKP witness key must be exactly 32 bytes")
    raw = hashlib.shake_256(_LATTICE_ZKP_DOMAIN + b"witness/" + witness_key + message_hash).digest(LATTICE_ZKP_COLS)
    # Ternary, short witness.  The verifier only learns that a bounded witness
    # exists; the key-derived vector itself is never serialized.
    return [int(byte % 3) - 1 for byte in raw]


def _matrix_vector_product(matrix: list[list[int]], vector: list[int]) -> list[int]:
    return [sum(coefficient * value for coefficient, value in zip(row, vector)) % LATTICE_ZKP_Q for row in matrix]


def _challenge_bits(message_hash: bytes, statement: list[int], commitments: list[int]) -> list[int]:
    transcript = (
        _LATTICE_ZKP_DOMAIN
        + b"challenge/"
        + message_hash
        + _pack_mod_q(statement)
        + _pack_mod_q(commitments)
    )
    digest = hashlib.shake_256(transcript).digest((LATTICE_ZKP_ROUNDS + 7) // 8)
    return [(digest[index // 8] >> (index % 8)) & 1 for index in range(LATTICE_ZKP_ROUNDS)]


@dataclass(frozen=True)
class LatticeZkProof:
    """Experimental transparent Fiat-Shamir proof for a bounded SIS preimage.

    The public statement is ``t = A(message) * x mod q``.  ``A`` is derived
    from the payload hash, while the prover's intended ``x`` is a ternary
    vector derived from a local 32-byte witness key.  For every Fiat-Shamir challenge bit the prover sends
    ``z = y + c*x`` and uses rejection sampling, so accepted responses are in
    a common interval independent of ``x``.  Thus the serialized transcript
    contains no witness vector.  The verifier's response bound establishes a
    bounded modular preimage relation; this prototype does not constitute a
    parameterized, independently-audited proof that the preimage is ternary.
    It is intentionally scoped to this linear relation and does *not* claim
    to prove H.264 codec execution.
    """

    version: str
    protocol: str
    q: int
    rows: int
    cols: int
    rounds: int
    witness_bound: int
    mask_bound: int
    message_hash: str
    statement: str
    commitments: str
    responses: str

    @classmethod
    def create(cls, message: bytes, witness_key: bytes) -> "LatticeZkProof":
        message_hash = _message_hash(message)
        matrix = _derive_matrix(message_hash)
        witness = _derive_witness(witness_key, message_hash)
        statement = _matrix_vector_product(matrix, witness)

        # Rejection sampling restricts every accepted z coordinate to the
        # intersection [-B+W, B-W], whose distribution is independent of the
        # witness for all |x_i| <= W and c in {0, 1}.
        for _attempt in range(1_000):
            masks: list[list[int]] = [
                [secrets.randbelow(2 * LATTICE_ZKP_MASK_BOUND + 1) - LATTICE_ZKP_MASK_BOUND for _ in range(LATTICE_ZKP_COLS)]
                for _ in range(LATTICE_ZKP_ROUNDS)
            ]
            commitments = [coefficient for mask in masks for coefficient in _matrix_vector_product(matrix, mask)]
            challenges = _challenge_bits(message_hash, statement, commitments)
            responses = [
                mask_value + challenge * witness_value
                for challenge, mask in zip(challenges, masks)
                for mask_value, witness_value in zip(mask, witness)
            ]
            if all(abs(value) <= LATTICE_ZKP_RESPONSE_BOUND for value in responses):
                return cls(
                    version=LATTICE_ZKP_VERSION,
                    protocol=LATTICE_ZKP_PROTOCOL,
                    q=LATTICE_ZKP_Q,
                    rows=LATTICE_ZKP_ROWS,
                    cols=LATTICE_ZKP_COLS,
                    rounds=LATTICE_ZKP_ROUNDS,
                    witness_bound=LATTICE_ZKP_WITNESS_BOUND,
                    mask_bound=LATTICE_ZKP_MASK_BOUND,
                    message_hash=message_hash.hex(),
                    statement=_b64encode(_pack_mod_q(statement)),
                    commitments=_b64encode(_pack_mod_q(commitments)),
                    responses=_b64encode(_pack_signed(responses)),
                )
        raise RuntimeError("lattice ZKP rejection sampler exhausted")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "protocol": self.protocol,
            "q": self.q,
            "rows": self.rows,
            "cols": self.cols,
            "rounds": self.rounds,
            "witness_bound": self.witness_bound,
            "mask_bound": self.mask_bound,
            "message_hash": self.message_hash,
            "statement": self.statement,
            "commitments": self.commitments,
            "responses": self.responses,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LatticeZkProof":
        return cls(
            version=str(data["version"]), protocol=str(data["protocol"]), q=int(data["q"]),
            rows=int(data["rows"]), cols=int(data["cols"]), rounds=int(data["rounds"]),
            witness_bound=int(data["witness_bound"]), mask_bound=int(data["mask_bound"]),
            message_hash=str(data["message_hash"]), statement=str(data["statement"]),
            commitments=str(data["commitments"]), responses=str(data["responses"]),
        )

    def verify(self, message: bytes) -> bool:
        if (
            self.version != LATTICE_ZKP_VERSION or self.protocol != LATTICE_ZKP_PROTOCOL
            or (self.q, self.rows, self.cols, self.rounds, self.witness_bound, self.mask_bound)
            != (LATTICE_ZKP_Q, LATTICE_ZKP_ROWS, LATTICE_ZKP_COLS, LATTICE_ZKP_ROUNDS, LATTICE_ZKP_WITNESS_BOUND, LATTICE_ZKP_MASK_BOUND)
        ):
            return False
        message_hash = _message_hash(message)
        if not secrets.compare_digest(self.message_hash, message_hash.hex()):
            return False
        try:
            statement = _unpack_mod_q(_b64decode(self.statement), LATTICE_ZKP_ROWS)
            commitments = _unpack_mod_q(_b64decode(self.commitments), LATTICE_ZKP_ROUNDS * LATTICE_ZKP_ROWS)
            responses = _unpack_signed(_b64decode(self.responses), LATTICE_ZKP_ROUNDS * LATTICE_ZKP_COLS)
        except (KeyError, ValueError, struct.error):
            return False
        # The homogeneous zero relation has a universal zero witness and is
        # therefore never an admissible experimental statement.
        if not any(statement):
            return False
        matrix = _derive_matrix(message_hash)
        challenges = _challenge_bits(message_hash, statement, commitments)
        for round_index, challenge in enumerate(challenges):
            response = responses[round_index * LATTICE_ZKP_COLS:(round_index + 1) * LATTICE_ZKP_COLS]
            commitment = commitments[round_index * LATTICE_ZKP_ROWS:(round_index + 1) * LATTICE_ZKP_ROWS]
            expected = [(value + challenge * statement_value) % LATTICE_ZKP_Q for value, statement_value in zip(commitment, statement)]
            if _matrix_vector_product(matrix, response) != expected:
                return False
        return True


@dataclass(frozen=True)
class LatticeZkReceipt:
    """Research-only receipt wrapping an unreviewed SIS proof prototype.

    The ML-DSA signature authenticates the serialized receipt; it does not
    upgrade the experimental proof relation into a reviewed application ZKP.
    Public ``embed()``/``verify()`` APIs do not enable this artifact as a
    lattice-ZK backend.
    """

    version: str
    protocol: str
    signature_algorithm: str
    signer_id: str
    message_hash: str
    proof: dict[str, Any]
    signature: str

    @classmethod
    def create(
        cls, message: bytes, witness_key: bytes, private_key: bytes, *, signer_id: str = "ml-dsa-65"
    ) -> "LatticeZkReceipt":
        proof = LatticeZkProof.create(message, witness_key)
        unsigned = {
            "version": LATTICE_ZKP_VERSION,
            "protocol": LATTICE_ZKP_PROTOCOL,
            "signature_algorithm": LATTICE_SIGNATURE_ALGORITHM,
            "signer_id": signer_id,
            "message_hash": proof.message_hash,
            "proof": proof.to_dict(),
        }
        signature = LatticeSigner.sign(private_key, _canonical_json_bytes(unsigned))
        return cls(signature=_b64encode(signature), **unsigned)

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "version": self.version, "protocol": self.protocol,
            "signature_algorithm": self.signature_algorithm, "signer_id": self.signer_id,
            "message_hash": self.message_hash, "proof": self.proof,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._unsigned_dict(), "signature": self.signature}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LatticeZkReceipt":
        return cls(
            version=str(data["version"]), protocol=str(data["protocol"]),
            signature_algorithm=str(data["signature_algorithm"]), signer_id=str(data["signer_id"]),
            message_hash=str(data["message_hash"]), proof=dict(data["proof"]), signature=str(data["signature"]),
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "LatticeZkReceipt":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def commitment(self) -> bytes:
        return _sha3_256(_canonical_json_bytes(self.to_dict()))

    def verify(self, message: bytes, public_key: bytes) -> bool:
        if (
            self.version != LATTICE_ZKP_VERSION or self.protocol != LATTICE_ZKP_PROTOCOL
            or self.signature_algorithm != LATTICE_SIGNATURE_ALGORITHM
        ):
            return False
        try:
            proof = LatticeZkProof.from_dict(self.proof)
            signature = _b64decode(self.signature)
        except (KeyError, TypeError, ValueError):
            return False
        if not secrets.compare_digest(self.message_hash, proof.message_hash):
            return False
        return proof.verify(message) and LatticeSigner.verify(public_key, _canonical_json_bytes(self._unsigned_dict()), signature)


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


def lattice_reference_bit_length(message: bytes) -> int:
    """Return the fixed extraction budget for a message's video reference."""
    if not isinstance(message, bytes):
        raise TypeError("message must be bytes")
    return (len(LATTICE_REFERENCE_MAGIC) + 4 + len(message) + LATTICE_REFERENCE_SIZE) * 8
