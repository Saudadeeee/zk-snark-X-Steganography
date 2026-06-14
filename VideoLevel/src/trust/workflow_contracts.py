"""Versioned output contracts for Upgrade-v2 trust workflows."""

from __future__ import annotations

from typing import Any


WORKFLOW_CONTRACT_SCHEMA = "zk-stego-trust-workflow-contract-v1"

WORKFLOW_OUTPUT_SCHEMAS = {
    "provenance": "zk-stego-provenance-workflow-v1",
    "fingerprint": "zk-stego-fingerprint-workflow-v1",
    "watermark": "zk-stego-watermark-workflow-v1",
    "attestation": "zk-stego-attestation-workflow-v1",
}

WORKFLOW_REQUIRED_KEYS = {
    "provenance": {
        "schema",
        "workflow",
        "root",
        "sidecar",
        "verified",
        "embedded_payload_valid",
        "embedded_payload_tamper_detected",
        "manifest_tamper_detected",
        "registry_roundtrip_valid",
    },
    "fingerprint": {
        "schema",
        "workflow",
        "policy",
        "lookup_policy",
        "fingerprint",
        "registry_commitment",
        "match",
        "receipt",
    },
    "watermark": {
        "schema",
        "workflow",
        "detector",
        "detector_commitment",
        "receipt_policy",
        "fixed_receipt",
        "resynchronized_receipt",
        "resynchronized_alignment",
        "verification_report",
        "claim_scope",
        "out_of_scope",
    },
    "attestation": {
        "schema",
        "workflow",
        "bundle",
        "signed_attestation",
        "sidecar",
        "signature_valid",
        "verifier_public_key",
        "verification_policy",
        "verification_report",
    },
}


def validate_workflow_output(workflow: str, data: dict[str, Any]) -> list[str]:
    """Return schema errors for a workflow output dictionary."""

    if workflow not in WORKFLOW_OUTPUT_SCHEMAS:
        return [f"unknown workflow: {workflow}"]
    if not isinstance(data, dict):
        return [f"{workflow}: output must be an object"]

    errors: list[str] = []
    expected_schema = WORKFLOW_OUTPUT_SCHEMAS[workflow]
    if data.get("schema") != expected_schema:
        errors.append(f"{workflow}: schema must be {expected_schema}")
    if data.get("workflow") != workflow:
        errors.append(f"{workflow}: workflow must be {workflow}")

    missing = sorted(WORKFLOW_REQUIRED_KEYS[workflow] - set(data.keys()))
    if missing:
        errors.append(f"{workflow}: missing keys: {', '.join(missing)}")

    if workflow == "provenance":
        for key in ("verified", "embedded_payload_valid", "embedded_payload_tamper_detected", "manifest_tamper_detected"):
            if not isinstance(data.get(key), bool):
                errors.append(f"{workflow}: {key} must be boolean")
    elif workflow == "fingerprint":
        match = data.get("match")
        if not isinstance(match, dict):
            errors.append("fingerprint: match must be object")
        elif "matched" not in match or "registry_commitment" not in match or "candidate_count" not in match:
            errors.append("fingerprint: match must include matched, registry_commitment, and candidate_count")
        receipt = data.get("receipt")
        if not isinstance(receipt, dict):
            errors.append("fingerprint: receipt must be object")
        elif "lookup_commitment" not in receipt or "policy_commitment" not in receipt:
            errors.append("fingerprint: receipt must include lookup_commitment and policy_commitment")
    elif workflow == "watermark":
        for key in ("claim_scope", "out_of_scope"):
            if not isinstance(data.get(key), list):
                errors.append(f"watermark: {key} must be list")
        receipt = data.get("resynchronized_receipt")
        if not isinstance(receipt, dict) or "valid" not in receipt:
            errors.append("watermark: resynchronized_receipt must include valid")
        elif "receipt_commitment" not in receipt or "policy_commitment" not in receipt:
            errors.append("watermark: resynchronized_receipt must include receipt_commitment and policy_commitment")
        report = data.get("verification_report")
        if not isinstance(report, dict):
            errors.append("watermark: verification_report must be object")
        elif report.get("verified") is not True:
            errors.append("watermark: verification_report must verify")
    elif workflow == "attestation":
        if not isinstance(data.get("signature_valid"), bool):
            errors.append("attestation: signature_valid must be boolean")
        signed = data.get("signed_attestation")
        if not isinstance(signed, dict) or "scheme" not in signed:
            errors.append("attestation: signed_attestation must include scheme")
        report = data.get("verification_report")
        if not isinstance(report, dict):
            errors.append("attestation: verification_report must be object")
        elif report.get("verified") is not True:
            errors.append("attestation: verification_report must verify")

    return errors


def validate_workflow_outputs(outputs: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Validate a map of workflow name to output dictionary."""

    return {
        workflow: validate_workflow_output(workflow, outputs.get(workflow, {}))
        for workflow in WORKFLOW_OUTPUT_SCHEMAS
    }
