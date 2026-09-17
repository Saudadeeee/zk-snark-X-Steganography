"""Authenticated manifest schema for ZK-Stego video sidecars."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from .lattice_pq import LATTICE_SIGNATURE_ALGORITHM, LatticeSigner


MANIFEST_VERSION = "4.0.0"
"""Manifest v4 makes ML-DSA lattice-attestation metadata the default."""

SIGNATURE_ALGORITHM = "ml-dsa-65"
LEGACY_SIGNATURE_ALGORITHM = "ed25519"


@dataclass
class PayloadMetadata:
    message_length: int = 0
    bits_embedded: int = 0
    bits_required: int = 0
    chaos_enabled: bool = False
    chaos_original_bits: Optional[int] = None
    chaos_expansion_factor: float = 1.0


@dataclass
class EmbeddingMetadata:
    strategy: str = "t1_sign_flip"
    max_modifications_per_block: int = 1
    positions_count: int = 0
    positions_hash: Optional[str] = None
    validation_threshold_db: Optional[float] = None


@dataclass
class VideoMetadata:
    file_path: str = ""
    file_hash: str = ""  # SHA-256 of the original cover video
    stego_file_hash: Optional[str] = None
    codec: str = "h264"
    profile: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    frame_count: Optional[int] = None
    gop_size: Optional[int] = None
    qp_value: Optional[int] = None
    provenance_uri: Optional[str] = None
    provenance_root_hash: Optional[str] = None


@dataclass
class ProofMetadata:
    proof_system: str = "ml-dsa-65-attestation"
    proof_size_bytes: int = 0
    constraint_count: int = 0
    prove_time_ms: Optional[float] = None
    verify_time_ms: Optional[float] = None
    statement_id: Optional[str] = None


def canonical_json_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def hash_positions(positions: Sequence[Sequence[int]]) -> str:
    """Hash normalized embedding positions so their sidecar is authenticated."""
    normalized: list[list[int]] = []
    for position in positions:
        if len(position) != 3:
            raise ValueError("each embedding position must contain exactly three integers")
        if any(not isinstance(value, int) or isinstance(value, bool) for value in position):
            raise ValueError("each embedding position must contain exactly three integers")
        normalized.append(list(position))
    return hashlib.sha256(canonical_json_bytes({"positions": normalized})).hexdigest()


def _private_key(key: bytes | Ed25519PrivateKey) -> Ed25519PrivateKey:
    if isinstance(key, Ed25519PrivateKey):
        return key
    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        raise ValueError("Ed25519 private key must be a 32-byte seed or Ed25519PrivateKey")
    return Ed25519PrivateKey.from_private_bytes(bytes(key))


def _public_key(key: bytes | Ed25519PublicKey) -> Ed25519PublicKey:
    if isinstance(key, Ed25519PublicKey):
        return key
    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        raise ValueError("Ed25519 public key must be 32 bytes or Ed25519PublicKey")
    return Ed25519PublicKey.from_public_bytes(bytes(key))


@dataclass
class StegoManifest:
    """Versioned manifest bound to a stego asset and its positions sidecar."""

    version: str = MANIFEST_VERSION
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: PayloadMetadata = field(default_factory=PayloadMetadata)
    embedding: EmbeddingMetadata = field(default_factory=EmbeddingMetadata)
    video: VideoMetadata = field(default_factory=VideoMetadata)
    proof: ProofMetadata = field(default_factory=ProofMetadata)
    signature: Optional[str] = None
    signature_algorithm: Optional[str] = None
    signer: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        video = {
            "file_path": self.video.file_path,
            "file_hash": self.video.file_hash,
            "stego_file_hash": self.video.stego_file_hash,
            "codec": self.video.codec,
            "profile": self.video.profile,
            "width": self.video.width,
            "height": self.video.height,
            "frame_count": self.video.frame_count,
            "gop_size": self.video.gop_size,
            "qp_value": self.video.qp_value,
        }
        if self.video.provenance_uri is not None:
            video["provenance_uri"] = self.video.provenance_uri
        if self.video.provenance_root_hash is not None:
            video["provenance_root_hash"] = self.video.provenance_root_hash
        return {
            "version": self.version,
            "created": self.created,
            "payload": {
                "message_length": self.payload.message_length,
                "bits_embedded": self.payload.bits_embedded,
                "bits_required": self.payload.bits_required,
                "chaos_enabled": self.payload.chaos_enabled,
                "chaos_original_bits": self.payload.chaos_original_bits,
                "chaos_expansion_factor": self.payload.chaos_expansion_factor,
            },
            "embedding": {
                "strategy": self.embedding.strategy,
                "max_modifications_per_block": self.embedding.max_modifications_per_block,
                "positions_count": self.embedding.positions_count,
                "positions_hash": self.embedding.positions_hash,
                "validation_threshold_db": self.embedding.validation_threshold_db,
            },
            "video": video,
            "proof": {
                "proof_system": self.proof.proof_system,
                "proof_size_bytes": self.proof.proof_size_bytes,
                "constraint_count": self.proof.constraint_count,
                "prove_time_ms": self.proof.prove_time_ms,
                "verify_time_ms": self.proof.verify_time_ms,
                "statement_id": self.proof.statement_id,
            },
            "signature": self.signature,
            "signature_algorithm": self.signature_algorithm,
            "signer": self.signer,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StegoManifest":
        payload = data["payload"]
        embedding = data["embedding"]
        video = data["video"]
        proof = data["proof"]
        return cls(
            version=str(data.get("version", "1.0.0")),
            created=str(data.get("created", "")),
            payload=PayloadMetadata(
                message_length=int(payload["message_length"]),
                bits_embedded=int(payload["bits_embedded"]),
                bits_required=int(payload["bits_required"]),
                chaos_enabled=bool(payload.get("chaos_enabled", False)),
                chaos_original_bits=payload.get("chaos_original_bits"),
                chaos_expansion_factor=float(payload.get("chaos_expansion_factor", 1.0)),
            ),
            embedding=EmbeddingMetadata(
                strategy=str(embedding["strategy"]),
                max_modifications_per_block=int(embedding["max_modifications_per_block"]),
                positions_count=int(embedding["positions_count"]),
                positions_hash=embedding.get("positions_hash"),
                validation_threshold_db=embedding.get("validation_threshold_db"),
            ),
            video=VideoMetadata(
                file_path=str(video["file_path"]),
                file_hash=str(video["file_hash"]),
                stego_file_hash=video.get("stego_file_hash"),
                codec=str(video.get("codec", "h264")),
                profile=video.get("profile"),
                width=video.get("width"),
                height=video.get("height"),
                frame_count=video.get("frame_count"),
                gop_size=video.get("gop_size"),
                qp_value=video.get("qp_value"),
                provenance_uri=video.get("provenance_uri"),
                provenance_root_hash=video.get("provenance_root_hash"),
            ),
            proof=ProofMetadata(
                proof_system=str(proof.get("proof_system", "ml-dsa-65-attestation")),
                proof_size_bytes=int(proof["proof_size_bytes"]),
                constraint_count=int(proof["constraint_count"]),
                prove_time_ms=proof.get("prove_time_ms"),
                verify_time_ms=proof.get("verify_time_ms"),
                statement_id=proof.get("statement_id"),
            ),
            signature=data.get("signature"),
            signature_algorithm=data.get("signature_algorithm"),
            signer=data.get("signer"),
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "StegoManifest":
        return cls.from_dict(json.loads(json_str))

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as file:
            file.write(self.to_json())

    @classmethod
    def load(cls, path: str) -> "StegoManifest":
        with open(path, "r", encoding="utf-8") as file:
            return cls.from_json(file.read())

    def _unsigned_dict(self) -> dict[str, Any]:
        data = self.to_dict()
        data["signature"] = None
        data["signer"] = None
        return data

    def compute_content_hash(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()

    def sign(self, private_key: bytes | Ed25519PrivateKey, signer_id: Optional[str] = None) -> None:
        """Sign with ML-DSA-65, preserving Ed25519 only for legacy artifacts."""
        if isinstance(private_key, Ed25519PrivateKey) or (
            isinstance(private_key, (bytes, bytearray)) and len(private_key) == 32
        ):
            self.signature_algorithm = LEGACY_SIGNATURE_ALGORITHM
            signature = _private_key(private_key).sign(canonical_json_bytes(self._unsigned_dict()))
            default_signer = LEGACY_SIGNATURE_ALGORITHM
        else:
            self.signature_algorithm = SIGNATURE_ALGORITHM
            signature = LatticeSigner.sign(bytes(private_key), canonical_json_bytes(self._unsigned_dict()))
            default_signer = SIGNATURE_ALGORITHM
        self.signature = base64.b64encode(signature).decode("ascii")
        self.signer = signer_id or default_signer

    def verify_signature(self, public_key: bytes | Ed25519PublicKey) -> bool:
        if not self.signature:
            return False
        try:
            signature = base64.b64decode(self.signature.encode("ascii"), validate=True)
            data = canonical_json_bytes(self._unsigned_dict())
            if self.signature_algorithm == SIGNATURE_ALGORITHM:
                return LatticeSigner.verify(bytes(public_key), data, signature)
            if self.signature_algorithm == LEGACY_SIGNATURE_ALGORITHM:
                _public_key(public_key).verify(signature, data)
                return True
        except (TypeError, ValueError, InvalidSignature):
            return False
        return False

def compute_file_hash(file_path: str) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()
