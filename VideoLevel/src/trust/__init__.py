"""Experimental trust-plane helpers for future branches.

These modules are intentionally separate from the frozen H.264/CAVLC baseline.
They provide executable interfaces for provenance, registry, watermark receipt,
and attestation experiments without changing embed()/verify() semantics.
"""

from .provenance import ProvenanceRoot, build_provenance_root, verify_provenance_root
from .fingerprint import (
    FingerprintPreprocessPolicy,
    FingerprintRecord,
    FingerprintRegistry,
    VideoFingerprint,
    compute_framehash,
    compute_video_fingerprint,
    sample_frame_indices,
)
from .c2pa_bridge import (
    C2PAAnchor,
    C2PAAuditSidecar,
    attach_anchor_to_manifest,
    build_c2pa_anchor,
    load_audit_sidecar,
    save_audit_sidecar,
    verify_c2pa_anchor,
)
from .watermark_receipt import DetectorReceipt, TinyThresholdDetector, extract_tiny_video_features
from .attestation import (
    AttestationBundle,
    AttestationSidecar,
    MockTEESigner,
    SignedAttestation,
    ZKMLInterfaceSpec,
    load_attestation_sidecar,
    save_attestation_sidecar,
)

__all__ = [
    "C2PAAnchor",
    "C2PAAuditSidecar",
    "attach_anchor_to_manifest",
    "build_c2pa_anchor",
    "load_audit_sidecar",
    "save_audit_sidecar",
    "verify_c2pa_anchor",
    "ProvenanceRoot",
    "build_provenance_root",
    "verify_provenance_root",
    "FingerprintRecord",
    "FingerprintPreprocessPolicy",
    "FingerprintRegistry",
    "VideoFingerprint",
    "compute_framehash",
    "compute_video_fingerprint",
    "sample_frame_indices",
    "DetectorReceipt",
    "TinyThresholdDetector",
    "extract_tiny_video_features",
    "AttestationBundle",
    "AttestationSidecar",
    "MockTEESigner",
    "SignedAttestation",
    "ZKMLInterfaceSpec",
    "load_attestation_sidecar",
    "save_attestation_sidecar",
]
