"""Production-style C2PA root anchor bridge for future branches.

The bridge builds a compact anchor from a canonical manifest. The 32-byte root
can be embedded as payload bytes by the existing fragile CAVLC plane, while the
audit sidecar records how to resolve and verify the external manifest.
"""

from __future__ import annotations

import base64
import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.manifest import StegoManifest
from .canonical import canonical_json_hash, sha256_file
from .provenance import (ProvenanceRoot, build_provenance_root, load_manifest_dict,
                         verify_provenance_root)


ANCHOR_SCHEMA = "zk-stego-c2pa-anchor-v1"
SIDECAR_SCHEMA = "zk-stego-c2pa-audit-v1"


@dataclass(frozen=True)
class C2PAAnchor:
    """Compact provenance anchor intended for fragile-plane embedding."""

    root: ProvenanceRoot
    schema: str = ANCHOR_SCHEMA

    @property
    def payload_bytes(self) -> bytes:
        """Return the 32-byte root hash suitable for embedding."""
        return bytes.fromhex(self.root.manifest_root_hash)

    @property
    def payload_b64(self) -> str:
        return base64.b64encode(self.payload_bytes).decode("ascii")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "root": self.root.to_dict(),
            "payload_b64": self.payload_b64,
        }


@dataclass(frozen=True)
class C2PAAuditSidecar:
    """Audit sidecar binding media, manifest, registry URI, and embedded root."""

    anchor: C2PAAnchor
    registry_uri: str
    media_hash: str | None
    manifest_commitment: str
    sidecar_schema: str = SIDECAR_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "sidecar_schema": self.sidecar_schema,
            "registry_uri": self.registry_uri,
            "media_hash": self.media_hash,
            "manifest_commitment": self.manifest_commitment,
            "anchor": self.anchor.to_dict(),
        }


def build_c2pa_anchor(
    manifest: str | Path | dict[str, Any],
    *,
    registry_uri: str,
    media_path: str | Path | None = None,
) -> C2PAAuditSidecar:
    """Build an audit sidecar and compact root payload for a manifest."""
    manifest_dict = load_manifest_dict(manifest)
    root = build_provenance_root(
        manifest_dict,
        manifest_uri=registry_uri,
        media_path=media_path,
    )
    anchor = C2PAAnchor(root=root)
    return C2PAAuditSidecar(
        anchor=anchor,
        registry_uri=registry_uri,
        media_hash=sha256_file(media_path) if media_path is not None else None,
        manifest_commitment=canonical_json_hash(manifest_dict),
    )


def verify_c2pa_anchor(
    sidecar: C2PAAuditSidecar | dict[str, Any],
    manifest: str | Path | dict[str, Any],
    *,
    media_path: str | Path | None = None,
    embedded_payload: bytes | None = None,
    allow_unanchored: bool = False,
) -> bool:
    """Verify manifest/media against an audit sidecar and the embedded root.

    Fail-closed rules:
    - ``embedded_payload`` (the 32-byte root recovered from the fragile plane) is
      required and must equal the sidecar root. Without it the call returns
      False unless ``allow_unanchored=True`` is passed explicitly;
    - the recomputed canonical manifest hash must equal both
      ``manifest_commitment`` and the root ``manifest_root_hash``;
    - the top-level ``media_hash`` and the root ``media_hash`` must agree;
    - when ``media_path`` is given, the media hash must be present and equal the
      SHA-256 of that file.

    Security note: the audit sidecar is unsigned. With ``allow_unanchored=True``
    this is only a self-consistency check, NOT authentication -- anyone can
    recompute every hash in a forged sidecar+manifest+media set. Authenticity
    comes from the embedded root (or a signed/published root), not the sidecar.
    """
    try:
        if isinstance(sidecar, dict):
            sidecar = _sidecar_from_dict(sidecar)
        anchor_root = sidecar.anchor.payload_bytes
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
    if sidecar.sidecar_schema != SIDECAR_SCHEMA or sidecar.anchor.schema != ANCHOR_SCHEMA:
        return False
    if embedded_payload is None:
        if not allow_unanchored:
            return False
    elif not isinstance(embedded_payload, (bytes, bytearray)) or not hmac.compare_digest(
        bytes(embedded_payload), anchor_root
    ):
        return False
    if sidecar.registry_uri != sidecar.anchor.root.manifest_uri:
        return False
    if sidecar.media_hash != sidecar.anchor.root.media_hash:
        return False
    manifest_dict = load_manifest_dict(manifest)
    manifest_hash = canonical_json_hash(manifest_dict)
    if manifest_hash != str(sidecar.manifest_commitment).lower():
        return False
    if manifest_hash != str(sidecar.anchor.root.manifest_root_hash).lower():
        return False
    return verify_provenance_root(sidecar.anchor.root, manifest_dict, media_path=media_path)


def attach_anchor_to_manifest(manifest: StegoManifest, sidecar: C2PAAuditSidecar) -> StegoManifest:
    """Attach C2PA provenance locator fields to a stego manifest."""
    manifest.video.provenance_uri = sidecar.registry_uri
    manifest.video.provenance_root_hash = sidecar.anchor.root.manifest_root_hash
    return manifest


def save_audit_sidecar(sidecar: C2PAAuditSidecar, path: str | Path) -> None:
    Path(path).write_text(json.dumps(sidecar.to_dict(), indent=2, ensure_ascii=True), encoding="utf-8")


def load_audit_sidecar(path: str | Path) -> C2PAAuditSidecar:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("audit sidecar must be a JSON object")
    return _sidecar_from_dict(data)


def _sidecar_from_dict(data: dict[str, Any]) -> C2PAAuditSidecar:
    root_data = data["anchor"]["root"]
    return C2PAAuditSidecar(
        anchor=C2PAAnchor(
            root=ProvenanceRoot(
                manifest_root_hash=str(root_data["manifest_root_hash"]),
                manifest_uri=root_data.get("manifest_uri"),
                media_hash=root_data.get("media_hash"),
                algorithm=root_data.get("algorithm", "sha256-canonical-json-v1"),
            ),
            schema=data["anchor"].get("schema", ANCHOR_SCHEMA),
        ),
        registry_uri=str(data["registry_uri"]),
        media_hash=data.get("media_hash"),
        manifest_commitment=str(data["manifest_commitment"]),
        sidecar_schema=data.get("sidecar_schema", SIDECAR_SCHEMA),
    )
