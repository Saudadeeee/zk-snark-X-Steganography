"""Section 45 - Trust Architecture Evidence Gate.

This section distills the diagnostic trust-plane output into claim-gated
evidence. It does not replace the frozen CAVLC paper baseline. Its purpose is
to make Upgrade-v2 evidence auditable without overstating public-dataset or
production-robustness claims.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import RESULTS_DIR, PALETTE, save_fig, setup_style

DIAGNOSTIC_PATH = RESULTS_DIR / "trust_architecture_diagnostic.json"
OUTPUT_PATH = RESULTS_DIR / "sec45_trust_evidence_data.json"
CORPUS_MANIFEST_PATH = Path(__file__).resolve().parent / "trust_corpus_manifest.json"


def _load_or_run_diagnostic() -> dict[str, Any]:
    if DIAGNOSTIC_PATH.exists():
        return json.loads(DIAGNOSTIC_PATH.read_text(encoding="utf-8"))
    from benchmark.trust_architecture_diagnostic import run_diagnostic

    return run_diagnostic()


def _best_threshold_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    eligible = [
        row
        for row in rows
        if float(row.get("true_accept_rate", 0.0)) >= 1.0
        and float(row.get("false_accept_rate", 1.0)) <= 0.0
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda row: int(row.get("threshold", 0)))


def collect_data() -> dict[str, Any]:
    diagnostic = _load_or_run_diagnostic()
    corpus_manifest = json.loads(CORPUS_MANIFEST_PATH.read_text(encoding="utf-8"))
    fingerprint = diagnostic["fingerprint_registry"]
    watermark = diagnostic["watermark_receipt"]
    circuits = diagnostic["circuits"]

    real_clip = fingerprint["real_clip_benchmark"]
    best_real_threshold = _best_threshold_row(real_clip.get("rows", []))
    keyed = watermark["keyed_template_benchmark"]
    stress = watermark["keyed_template_stress_benchmark"]

    claim_gates = {
        "c2pa_anchor": {
            "status": "supported",
            "evidence": "32-byte manifest root payload roundtrip and tamper detection",
            "passed": bool(
                diagnostic["c2pa_bridge"]["embedded_payload_valid"]
                and diagnostic["c2pa_bridge"]["embedded_payload_tamper_detected"]
                and diagnostic["c2pa_bridge"]["manifest_tamper_detected"]
            ),
        },
        "fingerprint_local_registry": {
            "status": "supported_local_corpus",
            "evidence": "registered local H.264 corpus threshold sweep",
            "passed": best_real_threshold is not None and int(real_clip.get("clip_count", 0)) >= 8,
            "clip_count": int(real_clip.get("clip_count", 0)),
            "best_zero_far_threshold": int(best_real_threshold["threshold"]) if best_real_threshold else None,
        },
        "watermark_receipt": {
            "status": "supported_synthetic_stress",
            "evidence": "keyed-template detector with resynchronized stress matrix",
            "passed": bool(
                keyed["summary"]["positive_accept_rate"] >= 1.0
                and keyed["summary"]["false_accept_rate"] <= 0.0
                and stress["summary"]["resynchronized_accept_rate"] >= 1.0
            ),
            "fixed_accept_rate": float(stress["summary"]["fixed_accept_rate"]),
            "resynchronized_accept_rate": float(stress["summary"]["resynchronized_accept_rate"]),
        },
        "tee_attestation": {
            "status": "interface_supported_mock_signer",
            "evidence": "canonical bundle signing and sidecar roundtrip",
            "passed": bool(
                diagnostic["attestation"]["signature_valid"]
                and diagnostic["attestation"]["sidecar_roundtrip_valid"]
            ),
        },
        "ready_workflows": {
            "status": "ready_to_use_api_surface",
            "evidence": "src.trust.workflows facade covers provenance, fingerprint, watermark, and attestation",
            "passed": bool(
                diagnostic["ready_workflows"]["provenance_valid"]
                and diagnostic["ready_workflows"]["fingerprint_match"]["matched"]
                and diagnostic["ready_workflows"]["watermark_valid"]
                and diagnostic["ready_workflows"]["attestation_valid"]
            ),
        },
        "zk_circuits": {
            "status": "supported_for_toy_relations",
            "evidence": "fingerprint and detector receipt circuits compile and Groth16 verify",
            "passed": bool(
                circuits["fingerprint_verify"]["compile_ok"]
                and circuits["fingerprint_verify"]["groth16_measurement"]["verified"]
                and circuits["detector_receipt"]["compile_ok"]
                and circuits["detector_receipt"]["groth16_measurement"]["verified"]
            ),
            "fingerprint_non_linear_constraints": int(
                circuits["fingerprint_verify"]["stats"]["non_linear_constraints"]
            ),
            "detector_non_linear_constraints": int(
                circuits["detector_receipt"]["stats"]["non_linear_constraints"]
            ),
        },
    }

    blockers = []
    if corpus_manifest.get("external_public_dataset") is not True:
        blockers.append("No non-local or externally curated real-video corpus is registered.")
    if watermark["keyed_template_stress_benchmark"]["summary"]["available_count"] < 7:
        blockers.append("Watermark stress matrix has insufficient available transforms.")
    if diagnostic.get("tier") != "diagnostic_grade":
        blockers.append("Source diagnostic remains diagnostic-grade, not frozen paper-grade.")

    output = {
        "tier": "claim_gated_evidence",
        "source": str(DIAGNOSTIC_PATH),
        "source_tier": diagnostic.get("tier"),
        "corpus_manifest": corpus_manifest,
        "promotion_ready": not blockers and all(gate["passed"] for gate in claim_gates.values()),
        "blockers": blockers,
        "claim_gates": claim_gates,
        "metrics": {
            "fingerprint_clip_count": int(real_clip.get("clip_count", 0)),
            "fingerprint_best_zero_far_threshold": (
                int(best_real_threshold["threshold"]) if best_real_threshold else None
            ),
            "keyed_template_threshold": float(keyed["threshold"]),
            "keyed_template_score_margin": float(keyed["score_margin"]),
            "watermark_fixed_accept_rate": float(stress["summary"]["fixed_accept_rate"]),
            "watermark_resynchronized_accept_rate": float(stress["summary"]["resynchronized_accept_rate"]),
            "fingerprint_groth16_verified": bool(circuits["fingerprint_verify"]["groth16_measurement"]["verified"]),
            "detector_groth16_verified": bool(circuits["detector_receipt"]["groth16_measurement"]["verified"]),
            "ready_workflows_valid": bool(claim_gates["ready_workflows"]["passed"]),
        },
    }
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=True, indent=2), encoding="utf-8")
    return output


def plot_summary(data: dict[str, Any]) -> None:
    gates = data["claim_gates"]
    labels = list(gates.keys())
    values = [1.0 if gates[label]["passed"] else 0.0 for label in labels]
    colors = [PALETTE["this_work"] if value else PALETTE["lsb"] for value in values]

    setup_style()
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.barh(labels, values, color=colors)
    ax.set_xlim(0, 1.05)
    ax.set_xlabel("Gate passed")
    ax.set_title("Section 45 Trust Architecture Claim Gates")
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["blocked", "passed"])
    for idx, label in enumerate(labels):
        status = gates[label]["status"]
        ax.text(0.02, idx, status, va="center", ha="left", color="white", fontsize=8)
    save_fig(fig, "sec45_trust_evidence_summary")


def run() -> dict[str, Any]:
    print("\n=== Section 45 Trust Architecture Evidence Gate ===")
    data = collect_data()
    plot_summary(data)
    passed = sum(1 for gate in data["claim_gates"].values() if gate["passed"])
    print(f"  claim gates: {passed}/{len(data['claim_gates'])} passed")
    print(f"  promotion_ready: {data['promotion_ready']}")
    for blocker in data["blockers"]:
        print(f"  blocker: {blocker}")
    return data


if __name__ == "__main__":
    run()
