"""Manifest schema for ZK-Stego VideoLevel.

Versioned manifest structure for embed/verify sidecars.
"""

from __future__ import annotations

import hmac
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

# Current manifest schema version
MANIFEST_VERSION = "1.0.0"


@dataclass
class PayloadMetadata:
    """Payload metadata."""

    message_length: int = 0        # Original message byte count
    bits_embedded: int = 0         # Total bits embedded (message + proof + chaos)
    bits_required: int = 0         # Minimum bits needed
    chaos_enabled: bool = False        # Whether chaos expansion was used
    chaos_original_bits: Optional[int] = None  # Original bits before chaos
    chaos_expansion_factor: float = 1.0  # chaos_bits / original_bits


@dataclass
class EmbeddingMetadata:
    """Embedding process metadata."""

    strategy: str = "t1_sign_flip"             # e.g., "t1_sign_flip"
    max_modifications_per_block: int = 1
    positions_count: int = 0      # Number of T1 positions used
    validation_threshold_db: Optional[float] = None  # PSNR threshold used


@dataclass
class VideoMetadata:
    """Source video metadata."""

    file_path: str = ""
    file_hash: str = ""            # SHA-256 of original video
    codec: str = "h264"                # e.g., "h264"
    profile: Optional[str] = None  # e.g., "baseline"
    width: Optional[int] = None
    height: Optional[int] = None
    frame_count: Optional[int] = None
    gop_size: Optional[int] = None
    qp_value: Optional[int] = None
    provenance_uri: Optional[str] = None
    provenance_root_hash: Optional[str] = None


@dataclass
class ProofMetadata:
    """ZK proof metadata."""

    proof_system: str = "groth16"         # e.g., "groth16"
    proof_size_bytes: int = 0
    constraint_count: int = 0
    prove_time_ms: Optional[float] = None
    verify_time_ms: Optional[float] = None


@dataclass
class StegoManifest:
    """Complete steganography manifest.

    This manifest accompanies a stego video and contains all information
    needed for verification and reproducibility.

    Version 1.0.0 structure:
    - version: Schema version
    - created: ISO-8601 timestamp
    - payload: Payload metadata
    - embedding: Embedding process metadata
    - video: Source video metadata
    - proof: ZK proof metadata
    - signature: Optional HMAC/ED25519 signature for authenticity
    """

    version: str = MANIFEST_VERSION
    created: str = field(default_factory=lambda: datetime.now().isoformat())

    payload: PayloadMetadata = field(default_factory=PayloadMetadata)
    embedding: EmbeddingMetadata = field(default_factory=EmbeddingMetadata)
    video: VideoMetadata = field(default_factory=VideoMetadata)
    proof: ProofMetadata = field(default_factory=ProofMetadata)

    # Optional signing
    signature: Optional[str] = None  # Base64-encoded signature
    signer: Optional[str] = None    # Key identifier

    def to_dict(self) -> dict:
        """Convert manifest to JSON-serializable dict."""
        video = {
            "file_path": self.video.file_path,
            "file_hash": self.video.file_hash,
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
                "validation_threshold_db": self.embedding.validation_threshold_db,
            },
            "video": video,
            "proof": {
                "proof_system": self.proof.proof_system,
                "proof_size_bytes": self.proof.proof_size_bytes,
                "constraint_count": self.proof.constraint_count,
                "prove_time_ms": self.proof.prove_time_ms,
                "verify_time_ms": self.proof.verify_time_ms,
            },
            "signature": self.signature,
            "signer": self.signer,
        }

    @classmethod
    def from_dict(cls, data: dict) -> StegoManifest:
        """Create manifest from JSON dict."""
        return cls(
            version=data.get("version", MANIFEST_VERSION),
            created=data.get("created", ""),
            payload=PayloadMetadata(
                message_length=data["payload"]["message_length"],
                bits_embedded=data["payload"]["bits_embedded"],
                bits_required=data["payload"]["bits_required"],
                chaos_enabled=data["payload"].get("chaos_enabled", False),
                chaos_original_bits=data["payload"].get("chaos_original_bits"),
                chaos_expansion_factor=data["payload"].get("chaos_expansion_factor", 1.0),
            ),
            embedding=EmbeddingMetadata(
                strategy=data["embedding"]["strategy"],
                max_modifications_per_block=data["embedding"]["max_modifications_per_block"],
                positions_count=data["embedding"]["positions_count"],
                validation_threshold_db=data["embedding"].get("validation_threshold_db"),
            ),
            video=VideoMetadata(
                file_path=data["video"]["file_path"],
                file_hash=data["video"]["file_hash"],
                codec=data["video"].get("codec", "h264"),
                profile=data["video"].get("profile"),
                width=data["video"].get("width"),
                height=data["video"].get("height"),
                frame_count=data["video"].get("frame_count"),
                gop_size=data["video"].get("gop_size"),
                qp_value=data["video"].get("qp_value"),
                provenance_uri=data["video"].get("provenance_uri"),
                provenance_root_hash=data["video"].get("provenance_root_hash"),
            ),
            proof=ProofMetadata(
                proof_system=data["proof"].get("proof_system", "groth16"),
                proof_size_bytes=data["proof"]["proof_size_bytes"],
                constraint_count=data["proof"]["constraint_count"],
                prove_time_ms=data["proof"].get("prove_time_ms"),
                verify_time_ms=data["proof"].get("verify_time_ms"),
            ),
            signature=data.get("signature"),
            signer=data.get("signer"),
        )

    def to_json(self, indent: int = 2) -> str:
        """Serialize manifest to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> StegoManifest:
        """Deserialize manifest from JSON string."""
        return cls.from_dict(json.loads(json_str))

    def save(self, path: str) -> None:
        """Save manifest to file."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())

    @classmethod
    def load(cls, path: str) -> StegoManifest:
        """Load manifest from file."""
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_json(f.read())

    def compute_content_hash(self) -> str:
        """Compute SHA-256 hash of manifest content (excluding signature)."""
        manifest_dict = self.to_dict()
        manifest_dict["signature"] = None
        manifest_dict["signer"] = None
        content = json.dumps(manifest_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(content.encode()).hexdigest()

    def verify_signature(self, public_key: bytes) -> bool:
        """Verify manifest signature using HMAC-SHA256."""
        if not self.signature or not isinstance(public_key, (bytes, bytearray)) or len(public_key) == 0:
            return False
        expected = hmac.new(bytes(public_key), self.compute_content_hash().encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(self.signature, expected)

    def sign(self, private_key: bytes, signer_id: Optional[str] = None) -> None:
        """Sign manifest content using HMAC-SHA256."""
        if not isinstance(private_key, (bytes, bytearray)) or len(private_key) == 0:
            raise ValueError("private_key must be non-empty bytes")
        content_hash = self.compute_content_hash()
        self.signature = hmac.new(bytes(private_key), content_hash.encode("utf-8"), hashlib.sha256).hexdigest()
        self.signer = signer_id or "default"


def compute_file_hash(file_path: str) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()
