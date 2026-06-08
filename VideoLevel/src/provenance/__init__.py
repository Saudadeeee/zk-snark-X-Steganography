"""Future provenance anchoring helpers.

This package is not part of the frozen CAVLC baseline claim. It provides a
production-style interface for future C2PA/root-hash anchoring experiments.
"""

from .c2pa_bridge import (
    C2PAAnchor,
    C2PAAuditSidecar,
    attach_anchor_to_manifest,
    build_c2pa_anchor,
    load_audit_sidecar,
    save_audit_sidecar,
    verify_c2pa_anchor,
)

__all__ = [
    "C2PAAnchor",
    "C2PAAuditSidecar",
    "attach_anchor_to_manifest",
    "build_c2pa_anchor",
    "load_audit_sidecar",
    "save_audit_sidecar",
    "verify_c2pa_anchor",
]
