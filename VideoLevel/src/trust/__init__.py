"""Experimental trust-plane helpers for future branches.

These modules are intentionally separate from the frozen H.264/CAVLC baseline.
They provide executable interfaces for provenance, registry, watermark receipt,
and attestation experiments without changing embed()/verify() semantics.
"""

from .provenance import ProvenanceRoot, build_provenance_root, verify_provenance_root
from .fingerprint import (
    FingerprintLookupPolicy,
    FingerprintLookupReceipt,
    FingerprintPreprocessPolicy,
    FingerprintRecord,
    FingerprintRegistry,
    RegistryMatch,
    VideoFingerprint,
    compute_framehash,
    compute_video_fingerprint,
    sample_frame_indices,
)
from .watermark_receipt import (
    CalibratedThresholdDetector,
    DetectorAlignmentScore,
    DetectorCalibration,
    DetectorReceipt,
    KeyedTemplateDetector,
    TinyThresholdDetector,
    WatermarkReceiptPolicy,
    WatermarkVerificationReport,
    extract_tiny_video_features,
)
from .attestation import (
    AttestationBundle,
    AttestationSidecar,
    AttestationVerificationPolicy,
    AttestationVerificationReport,
    Ed25519AttestationSigner,
    Ed25519AttestationVerifier,
    MockTEESigner,
    SignedAttestation,
    ZKMLInterfaceSpec,
    verify_attestation_bundle,
    load_attestation_sidecar,
    save_attestation_sidecar,
)
from .zk_receipts import (
    DETECTOR_RECEIPT_CIRCUIT,
    FINGERPRINT_VERIFY_CIRCUIT,
    ZK_RECEIPT_CONTRACT_REPORT_SCHEMA,
    ZK_RECEIPT_CONTRACT_TIER,
    ZKReceiptCircuitContract,
    ZKReceiptTestVector,
    ZKReceiptValidationReport,
    build_zk_receipt_contract_report,
    detector_receipt_contract,
    detector_receipt_test_vector,
    fingerprint_receipt_test_vector,
    fingerprint_verify_contract,
    zk_receipt_test_vectors,
)
__all__ = [
    "ProvenanceRoot",
    "build_provenance_root",
    "verify_provenance_root",
    "FingerprintRecord",
    "FingerprintLookupPolicy",
    "FingerprintLookupReceipt",
    "FingerprintPreprocessPolicy",
    "FingerprintRegistry",
    "RegistryMatch",
    "VideoFingerprint",
    "compute_framehash",
    "compute_video_fingerprint",
    "sample_frame_indices",
    "DetectorReceipt",
    "DetectorAlignmentScore",
    "DetectorCalibration",
    "CalibratedThresholdDetector",
    "KeyedTemplateDetector",
    "TinyThresholdDetector",
    "WatermarkReceiptPolicy",
    "WatermarkVerificationReport",
    "extract_tiny_video_features",
    "AttestationBundle",
    "AttestationSidecar",
    "AttestationVerificationPolicy",
    "AttestationVerificationReport",
    "Ed25519AttestationSigner",
    "Ed25519AttestationVerifier",
    "MockTEESigner",
    "SignedAttestation",
    "ZKMLInterfaceSpec",
    "verify_attestation_bundle",
    "load_attestation_sidecar",
    "save_attestation_sidecar",
    "DETECTOR_RECEIPT_CIRCUIT",
    "FINGERPRINT_VERIFY_CIRCUIT",
    "ZK_RECEIPT_CONTRACT_REPORT_SCHEMA",
    "ZK_RECEIPT_CONTRACT_TIER",
    "ZKReceiptCircuitContract",
    "ZKReceiptTestVector",
    "ZKReceiptValidationReport",
    "build_zk_receipt_contract_report",
    "detector_receipt_contract",
    "detector_receipt_test_vector",
    "fingerprint_receipt_test_vector",
    "fingerprint_verify_contract",
    "zk_receipt_test_vectors",
    "PRODUCT_READINESS_SCHEMA",
    "PRODUCT_READINESS_TIER",
    "ProductFeatureReadiness",
    "evaluate_product_readiness",
    "write_product_readiness_report",
    "WORKFLOW_CONTRACT_SCHEMA",
    "WORKFLOW_OUTPUT_SCHEMAS",
    "validate_workflow_output",
    "validate_workflow_outputs",
    "ProvenanceWorkflowResult",
    "FingerprintWorkflowResult",
    "WatermarkWorkflowResult",
    "AttestationWorkflowResult",
    "provenance_workflow",
    "fingerprint_workflow",
    "watermark_workflow",
    "attestation_workflow",
]


def __getattr__(name: str):
    workflow_exports = {
        "ProvenanceWorkflowResult",
        "FingerprintWorkflowResult",
        "WatermarkWorkflowResult",
        "AttestationWorkflowResult",
        "provenance_workflow",
        "fingerprint_workflow",
        "watermark_workflow",
        "attestation_workflow",
    }
    product_exports = {
        "PRODUCT_READINESS_SCHEMA",
        "PRODUCT_READINESS_TIER",
        "ProductFeatureReadiness",
        "evaluate_product_readiness",
        "write_product_readiness_report",
    }
    contract_exports = {
        "WORKFLOW_CONTRACT_SCHEMA",
        "WORKFLOW_OUTPUT_SCHEMAS",
        "validate_workflow_output",
        "validate_workflow_outputs",
    }
    if name in workflow_exports:
        from . import workflows

        return getattr(workflows, name)
    if name in product_exports:
        from . import product_readiness

        return getattr(product_readiness, name)
    if name in contract_exports:
        from . import workflow_contracts

        return getattr(workflow_contracts, name)
    raise AttributeError(f"module 'src.trust' has no attribute {name!r}")
