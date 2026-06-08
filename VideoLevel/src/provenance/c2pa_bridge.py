"""Production-style C2PA root anchor bridge for future branches.

The bridge builds a compact anchor from a canonical manifest. The 32-byte root
can be embedded as payload bytes by the existing fragile CAVLC plane, while the
audit sidecar records how to resolve and verify the external manifest.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.manifest import StegoManifest
from src.trust.canonical import canonical_json_hash, sha256_file
from src.trust.provenance import ProvenanceRoot, build_provenance_root, verify_provenance_root


ANCHOR_SCHEMA = "zk-stego-c2pa-anchor-v1"


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
    sidecar_schema: str = "zk-stego-c2pa-audit-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "sidecar_schema": self.sidecar_schema,
            "registry_uri": self.registry_uri,
            "media_hash": self.media_hash,
            "manifest_commitment": self.manifest_commitment,
            "anchor": self.anchor.to_dict(),
        }


def _load_manifest(manifest: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(manifest, dict):
        return dict(manifest)
    with open(manifest, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("C2PA manifest must be a JSON object")
    return data


def build_c2pa_anchor(
    manifest: str | Path | dict[str, Any],
    *,
    registry_uri: str,
    media_path: str | Path | None = None,
) -> C2PAAuditSidecar:
    """Build an audit sidecar and compact root payload for a manifest."""
    manifest_dict = _load_manifest(manifest)
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
) -> bool:
    """Verify manifest/media and optional embedded root payload."""
    if isinstance(sidecar, dict):
        sidecar = C2PAAuditSidecar(
            anchor=C2PAAnchor(
                root=ProvenanceRoot(
                    manifest_root_hash=str(sidecar["anchor"]["root"]["manifest_root_hash"]),
                    manifest_uri=sidecar["anchor"]["root"].get("manifest_uri"),
                    media_hash=sidecar["anchor"]["root"].get("media_hash"),
                    algorithm=sidecar["anchor"]["root"].get("algorithm", "sha256-canonical-json-v1"),
                ),
                schema=sidecar["anchor"].get("schema", ANCHOR_SCHEMA),
            ),
            registry_uri=str(sidecar["registry_uri"]),
            media_hash=sidecar.get("media_hash"),
            manifest_commitment=str(sidecar["manifest_commitment"]),
            sidecar_schema=sidecar.get("sidecar_schema", "zk-stego-c2pa-audit-v1"),
        )
    if embedded_payload is not None and embedded_payload != sidecar.anchor.payload_bytes:
        return False
    manifest_dict = _load_manifest(manifest)
    if canonical_json_hash(manifest_dict) != sidecar.manifest_commitment:
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
        sidecar_schema=data.get("sidecar_schema", "zk-stego-c2pa-audit-v1"),
    )
