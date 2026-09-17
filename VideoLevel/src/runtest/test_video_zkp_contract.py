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
        payload_commitment_hex=payload_commitment(b"private payload"),
        cover_hash="01" * 32,
        stego_hash="02" * 32,
        positions_hash="03" * 32,
        policy={"codec": "h264-baseline-cavlc", "max_modifications_per_block": 1},
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
        build_video_zkp_statement(bytes(range(32)), payload_commitment(b"other"), "01" * 32, "02" * 32, "03" * 32, {"codec": "h264-baseline-cavlc", "max_modifications_per_block": 1}),
        build_video_zkp_statement(bytes(range(32)), reference.payload_commitment, "04" * 32, "02" * 32, "03" * 32, {"codec": "h264-baseline-cavlc", "max_modifications_per_block": 1}),
        build_video_zkp_statement(bytes(range(32)), reference.payload_commitment, "01" * 32, "05" * 32, "03" * 32, {"codec": "h264-baseline-cavlc", "max_modifications_per_block": 1}),
        build_video_zkp_statement(bytes(range(32)), reference.payload_commitment, "01" * 32, "02" * 32, "06" * 32, {"codec": "h264-baseline-cavlc", "max_modifications_per_block": 1}),
        build_video_zkp_statement(bytes(range(32)), reference.payload_commitment, "01" * 32, "02" * 32, "03" * 32, {"codec": "h264-baseline-cavlc", "max_modifications_per_block": 2}),
    ]

    assert all(variant.statement_id != reference.statement_id for variant in variants)


def t_statement_rejects_ambiguous_or_wrongly_sized_inputs() -> None:
    from src.video_zkp_contract import build_video_zkp_statement

    try:
        build_video_zkp_statement(b"short", "00" * 32, "01" * 32, "02" * 32, "03" * 32, {})
    except ValueError:
        pass
    else:
        raise AssertionError("short session id accepted")

    try:
        build_video_zkp_statement(bytes(range(32)), "00" * 31, "01" * 32, "02" * 32, "03" * 32, {})
    except ValueError:
        pass
    else:
        raise AssertionError("short digest accepted")


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
        run_test("manifest_preserves_a_future_zkp_statement_identifier", t_manifest_preserves_a_future_zkp_statement_identifier),
    ]
    raise SystemExit(summarise(results, "PQ video ZKP statement contract"))


if __name__ == "__main__":
    main()
