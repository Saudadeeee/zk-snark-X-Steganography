"""Regression tests for honest separation of proof and signature measurements."""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.sec5_zkp import _measure_ecdsa_signature, build_comparison_report


def test_ecdsa_measurement_is_explicitly_not_a_zero_knowledge_proof() -> None:
    measurement = _measure_ecdsa_signature(n_trials=2)

    assert measurement["category"] == "digital_signature"
    assert measurement["zero_knowledge"] is False
    assert measurement["simulated"] is False
    assert measurement["signature_size_bytes_mean"] > 0
    assert measurement["signing_time_ms_mean"] > 0
    assert measurement["verification_time_ms_mean"] > 0
    assert "proof_size_bytes" not in measurement
    assert "prove_time_ms" not in measurement


def test_signature_baselines_are_separate_from_zkp_systems() -> None:
    groth16 = {"proof_size_bytes": 147, "simulated": False}
    ecdsa = {
        "category": "digital_signature",
        "zero_knowledge": False,
        "signature_size_bytes": 71,
    }

    report = build_comparison_report({"Groth16 BN128": groth16}, {"ECDSA P-256": ecdsa})

    assert report["schema_version"] == 2
    assert report["proof_systems"] == {"Groth16 BN128": groth16}
    assert report["signature_baselines"] == {"ECDSA P-256": ecdsa}
    assert "ECDSA P-256" not in report["proof_systems"]
