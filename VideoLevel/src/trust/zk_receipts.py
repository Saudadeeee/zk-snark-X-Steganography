"""Versioned contracts for toy ZK receipt circuits.

The circuits in this module are deliberately small future-branch relations.
They define how public signals should be interpreted for the current toy
fingerprint and detector-receipt Circom programs. They do not claim production
privacy, production detector parity, or full registry inclusion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .canonical import canonical_json_hash


ZK_RECEIPT_CONTRACT_REPORT_SCHEMA = "zk-stego-zk-receipt-contract-report-v1"
ZK_RECEIPT_CIRCUIT_CONTRACT_SCHEMA = "zk-stego-zk-receipt-circuit-contract-v1"
ZK_RECEIPT_TEST_VECTOR_SCHEMA = "zk-stego-zk-receipt-test-vector-v1"
ZK_RECEIPT_VALIDATION_SCHEMA = "zk-stego-zk-receipt-validation-v1"
ZK_RECEIPT_CONTRACT_TIER = "zk_receipt_contract_diagnostic"

FINGERPRINT_VERIFY_CIRCUIT = "fingerprint_verify"
DETECTOR_RECEIPT_CIRCUIT = "detector_receipt"

FINGERPRINT_TEST_COMMITMENT = "21451698921772718435912221772150976482499822594119359987538900709054009240964"
DETECTOR_TEST_COMMITMENT = "4220715926047232732883364092278159128484462297542435605209235091838322135833"


@dataclass(frozen=True)
class ZKReceiptCircuitContract:
    """Public/private signal layout for a toy receipt circuit."""

    circuit_name: str
    relation: str
    public_outputs: tuple[str, ...]
    public_inputs: tuple[str, ...]
    private_inputs: tuple[str, ...]
    public_signal_order: tuple[str, ...]
    claim_scope: str
    limitations: tuple[str, ...]
    schema: str = ZK_RECEIPT_CIRCUIT_CONTRACT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "circuit_name": self.circuit_name,
            "relation": self.relation,
            "public_outputs": list(self.public_outputs),
            "public_inputs": list(self.public_inputs),
            "private_inputs": list(self.private_inputs),
            "public_signal_order": list(self.public_signal_order),
            "claim_scope": self.claim_scope,
            "limitations": list(self.limitations),
            "contract_commitment": self.commitment(),
        }

    def commitment(self) -> str:
        return canonical_json_hash(
            {
                "schema": self.schema,
                "circuit_name": self.circuit_name,
                "relation": self.relation,
                "public_outputs": list(self.public_outputs),
                "public_inputs": list(self.public_inputs),
                "private_inputs": list(self.private_inputs),
                "public_signal_order": list(self.public_signal_order),
                "claim_scope": self.claim_scope,
                "limitations": list(self.limitations),
            }
        )


@dataclass(frozen=True)
class ZKReceiptValidationReport:
    """Validation result for one test vector/public-signal pair."""

    circuit_name: str
    verified: bool
    relation_valid: bool
    public_layout_valid: bool
    contract_commitment: str
    witness_commitment: str
    public_signal_count: int
    expected_public_signal_count: int
    reason: str | None = None
    schema: str = ZK_RECEIPT_VALIDATION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "circuit_name": self.circuit_name,
            "verified": self.verified,
            "relation_valid": self.relation_valid,
            "public_layout_valid": self.public_layout_valid,
            "contract_commitment": self.contract_commitment,
            "witness_commitment": self.witness_commitment,
            "public_signal_count": self.public_signal_count,
            "expected_public_signal_count": self.expected_public_signal_count,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ZKReceiptTestVector:
    """Public toy test vector for one receipt circuit."""

    contract: ZKReceiptCircuitContract
    witness: dict[str, Any]
    expected_public_signals: tuple[str, ...]
    expected_relation_result: bool
    schema: str = ZK_RECEIPT_TEST_VECTOR_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "contract_commitment": self.contract.commitment(),
            "circuit_name": self.contract.circuit_name,
            "witness": self.witness,
            "witness_commitment": self.witness_commitment(),
            "expected_public_signals": list(self.expected_public_signals),
            "expected_relation_result": self.expected_relation_result,
        }

    def witness_commitment(self) -> str:
        return canonical_json_hash(self.witness)

    def validate(self, public_signals: Sequence[Any] | None = None) -> ZKReceiptValidationReport:
        observed = _string_signals(public_signals or self.expected_public_signals)
        expected = _string_signals(self.expected_public_signals)
        relation_valid, relation_reason = _relation_valid(self.contract.circuit_name, self.witness, observed)
        public_layout_valid = observed == expected
        reason = None
        if len(observed) != len(expected):
            reason = f"public signal count mismatch: {len(observed)} != {len(expected)}"
        elif not relation_valid:
            reason = relation_reason
        elif not public_layout_valid:
            reason = "public signal layout mismatch"

        return ZKReceiptValidationReport(
            circuit_name=self.contract.circuit_name,
            verified=relation_valid and public_layout_valid,
            relation_valid=relation_valid,
            public_layout_valid=public_layout_valid,
            contract_commitment=self.contract.commitment(),
            witness_commitment=self.witness_commitment(),
            public_signal_count=len(observed),
            expected_public_signal_count=len(expected),
            reason=reason,
        )


def fingerprint_verify_contract() -> ZKReceiptCircuitContract:
    return ZKReceiptCircuitContract(
        circuit_name=FINGERPRINT_VERIFY_CIRCUIT,
        relation="hamming_distance_lte_threshold_with_poseidon_record_commitment",
        public_outputs=("matched", "registry_commitment"),
        public_inputs=("query_bits[64]", "threshold"),
        private_inputs=("record_bits[64]", "record_chunks[8]"),
        public_signal_order=("matched", "registry_commitment", "query_bits[64]", "threshold"),
        claim_scope=(
            "Toy 64-bit fingerprint threshold proof. The proof binds a private "
            "record to a public Poseidon commitment and proves Hamming distance "
            "is below threshold."
        ),
        limitations=(
            "No Merkle registry inclusion.",
            "No private multi-record search.",
            "No full video fingerprint extraction inside the circuit.",
            "Poseidon commitment is treated as the circuit public output, not recomputed in Python.",
        ),
    )


def detector_receipt_contract() -> ZKReceiptCircuitContract:
    return ZKReceiptCircuitContract(
        circuit_name=DETECTOR_RECEIPT_CIRCUIT,
        relation="private_weight_dot_product_gte_threshold_with_poseidon_weight_commitment",
        public_outputs=("accepted", "detector_commitment"),
        public_inputs=("features[4]", "threshold"),
        private_inputs=("weights[4]",),
        public_signal_order=("accepted", "detector_commitment", "features[4]", "threshold"),
        claim_scope=(
            "Toy detector-score receipt. The proof keeps detector weights private, "
            "binds them to a public Poseidon commitment, and proves score >= threshold."
        ),
        limitations=(
            "No robust video feature extractor inside the circuit.",
            "No calibrated detector-version governance.",
            "No production watermark detector parity.",
            "Poseidon commitment is treated as the circuit public output, not recomputed in Python.",
        ),
    )


def fingerprint_receipt_test_vector() -> ZKReceiptTestVector:
    bits = [0] * 32 + [1] * 32
    chunks = _pack_bits_to_bytes(bits)
    witness = {
        "query_bits": bits,
        "record_bits": bits,
        "record_chunks": chunks,
        "threshold": 0,
    }
    expected = tuple(["1", FINGERPRINT_TEST_COMMITMENT, *[str(bit) for bit in bits], "0"])
    return ZKReceiptTestVector(
        contract=fingerprint_verify_contract(),
        witness=witness,
        expected_public_signals=expected,
        expected_relation_result=True,
    )


def detector_receipt_test_vector() -> ZKReceiptTestVector:
    witness = {
        "features": [100, 100, 50, 50],
        "weights": [25, 25, 25, 25],
        "threshold": 7000,
    }
    expected = tuple(["1", DETECTOR_TEST_COMMITMENT, "100", "100", "50", "50", "7000"])
    return ZKReceiptTestVector(
        contract=detector_receipt_contract(),
        witness=witness,
        expected_public_signals=expected,
        expected_relation_result=True,
    )


def zk_receipt_test_vectors() -> tuple[ZKReceiptTestVector, ...]:
    return (fingerprint_receipt_test_vector(), detector_receipt_test_vector())


def build_zk_receipt_contract_report(
    circuits_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a report for section 47 and product-readiness evidence."""

    circuits_data = circuits_data if isinstance(circuits_data, dict) else {}
    circuit_reports: dict[str, Any] = {}
    bound_count = 0
    valid_count = 0

    for vector in zk_receipt_test_vectors():
        circuit_name = vector.contract.circuit_name
        circuit_data = circuits_data.get(circuit_name, {})
        measurement = circuit_data.get("groth16_measurement", {}) if isinstance(circuit_data, dict) else {}
        local_validation = vector.validate()
        groth16_validation = None
        groth16_verified = None
        compile_ok = None
        if isinstance(circuit_data, dict) and circuit_data:
            compile_ok = circuit_data.get("compile_ok")
            groth16_verified = measurement.get("verified") if isinstance(measurement, dict) else None
            public_signals = measurement.get("public_signals") if isinstance(measurement, dict) else None
            if isinstance(public_signals, list):
                bound_count += 1
                groth16_validation = vector.validate(public_signals).to_dict()

        contract_valid = local_validation.verified
        if groth16_validation is not None:
            contract_valid = contract_valid and bool(groth16_validation["verified"]) and groth16_verified is True
        if compile_ok is not None:
            contract_valid = contract_valid and compile_ok is True
        if contract_valid:
            valid_count += 1

        circuit_reports[circuit_name] = {
            "contract_valid": bool(contract_valid),
            "compile_ok": compile_ok,
            "groth16_verified": groth16_verified,
            "contract": vector.contract.to_dict(),
            "test_vector": vector.to_dict(),
            "local_validation": local_validation.to_dict(),
            "groth16_measurement_validation": groth16_validation,
        }

    return {
        "schema": ZK_RECEIPT_CONTRACT_REPORT_SCHEMA,
        "tier": ZK_RECEIPT_CONTRACT_TIER,
        "summary": {
            "all_contracts_valid": valid_count == len(circuit_reports),
            "valid_contract_count": valid_count,
            "circuit_count": len(circuit_reports),
            "groth16_bound_count": bound_count,
            "claim_scope": "Versioned public-signal layout and toy test vectors for reduced ZK receipt relations.",
        },
        "circuits": circuit_reports,
        "limitations": [
            "These are toy reduced relations, not production privacy-preserving video verifiers.",
            "Fingerprint proof lacks registry inclusion and private multi-record lookup.",
            "Detector proof lacks real robust-video detector parity and feature extraction in-circuit.",
            "Trusted setup and proving-key governance remain outside this contract.",
        ],
    }


