"""Signed, time-bounded public-key certificates for manifest verification.

The certificate binds an Ed25519 manifest verification key to an issuer and a
UTC validity window.  It deliberately contains no private-key material.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from src.manifest import StegoManifest


CERTIFICATE_VERSION = "1.0"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must include a UTC offset")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


@dataclass
class KeyCertificate:
    """An issuer-signed binding for a manifest signing public key."""

    key_id: str
    subject_public_key_b64: str
    not_before: str
    expires_at: str
    signature_b64: str | None = None
    version: str = CERTIFICATE_VERSION
    issuer: str = "local-authority"
    signature_scheme: str = "ed25519"

    def unsigned_dict(self) -> dict[str, str]:
        return {
            "expires_at": self.expires_at,
            "issuer": self.issuer,
            "key_id": self.key_id,
            "not_before": self.not_before,
            "signature_scheme": self.signature_scheme,
            "subject_public_key_b64": self.subject_public_key_b64,
            "version": self.version,
        }

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.unsigned_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "signature_b64": self.signature_b64}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, source: str) -> "KeyCertificate":
        data = json.loads(source)
        required = {"key_id", "subject_public_key_b64", "not_before", "expires_at", "signature_b64"}
        missing = required.difference(data)
        if missing:
            raise ValueError(f"certificate is missing fields: {', '.join(sorted(missing))}")
        return cls(
            key_id=data["key_id"],
            subject_public_key_b64=data["subject_public_key_b64"],
            not_before=data["not_before"],
            expires_at=data["expires_at"],
            signature_b64=data["signature_b64"],
            version=data.get("version", CERTIFICATE_VERSION),
            issuer=data.get("issuer", "local-authority"),
            signature_scheme=data.get("signature_scheme", "ed25519"),
        )

    def subject_public_key(self) -> bytes:
        try:
            result = base64.b64decode(self.subject_public_key_b64, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("certificate public key is not valid base64") from exc
        if len(result) != 32:
            raise ValueError("certificate subject key must be 32 bytes")
        return result

    def verify(self, issuer_public_key: bytes, now: datetime | None = None) -> bool:
        """Check format, issuer signature, and the inclusive validity window."""
        if self.version != CERTIFICATE_VERSION or self.signature_scheme != "ed25519":
            return False
        if not isinstance(issuer_public_key, (bytes, bytearray)) or len(issuer_public_key) != 32:
            return False
        try:
            start, end = _parse_timestamp(self.not_before), _parse_timestamp(self.expires_at)
            instant = _utc(now or datetime.now(timezone.utc))
            if start > end or instant < start or instant > end or not self.signature_b64:
                return False
            signature = base64.b64decode(self.signature_b64, validate=True)
            Ed25519PublicKey.from_public_bytes(bytes(issuer_public_key)).verify(signature, self.canonical_bytes())
            self.subject_public_key()
            return True
        except (InvalidSignature, ValueError, TypeError):
            return False


def issue_key_certificate(
    *,
    subject_public_key: bytes,
    issuer_private_key: bytes,
    key_id: str,
    not_before: datetime,
    expires_at: datetime,
    issuer: str = "local-authority",
) -> KeyCertificate:
    """Issue a certificate.  Callers retain the subject private key offline."""
    if not key_id or not isinstance(subject_public_key, (bytes, bytearray)) or len(subject_public_key) != 32:
        raise ValueError("key_id and a 32-byte subject public key are required")
    if not isinstance(issuer_private_key, (bytes, bytearray)) or len(issuer_private_key) != 32:
        raise ValueError("issuer_private_key must be a 32-byte Ed25519 private key")
    if _utc(not_before) >= _utc(expires_at):
        raise ValueError("expires_at must be later than not_before")
    certificate = KeyCertificate(
        key_id=key_id,
        subject_public_key_b64=base64.b64encode(bytes(subject_public_key)).decode("ascii"),
        not_before=_timestamp(not_before),
        expires_at=_timestamp(expires_at),
        issuer=issuer,
    )
    signature = Ed25519PrivateKey.from_private_bytes(bytes(issuer_private_key)).sign(certificate.canonical_bytes())
    certificate.signature_b64 = base64.b64encode(signature).decode("ascii")
    return certificate


def verify_manifest_with_certificate(
    manifest: StegoManifest,
    certificate: KeyCertificate,
    issuer_public_key: bytes,
    *,
    now: datetime | None = None,
) -> bool:
    """Verify the issuer window first, then the manifest using the bound key."""
    return certificate.verify(issuer_public_key, now=now) and manifest.verify_signature(certificate.subject_public_key())
