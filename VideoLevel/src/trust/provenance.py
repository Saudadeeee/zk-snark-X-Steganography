"""Experimental C2PA-style provenance root anchoring.

This is a future-branch helper. It anchors a canonical manifest root hash but
does not claim robust watermarking or C2PA production compliance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import canonical_json_hash, sha256_file


@dataclass(frozen=True)
class ProvenanceRoot:
    """Canonical root that can be embedded or stored in sidecar policy."""

    manifest_root_hash: str
    manifest_uri: str | None = None
    media_hash: str | None = None
    algorithm: str = "sha256-canonical-json-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "manifest_root_hash": self.manifest_root_hash,
            "manifest_uri": self.manifest_uri,
            "media_hash": self.media_hash,
        }


def load_manifest_dict(manifest: str | Path | dict[str, Any]) -> dict[str, Any]:
    """Load a manifest dict from a path or return a shallow copy of a dict."""
    if isinstance(manifest, dict):
        return dict(manifest)
    with open(manifest, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    if not isinstance(loaded, dict):
        raise ValueError("manifest root must be computed from a JSON object")
    return loaded


def build_provenance_root(
    manifest: str | Path | dict[str, Any],
    *,
    manifest_uri: str | None = None,
    media_path: str | Path | None = None,
) -> ProvenanceRoot:
    """Build a root hash from canonical manifest JSON."""
    manifest_dict = load_manifest_dict(manifest)
    return ProvenanceRoot(
        manifest_root_hash=canonical_json_hash(manifest_dict),
        manifest_uri=manifest_uri,
        media_hash=sha256_file(media_path) if media_path is not None else None,
    )


def verify_provenance_root(
    root: ProvenanceRoot | dict[str, Any],
    manifest: str | Path | dict[str, Any],
    *,
    media_path: str | Path | None = None,
) -> bool:
    """Verify a manifest/media pair against a previously published root.

    Fail-closed rules:
    - the canonical manifest hash must equal ``root.manifest_root_hash``;
    - when ``media_path`` is given, ``root.media_hash`` must be present and equal
      the SHA-256 of that file (a root without a media hash cannot vouch for media);
    - when ``media_path`` is omitted, only the manifest is checked.

    Security note: this is an integrity check against a root the caller already
    trusts (e.g. one embedded in the fragile plane or published out of band). A
    root taken from an unsigned sidecar is NOT authentication: anyone can
    recompute these hashes for a forged manifest/media pair.
    """
    if isinstance(root, dict):
        try:
            root = ProvenanceRoot(
                manifest_root_hash=str(root["manifest_root_hash"]),
                manifest_uri=root.get("manifest_uri"),
                media_hash=root.get("media_hash"),
                algorithm=root.get("algorithm", "sha256-canonical-json-v1"),
            )
        except (KeyError, TypeError, AttributeError):
            return False
    if root.algorithm != "sha256-canonical-json-v1":
        return False
    rebuilt = build_provenance_root(manifest, manifest_uri=root.manifest_uri, media_path=media_path)
    if rebuilt.manifest_root_hash != str(root.manifest_root_hash).lower():
        return False
    if media_path is not None:
        if not isinstance(root.media_hash, str) or not root.media_hash:
            return False
        if rebuilt.media_hash != root.media_hash.lower():
            return False
    return True
