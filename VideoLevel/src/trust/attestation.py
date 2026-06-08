"""Experimental TEE/model attestation helpers.

This module provides a stable bundle/signature interface for future attestation
work. It intentionally uses HMAC for the mock signer and does not claim real TEE
hardware binding.
"""

from __future__ import annotations

import hmac
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import canonical_json_bytes, canonical_json_hash, sha256_file


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle": self.bundle.to_dict(),
            "signature": self.signature,
            "signer_id": self.signer_id,
            "scheme": self.scheme,
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
