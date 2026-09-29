"""Contracts for a disabled, research-only SIS proof prototype receipt.

These tests exercise prototype proof serialization and tamper rejection only.
They do not establish a reviewed application ZKP or the public video-only
proof path; the active public API uses ML-DSA attestation instead.
"""

from __future__ import annotations

import base64
import copy
import inspect
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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


def t_sis_prototype_accepts_a_prover_selected_statement() -> None:
    """Characterize why this proof cannot attest an externally fixed claim."""
    from src.lattice_pq import LatticeZkProof

    message = b"same public message, no verifier-pinned statement"
    first = LatticeZkProof.create(message, b"A" * 32)
    second = LatticeZkProof.create(message, b"B" * 32)

    assert first.verify(message)
    assert second.verify(message)
    assert first.message_hash == second.message_hash
    assert first.statement != second.statement


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


def t_public_apis_fail_closed_for_unreviewed_lattice_zkp() -> None:
    """The experimental proof must stay unavailable to the public video API."""
    from src.embedder import embed
    from src.verifier import verify

    with tempfile.TemporaryDirectory() as directory:
        cover = Path(directory) / "cover.h264"
        stego = Path(directory) / "stego.h264"
        cover.write_bytes(b"not parsed: backend gate must fail first")
        stego.write_bytes(b"not parsed: backend gate must fail first")

        try:
            embed(
                str(cover), b"payload", str(Path(directory) / "out.h264"), "",
                b"k" * 32, proof_backend="lattice_zkp",
            )
        except ValueError as error:
            assert "lattice_zkp is experimental and disabled" in str(error)
        else:
            raise AssertionError("embed unexpectedly enabled the research ZKP")

        try:
            verify(
                str(stego), str(cover), "", b"k" * 32, 7,
                proof_backend="lattice_zkp",
            )
        except ValueError as error:
            assert "lattice_zkp is experimental and disabled" in str(error)
        else:
            raise AssertionError("verify unexpectedly enabled the research ZKP")


def t_future_zkp_statement_requires_verifier_session_challenge() -> None:
    from src.embedder import embed

    with tempfile.TemporaryDirectory() as directory:
        cover = Path(directory) / "cover.h264"
        cover.write_bytes(b"fixture; challenge validation must precede video parsing")
        common = {
            "video_path": str(cover),
            "message": b"payload",
            "output_path": str(Path(directory) / "out.h264"),
            "circuits_dir": "",
            "secret_key": b"s" * 32,
            "lattice_private_key": b"k" * 32,
            "zkp_relation_id": "11" * 32,
            "zkp_relation_registry": object(),
            "zkp_registry_issuer_public_key": b"issuer-key",
            "zkp_payload_opening": b"o" * 32,
        }

        try:
            embed(**common)
        except ValueError as error:
            assert "all future-ZKP" in str(error)
            assert "session challenge" in str(error)
        else:
            raise AssertionError("future-ZKP statement accepted without verifier challenge")

        try:
            embed(**common, zkp_session_id=b"x" * 31)
        except ValueError as error:
            assert "zkp_session_id must be exactly 32 bytes" in str(error)
        else:
            raise AssertionError("future-ZKP statement accepted a malformed session challenge")


def t_blind_verifier_rejects_research_proof_before_parsing_video() -> None:
    """Reject authenticated research artifacts before expensive H.264 analysis."""
    from src.verifier_blind import verify_near_blind

    manifest = SimpleNamespace(
        signature_algorithm="ml-dsa-65",
        verify_signature=lambda _key: True,
        video=SimpleNamespace(stego_file_hash="fixture-video-hash"),
        embedding=SimpleNamespace(
            positions_count=1,
            positions_hash="fixture-positions-hash",
            strategy="t1_sign_flip",
            max_modifications_per_block=1,
        ),
        payload=SimpleNamespace(message_length=1, chaos_enabled=False, bits_required=8),
        proof=SimpleNamespace(proof_system="sis-linear-fiat-shamir-v1"),
    )

    with tempfile.TemporaryDirectory() as directory:
        stego = Path(directory) / "stego.h264"
        stego.write_bytes(b"not parsed: signed manifest selects disabled research proof")
        with (
            patch(
                "src.verifier_blind.analyze_stream_profile",
                return_value=SimpleNamespace(supported=True),
            ),
            patch(
                "src.verifier_blind._load_sidecar_data",
                return_value=([(0, 0, 0)], 8, manifest),
            ),
            patch("src.verifier_blind.compute_file_hash", return_value="fixture-video-hash"),
            patch("src.verifier_blind.hash_positions", return_value="fixture-positions-hash"),
            patch(
                "src.verifier_blind.H264BitstreamParser",
                side_effect=AssertionError("H.264 parser ran before proof-system rejection"),
            ),
        ):
            try:
                verify_near_blind(
                    str(stego), "", b"", 1, b"k" * 1952,
                )
            except RuntimeError as error:
                assert "experimental lattice_zkp artifacts are disabled" in str(error)
            else:
                raise AssertionError("blind verifier accepted a research-only proof artifact")


def main() -> None:
    section("Research-only SIS proof prototype (not an accepted backend)")
    results = [
        run_test("lattice_zkp_receipt_verifies_a_short_witness_without_disclosing_it", t_lattice_zkp_receipt_verifies_a_short_witness_without_disclosing_it),
        run_test("sis_prototype_accepts_a_prover_selected_statement", t_sis_prototype_accepts_a_prover_selected_statement),
        run_test("lattice_zkp_rejects_message_transcript_and_signature_tampering", t_lattice_zkp_rejects_message_transcript_and_signature_tampering),
        run_test("lattice_zkp_rejects_a_signed_trivial_zero_statement", t_lattice_zkp_rejects_a_signed_trivial_zero_statement),
        run_test("lattice_zkp_sidecar_round_trip_preserves_the_video_commitment", t_lattice_zkp_sidecar_round_trip_preserves_the_video_commitment),
        run_test("public_api_defaults_to_signed_lattice_attestation_and_manifest_v4", t_public_api_defaults_to_signed_lattice_attestation_and_manifest_v4),
        run_test("public_apis_fail_closed_for_unreviewed_lattice_zkp", t_public_apis_fail_closed_for_unreviewed_lattice_zkp),
        run_test("future_zkp_statement_requires_verifier_session_challenge", t_future_zkp_statement_requires_verifier_session_challenge),
        run_test("blind_verifier_rejects_research_proof_before_parsing_video", t_blind_verifier_rejects_research_proof_before_parsing_video),
    ]
    raise SystemExit(summarise(results, "Research-only SIS proof prototype"))


if __name__ == "__main__":
    main()
