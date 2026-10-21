"""Experimental TEE/model attestation helpers.

This module provides a stable bundle/signature interface for future attestation
work. The mock signer stabilizes tests; the Ed25519 signer gives a public-key
software signature path. Neither path claims real TEE hardware binding.
"""

from __future__ import annotations

import hmac
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import canonical_json_bytes, canonical_json_hash, sha256_file

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
except Exception:  # pragma: no cover - dependency is pinned, guard keeps imports explainable.
    InvalidSignature = Exception
    serialization = None
    Ed25519PrivateKey = None
    Ed25519PublicKey = None


ATTESTATION_SIGNATURE_SCHEMA = "zk-stego-attestation-signed-v2"
ATTESTATION_VERIFICATION_SCHEMA = "zk-stego-attestation-verification-v1"


@dataclass(frozen=True)
class AttestationBundle:
    """Canonical statement about model/media provenance."""

    video_hash: str
    model_config_hash: str
    model_binary_hash: str
    policy_id: str
    timestamp: str
    hardware_root: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_hash": self.video_hash,
            "model_config_hash": self.model_config_hash,
            "model_binary_hash": self.model_binary_hash,
            "policy_id": self.policy_id,
            "timestamp": self.timestamp,
            "hardware_root": self.hardware_root,
        }

    def statement_hash(self) -> str:
        return canonical_json_hash(self.to_dict())

    @classmethod
    def from_files(
        cls,
        *,
        video_path: str,
        model_config_path: str,
        model_binary_path: str,
        policy_id: str,
        timestamp: str,
        hardware_root: str | None = None,
    ) -> "AttestationBundle":
        return cls(
            video_hash=sha256_file(video_path),
            model_config_hash=sha256_file(model_config_path),
            model_binary_hash=sha256_file(model_binary_path),
            policy_id=policy_id,
            timestamp=timestamp,
            hardware_root=hardware_root,
        )


@dataclass(frozen=True)
class SignedAttestation:
    bundle: AttestationBundle
    signature: str
    signer_id: str
    scheme: str = "mock-hmac-sha256"
    receipt_schema: str = ATTESTATION_SIGNATURE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.receipt_schema,
            "bundle": self.bundle.to_dict(),
            "bundle_commitment": self.bundle.statement_hash(),
            "signature": self.signature,
            "signer_id": self.signer_id,
            "scheme": self.scheme,
            "signed_commitment": self.commitment(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SignedAttestation":
        bundle_data = data["bundle"]
        return cls(
            bundle=AttestationBundle(
                video_hash=str(bundle_data["video_hash"]),
                model_config_hash=str(bundle_data["model_config_hash"]),
                model_binary_hash=str(bundle_data["model_binary_hash"]),
                policy_id=str(bundle_data["policy_id"]),
                timestamp=str(bundle_data["timestamp"]),
                hardware_root=bundle_data.get("hardware_root"),
            ),
            signature=str(data["signature"]),
            signer_id=str(data["signer_id"]),
            scheme=data.get("scheme", "mock-hmac-sha256"),
            receipt_schema=data.get("schema", ATTESTATION_SIGNATURE_SCHEMA),
        )

    def commitment(self) -> str:
        return canonical_json_hash(
            {
                "schema": self.receipt_schema,
                "bundle_commitment": self.bundle.statement_hash(),
                "signature": self.signature,
                "signer_id": self.signer_id,
                "scheme": self.scheme,
            }
        )


@dataclass(frozen=True)
class AttestationSidecar:
    """Audit sidecar for a signed model/media attestation."""

    signed_attestation: SignedAttestation
    provenance_root_hash: str | None = None
    sidecar_schema: str = "zk-stego-attestation-sidecar-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "sidecar_schema": self.sidecar_schema,
            "provenance_root_hash": self.provenance_root_hash,
            "signed_attestation": self.signed_attestation.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AttestationSidecar":
        return cls(
            signed_attestation=SignedAttestation.from_dict(data["signed_attestation"]),
            provenance_root_hash=data.get("provenance_root_hash"),
            sidecar_schema=data.get("sidecar_schema", "zk-stego-attestation-sidecar-v1"),
        )


@dataclass(frozen=True)
class AttestationVerificationPolicy:
    """Verification policy for attestation bundles."""

    expected_signer_id: str | None = None
    expected_scheme: str | None = None
    hardware_root: str | None = None
    require_hardware_root: bool = False
    allow_software_only: bool = True
    claim_scope: str = "software_signature_bundle"

    def validate(self) -> None:
        if self.expected_signer_id is not None and not self.expected_signer_id:
            raise ValueError("expected_signer_id must be non-empty when provided")
        if self.expected_scheme is not None and not self.expected_scheme:
            raise ValueError("expected_scheme must be non-empty when provided")
        if self.require_hardware_root and not self.hardware_root:
            raise ValueError("hardware_root is required when require_hardware_root is true")
        if self.claim_scope not in {"software_signature_bundle", "hardware_attestation_bundle"}:
            raise ValueError("unsupported attestation claim scope")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "expected_signer_id": self.expected_signer_id,
            "expected_scheme": self.expected_scheme,
            "hardware_root": self.hardware_root,
            "require_hardware_root": self.require_hardware_root,
            "allow_software_only": self.allow_software_only,
            "claim_scope": self.claim_scope,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AttestationVerificationPolicy":
        policy = cls(
            expected_signer_id=data.get("expected_signer_id"),
            expected_scheme=data.get("expected_scheme"),
            hardware_root=data.get("hardware_root"),
            require_hardware_root=bool(data.get("require_hardware_root", False)),
            allow_software_only=bool(data.get("allow_software_only", True)),
            claim_scope=str(data.get("claim_scope", "software_signature_bundle")),
        )
        policy.validate()
        return policy

    def commitment(self) -> str:
        return canonical_json_hash(self.to_dict())


@dataclass(frozen=True)
class AttestationVerificationReport:
    """Replayable verification report for a signed attestation."""

    verified: bool
    signature_valid: bool
    policy: AttestationVerificationPolicy
    bundle_commitment: str
    signed_commitment: str
    sidecar_roundtrip_valid: bool | None
    hardware_root_present: bool
    reason: str | None = None
    schema: str = ATTESTATION_VERIFICATION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "verified": self.verified,
            "signature_valid": self.signature_valid,
            "policy": self.policy.to_dict(),
            "bundle_commitment": self.bundle_commitment,
            "signed_commitment": self.signed_commitment,
            "sidecar_roundtrip_valid": self.sidecar_roundtrip_valid,
            "hardware_root_present": self.hardware_root_present,
            "reason": self.reason,
        }