def _string_signals(values: Sequence[Any]) -> list[str]:
    return [str(value) for value in values]


def _pack_bits_to_bytes(bits: Sequence[int]) -> list[int]:
    if len(bits) % 8 != 0:
        raise ValueError("bit length must be divisible by 8")
    chunks: list[int] = []
    for offset in range(0, len(bits), 8):
        value = 0
        for bit_index, bit in enumerate(bits[offset : offset + 8]):
            value += int(bit) * (1 << bit_index)
        chunks.append(value)
    return chunks


def _relation_valid(circuit_name: str, witness: dict[str, Any], observed: Sequence[str]) -> tuple[bool, str | None]:
    if circuit_name == FINGERPRINT_VERIFY_CIRCUIT:
        return _fingerprint_relation_valid(witness, observed)
    if circuit_name == DETECTOR_RECEIPT_CIRCUIT:
        return _detector_relation_valid(witness, observed)
    return False, f"unknown circuit: {circuit_name}"


def _fingerprint_relation_valid(witness: dict[str, Any], observed: Sequence[str]) -> tuple[bool, str | None]:
    query_bits = [int(bit) for bit in witness["query_bits"]]
    record_bits = [int(bit) for bit in witness["record_bits"]]
    threshold = int(witness["threshold"])
    record_chunks = [int(value) for value in witness["record_chunks"]]
    if len(query_bits) != 64 or len(record_bits) != 64 or len(record_chunks) != 8:
        return False, "fingerprint witness dimensions are invalid"
    if any(bit not in (0, 1) for bit in query_bits + record_bits):
        return False, "fingerprint bits must be boolean"
    if record_chunks != _pack_bits_to_bytes(record_bits):
        return False, "record_chunks do not match record_bits"
    if len(observed) != 67:
        return False, "fingerprint public signal count must be 67"
    distance = sum(1 for q_bit, r_bit in zip(query_bits, record_bits) if q_bit != r_bit)
    matched = 1 if distance <= threshold else 0
    if observed[0] != str(matched):
        return False, "fingerprint matched output disagrees with witness relation"
    if list(observed[2:66]) != [str(bit) for bit in query_bits]:
        return False, "fingerprint query_bits public inputs mismatch"
    if observed[66] != str(threshold):
        return False, "fingerprint threshold public input mismatch"
    return True, None


def _detector_relation_valid(witness: dict[str, Any], observed: Sequence[str]) -> tuple[bool, str | None]:
    features = [int(value) for value in witness["features"]]
    weights = [int(value) for value in witness["weights"]]
    threshold = int(witness["threshold"])
    if len(features) != 4 or len(weights) != 4:
        return False, "detector witness dimensions are invalid"
    if any(value < 0 or value >= 2**16 for value in features + weights):
        return False, "detector features and weights must fit uint16"
    if len(observed) != 7:
        return False, "detector public signal count must be 7"
    score = sum(feature * weight for feature, weight in zip(features, weights))
    accepted = 1 if score >= threshold else 0
    if observed[0] != str(accepted):
        return False, "detector accepted output disagrees with witness relation"
    if list(observed[2:6]) != [str(value) for value in features]:
        return False, "detector features public inputs mismatch"
    if observed[6] != str(threshold):
        return False, "detector threshold public input mismatch"
    return True, None
