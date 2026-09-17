"""Contracts for the future reviewed post-quantum video-ZKP statement."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtest._helpers import run_test, section, summarise


def _statement() -> object:
    from src.video_zkp_contract import build_video_zkp_statement, payload_commitment

    return build_video_zkp_statement(
        session_id=bytes(range(32)),
        payload_commitment_hex=payload_commitment(b"private payload", b"o" * 32),
        cover_hash="01" * 32,
        stego_hash="02" * 32,
        positions_hash="03" * 32,
        relation_id="04" * 32,
        registry_root="05" * 32,
        registry_epoch=7,
        policy={"codec": "h264-baseline-cavlc", "embedding_strategy": "t1_sign_flip", "max_modifications_per_block": 1, "proof_backend": "lattice"},
    )


def t_statement_is_canonical_and_binds_every_video_artifact() -> None:
    statement = _statement()

    assert statement.protocol == "zkstego-pq-video-statement-v1"
    assert len(statement.statement_id) == 64
    assert statement.to_public_bytes() == statement.to_public_bytes()


def t_statement_id_changes_for_payload_video_positions_or_policy() -> None:
    from src.video_zkp_contract import build_video_zkp_statement, payload_commitment

    reference = _statement()
    variants = [
        build_video_zkp_statement(bytes(range(32)), payload_commitment(b"other", b"o" * 32), "01" * 32, "02" * 32, "03" * 32, "04" * 32, "05" * 32, 7, {"codec": "h264-baseline-cavlc", "embedding_strategy": "t1_sign_flip", "max_modifications_per_block": 1, "proof_backend": "lattice"}),
        build_video_zkp_statement(bytes(range(32)), reference.payload_commitment, "06" * 32, "02" * 32, "03" * 32, "04" * 32, "05" * 32, 7, {"codec": "h264-baseline-cavlc", "embedding_strategy": "t1_sign_flip", "max_modifications_per_block": 1, "proof_backend": "lattice"}),
        build_video_zkp_statement(bytes(range(32)), reference.payload_commitment, "01" * 32, "07" * 32, "03" * 32, "04" * 32, "05" * 32, 7, {"codec": "h264-baseline-cavlc", "embedding_strategy": "t1_sign_flip", "max_modifications_per_block": 1, "proof_backend": "lattice"}),
        build_video_zkp_statement(bytes(range(32)), reference.payload_commitment, "01" * 32, "02" * 32, "08" * 32, "04" * 32, "05" * 32, 7, {"codec": "h264-baseline-cavlc", "embedding_strategy": "t1_sign_flip", "max_modifications_per_block": 1, "proof_backend": "lattice"}),
        build_video_zkp_statement(bytes(range(32)), reference.payload_commitment, "01" * 32, "02" * 32, "03" * 32, "09" * 32, "05" * 32, 7, {"codec": "h264-baseline-cavlc", "embedding_strategy": "t1_sign_flip", "max_modifications_per_block": 1, "proof_backend": "lattice"}),
        build_video_zkp_statement(bytes(range(32)), reference.payload_commitment, "01" * 32, "02" * 32, "03" * 32, "04" * 32, "0a" * 32, 7, {"codec": "h264-baseline-cavlc", "embedding_strategy": "t1_sign_flip", "max_modifications_per_block": 1, "proof_backend": "lattice"}),
        build_video_zkp_statement(bytes(range(32)), reference.payload_commitment, "01" * 32, "02" * 32, "03" * 32, "04" * 32, "05" * 32, 8, {"codec": "h264-baseline-cavlc", "embedding_strategy": "t1_sign_flip", "max_modifications_per_block": 1, "proof_backend": "lattice"}),
        build_video_zkp_statement(bytes(range(32)), reference.payload_commitment, "01" * 32, "02" * 32, "03" * 32, "04" * 32, "05" * 32, 7, {"codec": "h264-baseline-cavlc", "embedding_strategy": "t1_sign_flip", "max_modifications_per_block": 2, "proof_backend": "lattice"}),
    ]

    assert all(variant.statement_id != reference.statement_id for variant in variants)


def t_statement_rejects_ambiguous_or_wrongly_sized_inputs() -> None:
    from src.video_zkp_contract import build_video_zkp_statement

    try:
        build_video_zkp_statement(b"short", "00" * 32, "01" * 32, "02" * 32, "03" * 32, "04" * 32, "05" * 32, 0, {})
    except ValueError:
        pass
    else:
        raise AssertionError("short session id accepted")

    try:
        build_video_zkp_statement(bytes(range(32)), "00" * 31, "01" * 32, "02" * 32, "03" * 32, "04" * 32, "05" * 32, 0, {})
    except ValueError:
        pass
    else:
        raise AssertionError("short digest accepted")


def t_payload_commitment_is_opening_bound_and_statement_parser_rejects_tampering() -> None:
    from src.video_zkp_contract import VideoZkpStatement, payload_commitment

    assert payload_commitment(b"short", b"a" * 32) != payload_commitment(b"short", b"b" * 32)
    encoded = _statement().to_dict()
    assert VideoZkpStatement.from_dict(encoded).statement_id == encoded["statement_id"]
    encoded["statement_id"] = "00" * 32
    try:
        VideoZkpStatement.from_dict(encoded)
    except ValueError:
        pass
    else:
        raise AssertionError("tampered statement id accepted")


def t_manifest_preserves_a_future_zkp_statement_identifier() -> None:
    from src.manifest import ProofMetadata, StegoManifest

    statement_id = _statement().statement_id
    restored = StegoManifest.from_json(
        StegoManifest(proof=ProofMetadata(statement_id=statement_id)).to_json()
    )

    assert restored.proof.statement_id == statement_id


def main() -> None:
    section("PQ video ZKP statement contract")
    results = [
        run_test("statement_is_canonical_and_binds_every_video_artifact", t_statement_is_canonical_and_binds_every_video_artifact),
        run_test("statement_id_changes_for_payload_video_positions_or_policy", t_statement_id_changes_for_payload_video_positions_or_policy),
        run_test("statement_rejects_ambiguous_or_wrongly_sized_inputs", t_statement_rejects_ambiguous_or_wrongly_sized_inputs),
        run_test("payload_commitment_is_opening_bound_and_statement_parser_rejects_tampering", t_payload_commitment_is_opening_bound_and_statement_parser_rejects_tampering),
        run_test("manifest_preserves_a_future_zkp_statement_identifier", t_manifest_preserves_a_future_zkp_statement_identifier),
    ]
    raise SystemExit(summarise(results, "PQ video ZKP statement contract"))


if __name__ == "__main__":
    main()
