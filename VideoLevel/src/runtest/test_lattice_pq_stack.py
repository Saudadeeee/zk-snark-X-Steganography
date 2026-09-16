"""Contracts for the lattice-based cryptographic path.

The active lattice path deliberately keeps large ML-DSA attestations outside
the constrained H.264 payload and embeds only a fixed-size binding reference.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtest._helpers import run_test, section, summarise


def t_ml_dsa_receipt_round_trip_and_tamper_rejection() -> None:
    from src.lattice_pq import LatticeReceipt, LatticeSigner

    public_key, private_key = LatticeSigner.generate_keypair()
    receipt = LatticeReceipt.create(b"lattice video proof", private_key, signer_id="camera-01")

    assert receipt.verify(b"lattice video proof", public_key)
    assert not receipt.verify(b"tampered", public_key)
    assert receipt.signer_id == "camera-01"
    assert receipt.signature_algorithm == "ML-DSA-65"


def t_video_reference_binds_exact_signed_receipt() -> None:
    from src.lattice_pq import LatticeReceipt, LatticeSigner, pack_lattice_reference, unpack_lattice_reference

    public_key, private_key = LatticeSigner.generate_keypair()
    receipt = LatticeReceipt.create(b"payload", private_key)
    blob = pack_lattice_reference(b"payload", receipt.commitment())
    message, commitment = unpack_lattice_reference(blob)

    assert message == b"payload"
    assert commitment == receipt.commitment()
    assert receipt.verify(message, public_key)


def t_ml_kem_encapsulation_agrees_and_rejects_tampering() -> None:
    from src.lattice_pq import LatticeKem

    public_key, private_key = LatticeKem.generate_keypair()
    capsule, sender_secret = LatticeKem.encapsulate(public_key)
    assert LatticeKem.decapsulate(private_key, capsule) == sender_secret

    tampered = bytes([capsule[0] ^ 1]) + capsule[1:]
    assert LatticeKem.decapsulate(private_key, tampered) != sender_secret


def t_lattice_reference_is_small_enough_for_video_payload() -> None:
    from src.lattice_pq import LATTICE_REFERENCE_SIZE, pack_lattice_reference

    blob = pack_lattice_reference(b"x" * 13, b"x" * LATTICE_REFERENCE_SIZE)
    assert len(blob) == 3 + 4 + 13 + LATTICE_REFERENCE_SIZE


def main() -> None:
    section("Lattice PQ stack")
    results = [
        run_test("ml_dsa_receipt_round_trip_and_tamper_rejection", t_ml_dsa_receipt_round_trip_and_tamper_rejection),
        run_test("video_reference_binds_exact_signed_receipt", t_video_reference_binds_exact_signed_receipt),
        run_test("ml_kem_encapsulation_agrees_and_rejects_tampering", t_ml_kem_encapsulation_agrees_and_rejects_tampering),
        run_test("lattice_reference_is_small_enough_for_video_payload", t_lattice_reference_is_small_enough_for_video_payload),
    ]
    raise SystemExit(summarise(results, "Lattice PQ"))


if __name__ == "__main__":
    main()