class MockTEESigner:
    """Mock signer used to stabilize the attestation interface."""

    def __init__(self, key: bytes, *, signer_id: str = "mock-tee-v1"):
        if not key:
            raise ValueError("key must be non-empty")
        self._key = bytes(key)
        self.signer_id = signer_id

    def sign(self, bundle: AttestationBundle) -> SignedAttestation:
        signature = hmac.new(
            self._key,
            canonical_json_bytes(bundle.to_dict()),
            hashlib.sha256,
        ).hexdigest()
        return SignedAttestation(bundle=bundle, signature=signature, signer_id=self.signer_id)

    def verify(self, signed: SignedAttestation) -> bool:
        expected = self.sign(signed.bundle)
        return (
            signed.signer_id == self.signer_id
            and signed.scheme == expected.scheme
            and hmac.compare_digest(signed.signature, expected.signature)
        )


def verify_attestation_bundle(
    signer: Any,
    signed: SignedAttestation,
    *,
    policy: AttestationVerificationPolicy | None = None,
    sidecar: AttestationSidecar | None = None,
) -> AttestationVerificationReport:
    policy = policy or AttestationVerificationPolicy(
        expected_signer_id=signed.signer_id,
        expected_scheme=signed.scheme,
        hardware_root=signed.bundle.hardware_root,
        require_hardware_root=False,
        allow_software_only=True,
    )
    policy.validate()
    signature_valid = signer.verify(signed)
    sidecar_roundtrip_valid = None
    hardware_root_present = signed.bundle.hardware_root is not None
    reason = None

    if policy.expected_signer_id is not None and signed.signer_id != policy.expected_signer_id:
        signature_valid = False
        reason = "signer_id mismatch"
    if policy.expected_scheme is not None and signed.scheme != policy.expected_scheme:
        signature_valid = False
        reason = reason or "scheme mismatch"
    if policy.require_hardware_root and not hardware_root_present:
        signature_valid = False
        reason = reason or "missing hardware root"
    if not policy.allow_software_only and signed.scheme in {"mock-hmac-sha256", "ed25519"}:
        signature_valid = False
        reason = reason or "software-only signatures are not allowed"
    if sidecar is not None:
        sidecar_roundtrip_valid = (
            sidecar.signed_attestation.commitment() == signed.commitment()
        )
        if not sidecar_roundtrip_valid:
            signature_valid = False
            reason = reason or "sidecar commitment mismatch"

    if not signature_valid and reason is None:
        reason = "signature verification failed"

    verified = bool(signature_valid and (not policy.require_hardware_root or hardware_root_present))
    return AttestationVerificationReport(
        verified=verified,
        signature_valid=signature_valid,
        policy=policy,
        bundle_commitment=signed.bundle.statement_hash(),
        signed_commitment=signed.commitment(),
        sidecar_roundtrip_valid=sidecar_roundtrip_valid,
        hardware_root_present=hardware_root_present,
        reason=reason,
    )


