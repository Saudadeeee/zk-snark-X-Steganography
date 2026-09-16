"""Contracts for the default transparent lattice-ZKP sidecar.

The proof is a Fiat-Shamir proof of knowledge for a short SIS witness.  The
test deliberately exercises independent verification and every binding:
payload, proof transcript, and ML-DSA authenticated sidecar.
"""

from __future__ import annotations

import copy
import base64
import inspect
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtest._helpers import run_test, section, summarise


def t_lattice_zkp_receipt_verifies_a_short_witness_without_disclosing_it() -> None:
    from src.lattice_pq import LatticeSigner, LatticeZkReceipt

    public_key, private_key = LatticeSigner.generate_keypair()
    witness_key = bytes(range(32))
    receipt = LatticeZkReceipt.create(b"lattice-zkp-video", witness_key, private_key, signer_id="camera-01")

    assert receipt.verify(b"lattice-zkp-video", public_key)
    assert receipt.protocol == "sis-linear-fiat-shamir-v1"
    assert receipt.proof["rounds"] == 128
    assert receipt.commitment() == receipt.commitment()


def t_lattice_zkp_rejects_message_transcript_and_signature_tampering() -> None:
    from src.lattice_pq import LatticeSigner, LatticeZkReceipt

    public_key, private_key = LatticeSigner.generate_keypair()
    receipt = LatticeZkReceipt.create(b"bound payload", b"w" * 32, private_key)
    assert not receipt.verify(b"different payload", public_key)

    tampered_proof = receipt.to_dict()
    tampered_proof["proof"] = copy.deepcopy(tampered_proof["proof"])
    original_response = tampered_proof["proof"]["responses"]
    tampered_proof["proof"]["responses"] = ("B" if original_response[0] != "B" else "C") + original_response[1:]
    assert not LatticeZkReceipt.from_dict(tampered_proof).verify(b"bound payload", public_key)

    tampered_signature = receipt.to_dict()
    original_signature = tampered_signature["signature"]
    tampered_signature["signature"] = ("B" if original_signature[0] != "B" else "C") + original_signature[1:]
    assert not LatticeZkReceipt.from_dict(tampered_signature).verify(b"bound payload", public_key)


def t_lattice_zkp_rejects_a_signed_trivial_zero_statement() -> None:
    """A signer must not be able to turn the always-true zero relation into a proof."""
    from src.lattice_pq import LatticeSigner, LatticeZkReceipt

    public_key, private_key = LatticeSigner.generate_keypair()
    receipt = LatticeZkReceipt.create(b"bound payload", b"w" * 32, private_key)
    forged = receipt.to_dict()
    proof = copy.deepcopy(forged["proof"])
    proof["statement"] = base64.b64encode(b"\x00" * (64 * 4)).decode("ascii")
    proof["commitments"] = base64.b64encode(b"\x00" * (128 * 64 * 4)).decode("ascii")
    proof["responses"] = base64.b64encode(b"\x00" * (128 * 128 * 4)).decode("ascii")
    forged["proof"] = proof
    forged["message_hash"] = proof["message_hash"]
    unsigned = {key: forged[key] for key in (
        "version", "protocol", "signature_algorithm", "signer_id", "message_hash", "proof"
    )}
    forged["signature"] = base64.b64encode(
        LatticeSigner.sign(private_key, json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
    ).decode("ascii")

    assert not LatticeZkReceipt.from_dict(forged).verify(b"bound payload", public_key)


def t_lattice_zkp_sidecar_round_trip_preserves_the_video_commitment() -> None:
    from src.lattice_pq import (
        LatticeSigner,
        LatticeZkReceipt,
        pack_lattice_reference,
        unpack_lattice_reference,
    )

    public_key, private_key = LatticeSigner.generate_keypair()
    receipt = LatticeZkReceipt.create(b"payload", b"s" * 32, private_key)
    blob = pack_lattice_reference(b"payload", receipt.commitment())
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "proof.lattice-zkp.json"
        receipt.save(path)
        restored = LatticeZkReceipt.load(path)

    message, commitment = unpack_lattice_reference(blob)
    assert message == b"payload"
    assert commitment == restored.commitment()
    assert restored.verify(message, public_key)


def t_public_api_defaults_to_signed_lattice_attestation_and_manifest_v4() -> None:
    from src.embedder import embed
    from src.manifest import MANIFEST_VERSION, ProofMetadata
    from src.verifier import verify

    assert inspect.signature(embed).parameters["proof_backend"].default == "lattice"
    assert inspect.signature(verify).parameters["proof_backend"].default == "lattice"
    assert MANIFEST_VERSION == "4.0.0"
    assert ProofMetadata().proof_system == "ml-dsa-65-attestation"


def main() -> None:
    section("Transparent lattice ZKP")
    results = [
        run_test("lattice_zkp_receipt_verifies_a_short_witness_without_disclosing_it", t_lattice_zkp_receipt_verifies_a_short_witness_without_disclosing_it),
        run_test("lattice_zkp_rejects_message_transcript_and_signature_tampering", t_lattice_zkp_rejects_message_transcript_and_signature_tampering),
        run_test("lattice_zkp_rejects_a_signed_trivial_zero_statement", t_lattice_zkp_rejects_a_signed_trivial_zero_statement),
        run_test("lattice_zkp_sidecar_round_trip_preserves_the_video_commitment", t_lattice_zkp_sidecar_round_trip_preserves_the_video_commitment),
        run_test("public_api_defaults_to_signed_lattice_attestation_and_manifest_v4", t_public_api_defaults_to_signed_lattice_attestation_and_manifest_v4),
    ]
    raise SystemExit(summarise(results, "Transparent lattice ZKP"))


if __name__ == "__main__":
    main()
