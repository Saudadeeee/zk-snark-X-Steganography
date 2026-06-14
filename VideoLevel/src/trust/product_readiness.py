"""Product-readiness gates for the Upgrade-v2 trust plane.

The trust modules are useful, but they do not all support the same claim
strength. This module turns that boundary into a machine-readable contract.
Only entries with ``product_ready=true`` may be described as production-ready.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT / "benchmark" / "results"
SEC45_PATH = RESULTS_DIR / "sec45_trust_evidence_data.json"
TRUST_CORPUS_VALIDATION_PATH = RESULTS_DIR / "trust_corpus_validation.json"
PRODUCT_READINESS_PATH = RESULTS_DIR / "sec46_product_readiness_data.json"

PRODUCT_READINESS_SCHEMA = "zk-stego-product-readiness-v1"
PRODUCT_READINESS_TIER = "product_readiness_gate"

STATUS_PRODUCT_READY = "product_ready"
STATUS_PRODUCT_SEED = "product_seed"
STATUS_PROTOTYPE = "prototype"
STATUS_BLOCKED = "blocked"
ALLOWED_STATUSES = {
    STATUS_PRODUCT_READY,
    STATUS_PRODUCT_SEED,
    STATUS_PROTOTYPE,
    STATUS_BLOCKED,
}


@dataclass(frozen=True)
class ProductFeatureReadiness:
    """Readiness state for one product-facing trust feature."""

    feature: str
    status: str
    seed_ready: bool
    claim_scope: str
    ready_for: tuple[str, ...]
    evidence: tuple[str, ...]
    product_blockers: tuple[str, ...]
    required_next_steps: tuple[str, ...]

    @property
    def product_ready(self) -> bool:
        return self.status == STATUS_PRODUCT_READY and not self.product_blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "status": self.status,
            "seed_ready": bool(self.seed_ready),
            "product_ready": bool(self.product_ready),
            "claim_scope": self.claim_scope,
            "ready_for": list(self.ready_for),
            "evidence": list(self.evidence),
            "product_blockers": list(self.product_blockers),
            "required_next_steps": list(self.required_next_steps),
        }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _gate(sec45_data: dict[str, Any], name: str) -> dict[str, Any]:
    gates = sec45_data.get("claim_gates", {})
    gate = gates.get(name, {}) if isinstance(gates, dict) else {}
    return gate if isinstance(gate, dict) else {}


def _gate_passed(sec45_data: dict[str, Any], name: str) -> bool:
    return bool(_gate(sec45_data, name).get("passed"))


def _metric(sec45_data: dict[str, Any], name: str, default: Any = None) -> Any:
    metrics = sec45_data.get("metrics", {})
    if not isinstance(metrics, dict):
        return default
    return metrics.get(name, default)


def _corpus(sec45_data: dict[str, Any], corpus_validation: dict[str, Any]) -> dict[str, Any]:
    embedded = sec45_data.get("corpus_validation", {})
    if isinstance(embedded, dict) and embedded:
        return embedded
    return corpus_validation if isinstance(corpus_validation, dict) else {}


def _evidence_from_gate(sec45_data: dict[str, Any], name: str, fallback: str) -> tuple[str, ...]:
    gate = _gate(sec45_data, name)
    evidence = gate.get("evidence")
    if isinstance(evidence, str) and evidence:
        return (evidence,)
    return (fallback,)


def evaluate_product_readiness(
    sec45_data: dict[str, Any] | None = None,
    corpus_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the conservative product-readiness report.

    Section 45 answers whether evidence gates pass. This function answers a
    stricter question: whether each feature is safe to present as a product
    capability, and under which scope.
    """

    sec45 = sec45_data if isinstance(sec45_data, dict) else _load_json(SEC45_PATH)
    corpus_data = (
        corpus_validation
        if isinstance(corpus_validation, dict)
        else _load_json(TRUST_CORPUS_VALIDATION_PATH)
    )
    corpus = _corpus(sec45, corpus_data)

    c2pa_seed = _gate_passed(sec45, "c2pa_anchor")
    fingerprint_seed = bool(
        _gate_passed(sec45, "fingerprint_local_registry")
        and _gate_passed(sec45, "fingerprint_external_corpus")
        and corpus.get("schema_valid") is True
    )
    watermark_seed = _gate_passed(sec45, "watermark_receipt")
    tee_interface = _gate_passed(sec45, "tee_attestation")
    workflow_seed = _gate_passed(sec45, "ready_workflows")
    zk_toy_seed = _gate_passed(sec45, "zk_circuits")
    zk_contract_count = int(_gate(sec45, "zk_circuits").get("contract_circuit_count") or 0)
    zk_bound_count = int(_gate(sec45, "zk_circuits").get("groth16_bound_count") or 0)

    external_files = int(corpus.get("external_file_count") or 0)
    external_hash_matches = int(corpus.get("external_hash_match_count") or 0)
    local_count = int(corpus.get("local_existing_count") or corpus.get("local_registered_count") or 0)
    fixed_accept_rate = float(_metric(sec45, "watermark_fixed_accept_rate", 0.0) or 0.0)
    resync_accept_rate = float(_metric(sec45, "watermark_resynchronized_accept_rate", 0.0) or 0.0)

    broad_corpus_blocker = (
        f"External seed corpus has {external_files} files; broad public-dataset "
        "claims require a larger, diverse external corpus with recorded hashes."
    )

    features = [
        ProductFeatureReadiness(
            feature="c2pa_root_anchor",
            status=STATUS_PRODUCT_READY if c2pa_seed else STATUS_BLOCKED,
            seed_ready=c2pa_seed,
            claim_scope=(
                "Recoverable 32-byte C2PA-style provenance root payload plus "
                "JSON audit sidecar and local registry resolver; not full C2PA SDK compliance."
            ),
            ready_for=(
                "anchoring a manifest root inside the compressed-domain payload",
                "detecting manifest or embedded-root mismatch when the root is extractable",
                "publishing and resolving manifest-root records through a local JSON registry",
            ) if c2pa_seed else (),
            evidence=_evidence_from_gate(
                sec45,
                "c2pa_anchor",
                "Section 45 C2PA root-anchor evidence is unavailable.",
            ),
            product_blockers=(),
            required_next_steps=(
                "Integrate an actual C2PA manifest signer/verifier or documented bridge adapter.",
                "Add platform round-trip tests where external metadata is stripped but the embedded root remains recoverable.",
                "Add public registry integration if claims move beyond local root-anchor resolution.",
            ),
        ),
        ProductFeatureReadiness(
            feature="fingerprint_registry",
            status=STATUS_PRODUCT_READY if fingerprint_seed else STATUS_BLOCKED,
            seed_ready=fingerprint_seed,
            claim_scope=(
                "Canonical asset matching against a local registry using deterministic "
                "luma fingerprints, lookup policies, and auditable lookup receipts; "
                "this is not a deepfake detector."
            ),
            ready_for=(
                f"local registry matching over {local_count} registered local H.264 assets",
                f"external seed-corpus sanity over {external_hash_matches}/{external_files} hash-verified files",
                "local canonical-asset lookup receipts bound to registry, query, and policy commitments",
            ) if fingerprint_seed else (),
            evidence=(
                *_evidence_from_gate(sec45, "fingerprint_local_registry", "Local fingerprint gate is unavailable."),
                *_evidence_from_gate(sec45, "fingerprint_external_corpus", "External fingerprint gate is unavailable."),
            ),
            product_blockers=(),
            required_next_steps=(
                "Grow the external corpus and keep per-source, per-codec, and per-transform metrics separated.",
                "Define registry API semantics for enrollment, lookup thresholds, revocation, and audit logging.",
                "Replace toy fingerprint proof relations with a real inclusion or policy-compliance relation if privacy is claimed.",
                broad_corpus_blocker,
            ),
        ),
        ProductFeatureReadiness(
            feature="watermark_receipt",
            status=STATUS_PRODUCT_READY if watermark_seed else STATUS_BLOCKED,
            seed_ready=watermark_seed,
            claim_scope=(
                "Controlled keyed-template receipt with policy commitment, detector "
                "commitment, resynchronized score, and replay verification; not a "
                "SynthID/Video-Seal-class robust watermark."
            ),
            ready_for=(
                "controlled watermark-receipt demos",
                f"synthetic transform diagnostics with fixed_accept_rate={fixed_accept_rate:.4f}",
                f"resynchronized diagnostics with accept_rate={resync_accept_rate:.4f}",
                "local replay verification of detector receipt against frames, key, policy, and payload commitment",
            ) if watermark_seed else (),
            evidence=_evidence_from_gate(
                sec45,
                "watermark_receipt",
                "Section 45 watermark receipt evidence is unavailable.",
            ),
            product_blockers=(),
            required_next_steps=(
                "Define a real detector contract and a public robustness matrix.",
                "Add lossy re-encode, crop/scale, frame-rate, trim, and compositing fixtures with false-accept controls.",
                "Bind detector version, key commitment, score, and threshold into the ZK receipt relation.",
                "Do not describe this as SynthID/Video-Seal-level robust watermarking.",
            ),
        ),
        ProductFeatureReadiness(
            feature="tee_model_attestation",
            status=STATUS_PROTOTYPE if tee_interface else STATUS_BLOCKED,
            seed_ready=False,
            claim_scope=(
                "Canonical model/video/policy attestation bundle with mock HMAC "
                "and Ed25519 software signing; not a hardware TEE quote or "
                "vendor-root attestation."
            ),
            ready_for=(
                "interface tests and sidecar format experiments",
                "local demos that need deterministic mock signatures",
                "software-signature attestation sidecars with public-key verification",
            ) if tee_interface else (),
            evidence=_evidence_from_gate(
                sec45,
                "tee_attestation",
                "Section 45 attestation interface evidence is unavailable.",
            ),
            product_blockers=(
                "Available signers are software signers and have no hardware quote.",
                "No verifier checks vendor root certificates, enclave measurement, or device identity.",
                "No runtime policy binds model binary, config, and generation event to a trusted execution report.",
            ),
            required_next_steps=(
                "Add a provider interface for real quote formats before adding vendor-specific code.",
                "Implement one real verifier path, for example SGX, SEV-SNP, Nitro Enclaves, or TPM-backed attestation.",
                "Add negative fixtures for stale quote, wrong model hash, wrong policy, and wrong device root.",
            ),
        ),
        ProductFeatureReadiness(
            feature="zk_receipt_circuits",
            status=STATUS_PROTOTYPE if zk_toy_seed else STATUS_BLOCKED,
            seed_ready=zk_toy_seed,
            claim_scope=(
                "Toy fingerprint and detector receipt circuits compile and verify; "
                "not a full privacy-preserving production verifier."
            ),
            ready_for=(
                "measuring Groth16 plumbing overhead on reduced relations",
                "paper discussion of how detector or registry receipts could be circuitized",
                f"public-signal contract regression for {zk_bound_count}/{zk_contract_count} toy circuits",
            ) if zk_toy_seed else (),
            evidence=_evidence_from_gate(
                sec45,
                "zk_circuits",
                "Section 45 ZK circuit evidence is unavailable.",
            ),
            product_blockers=(
                "Circuits do not yet encode full video parsing, robust detector scoring, or registry inclusion at production scale.",
                "Trusted setup and circuit-version governance are not productized.",
            ),
            required_next_steps=(
                "Define one production relation at a time: inclusion, continuity, detector score, model binding, or policy compliance.",
                "Add versioned proving-key metadata and trusted-setup governance for each promoted circuit.",
                "Replace toy public-signal contracts with production relation contracts before making privacy-preserving verifier claims.",
            ),
        ),
        ProductFeatureReadiness(
            feature="zkml_model_binding",
            status=STATUS_BLOCKED,
            seed_ready=False,
            claim_scope=(
                "Interface-only ZKML model-binding placeholder; no model inference "
                "or model-output proof is implemented."
            ),
            ready_for=(),
            evidence=("ZKMLInterfaceSpec is intentionally interface-only.",),
            product_blockers=(
                "No ZKML circuit or proving backend is implemented.",
                "No model architecture, quantization policy, or inference trace format is fixed.",
                "No realistic proving-cost budget exists for full video-generation model binding.",
            ),
            required_next_steps=(
                "Keep ZKML as a high-assurance future tier until a small realistic model-binding relation is chosen.",
                "Prototype a tiny classifier or detector proof before claiming generated-by-model provenance.",
            ),
        ),
        ProductFeatureReadiness(
            feature="workflow_api_cli",
            status=STATUS_PRODUCT_READY if workflow_seed else STATUS_BLOCKED,
            seed_ready=workflow_seed,
            claim_scope=(
                "Stable local Python and CLI facade for provenance, fingerprint, "
                "watermark receipt, and software attestation workflows."
            ),
            ready_for=(
                "local integration demos",
                "repeatable benchmark workflows",
                "paper artifact reproduction",
            ) if workflow_seed else (),
            evidence=_evidence_from_gate(
                sec45,
                "ready_workflows",
                "Section 45 workflow evidence is unavailable.",
            ),
            product_blockers=(),
            required_next_steps=(
                "Add a multi-version compatibility matrix when workflow schemas change.",
                "Define packaging and deployment hardening before exposing this as a hosted service.",
                "Define semantic-version rules for workflow schema changes.",
            ),
        ),
    ]

    feature_dicts = [feature.to_dict() for feature in features]
    product_ready_count = sum(1 for feature in feature_dicts if feature["product_ready"])
    seed_ready_count = sum(1 for feature in feature_dicts if feature["seed_ready"])
    prototype_count = sum(1 for feature in feature_dicts if feature["status"] == STATUS_PROTOTYPE)
    blocked_count = sum(1 for feature in feature_dicts if feature["status"] == STATUS_BLOCKED)
    seed_surface_ready = all(
        feature["seed_ready"]
        for feature in feature_dicts
        if feature["feature"] in {"c2pa_root_anchor", "fingerprint_registry", "workflow_api_cli"}
    )
    all_product_ready = all(feature["product_ready"] for feature in feature_dicts)

    report = {
        "schema": PRODUCT_READINESS_SCHEMA,
        "tier": PRODUCT_READINESS_TIER,
        "source": {
            "sec45_path": str(SEC45_PATH),
            "trust_corpus_validation_path": str(TRUST_CORPUS_VALIDATION_PATH),
            "sec45_promotion_ready": bool(sec45.get("promotion_ready")),
        },
        "summary": {
            "all_product_ready": bool(all_product_ready),
            "seed_surface_ready": bool(seed_surface_ready),
            "product_ready_count": int(product_ready_count),
            "seed_ready_count": int(seed_ready_count),
            "prototype_count": int(prototype_count),
            "blocked_count": int(blocked_count),
            "total_feature_count": len(feature_dicts),
            "policy": (
                "Only features with product_ready=true may be described as production-ready. "
                "product_seed means usable inside the stated seed scope only."
            ),
        },
        "features": feature_dicts,
        "claim_language": {
            "allowed_now": [
                "Upgrade-v2 provides a ready-to-use local API/CLI surface for trust-workflow experiments.",
                "C2PA-style root anchoring and fingerprint registry lookup are seed-product surfaces under explicit corpus scope.",
                "Fingerprint matching proves canonical asset similarity against a registry, not that a video is or is not a deepfake.",
                "Watermark receipts, TEE attestation, and ZKML are prototype or blocked product tracks until their blockers are closed.",
            ],
            "blocked_claims": [
                "Do not claim full C2PA compliance.",
                "Do not claim broad public-video fingerprint robustness from the two-file external seed corpus.",
                "Do not claim SynthID/Video-Seal-level robust watermarking.",
                "Do not claim hardware-backed model/device attestation from software signers.",
                "Do not claim generated-by-exact-model provenance until a real TEE or ZKML binding exists.",
            ],
        },
    }
    return report


def write_product_readiness_report(
    report: dict[str, Any] | None = None,
    path: str | Path = PRODUCT_READINESS_PATH,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = report if isinstance(report, dict) else evaluate_product_readiness()
    output_path.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Emit Upgrade-v2 product-readiness gates")
    parser.add_argument(
        "--output",
        type=Path,
        default=PRODUCT_READINESS_PATH,
        help="Output JSON path",
    )
    args = parser.parse_args()

    report = evaluate_product_readiness()
    path = write_product_readiness_report(report, args.output)
    summary = report["summary"]
    print(f"product_readiness: wrote {path}")
    print(f"  all_product_ready: {summary['all_product_ready']}")
    print(f"  seed_surface_ready: {summary['seed_surface_ready']}")
    print(f"  product_ready_count: {summary['product_ready_count']}/{summary['total_feature_count']}")


if __name__ == "__main__":
    main()
