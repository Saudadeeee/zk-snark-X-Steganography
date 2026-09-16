"""Contracts for the default transparent lattice-ZKP sidecar.

The proof is a Fiat-Shamir proof of knowledge for a short SIS witness.  The
test deliberately exercises independent verification and every binding:
payload, proof transcript, and ML-DSA authenticated sidecar.
"""

from __future__ import annotations

import copy
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
    tampered_proof["proof"]["responses"] = "A" + tampered_proof["proof"]["responses"][1:]
    assert not LatticeZkReceipt.from_dict(tampered_proof).verify(b"bound payload", public_key)

    tampered_signature = receipt.to_dict()
    tampered_signature["signature"] = "A" + tampered_signature["signature"][1:]
    assert not LatticeZkReceipt.from_dict(tampered_signature).verify(b"bound payload", public_key)


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


def main() -> None:
    section("Transparent lattice ZKP")
    results = [
        run_test("lattice_zkp_receipt_verifies_a_short_witness_without_disclosing_it", t_lattice_zkp_receipt_verifies_a_short_witness_without_disclosing_it),
        run_test("lattice_zkp_rejects_message_transcript_and_signature_tampering", t_lattice_zkp_rejects_message_transcript_and_signature_tampering),
        run_test("lattice_zkp_sidecar_round_trip_preserves_the_video_commitment", t_lattice_zkp_sidecar_round_trip_preserves_the_video_commitment),
    ]
    raise SystemExit(summarise(results, "Transparent lattice ZKP"))


if __name__ == "__main__":
    main()