class Ed25519AttestationVerifier:
    """Public-key verifier for software attestation signatures."""

    scheme = "ed25519"

    def __init__(self, public_key_hex: str, *, signer_id: str = "ed25519-v1"):
        if Ed25519PublicKey is None:
            raise RuntimeError("cryptography is required for Ed25519 attestation")
        public_bytes = bytes.fromhex(public_key_hex)
        if len(public_bytes) != 32:
            raise ValueError("Ed25519 public key must be 32 bytes")
        self._public_key = Ed25519PublicKey.from_public_bytes(public_bytes)
        self.public_key_hex = public_bytes.hex()
        self.signer_id = signer_id

    def verify(self, signed: SignedAttestation) -> bool:
        if signed.signer_id != self.signer_id or signed.scheme != self.scheme:
            return False
        try:
            self._public_key.verify(
                bytes.fromhex(signed.signature),
                canonical_json_bytes(signed.bundle.to_dict()),
            )
        except (ValueError, InvalidSignature):
            return False
        return True


class Ed25519AttestationSigner(Ed25519AttestationVerifier):
    """Software Ed25519 signer for product-style attestation sidecars."""

    def __init__(self, private_key_hex: str, *, signer_id: str = "ed25519-v1"):
        if Ed25519PrivateKey is None or serialization is None:
            raise RuntimeError("cryptography is required for Ed25519 attestation")
        private_bytes = bytes.fromhex(private_key_hex)
        if len(private_bytes) != 32:
            raise ValueError("Ed25519 private key must be 32 bytes")
        self._private_key = Ed25519PrivateKey.from_private_bytes(private_bytes)
        self.private_key_hex = private_bytes.hex()
        public_key = self._private_key.public_key()
        public_key_hex = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ).hex()
        super().__init__(public_key_hex, signer_id=signer_id)

    @classmethod
    def generate(cls, *, signer_id: str = "ed25519-v1") -> "Ed25519AttestationSigner":
        if Ed25519PrivateKey is None or serialization is None:
            raise RuntimeError("cryptography is required for Ed25519 attestation")
        private_key = Ed25519PrivateKey.generate()
        private_key_hex = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        ).hex()
        return cls(private_key_hex, signer_id=signer_id)

    @classmethod
    def from_seed(cls, seed: bytes, *, signer_id: str = "ed25519-v1") -> "Ed25519AttestationSigner":
        if not seed:
            raise ValueError("seed must be non-empty")
        return cls(hashlib.sha256(seed).hexdigest(), signer_id=signer_id)

    def sign(self, bundle: AttestationBundle) -> SignedAttestation:
        signature = self._private_key.sign(canonical_json_bytes(bundle.to_dict())).hex()
        return SignedAttestation(
            bundle=bundle,
            signature=signature,
            signer_id=self.signer_id,
            scheme=self.scheme,
        )


def save_attestation_sidecar(sidecar: AttestationSidecar, path: str | Path) -> None:
    Path(path).write_text(json.dumps(sidecar.to_dict(), indent=2, ensure_ascii=True), encoding="utf-8")


def load_attestation_sidecar(path: str | Path) -> AttestationSidecar:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("attestation sidecar must be a JSON object")
    return AttestationSidecar.from_dict(data)


@dataclass(frozen=True)
class ZKMLInterfaceSpec:
    """Explicit non-implementation contract for future ZKML work."""

    circuit_name: str
    public_outputs: tuple[str, ...]
    private_inputs: tuple[str, ...]
    status: str = "interface_only"

    def to_dict(self) -> dict[str, Any]:
        return {
            "circuit_name": self.circuit_name,
            "public_outputs": list(self.public_outputs),
            "private_inputs": list(self.private_inputs),
            "status": self.status,
        }

    def validate_interface_only(self) -> bool:
        return self.status == "interface_only" and bool(self.public_outputs)
