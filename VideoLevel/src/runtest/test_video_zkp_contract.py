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
    from src.video_zkp_contract import VIDEO_ZKP_HASH_ALGORITHMS

    statement = _statement()

    assert statement.protocol == "zkstego-pq-video-statement-v2"
    assert VIDEO_ZKP_HASH_ALGORITHMS["stego_hash"] == "sha256(canonical-h264-carrier-normalization-v1)"
    assert len(statement.statement_id) == 64
    assert statement.to_public_bytes() == statement.to_public_bytes()


def t_video_commitment_is_recomputed_from_video_and_carrier_positions() -> None:
    from unittest.mock import patch

    from src.video_zkp_contract import verify_video_zkp_video_commitment

    statement = _statement()
    positions = [(4, 8, -1), (9, 2, 3)]
    with patch("src.video_canonicalization.canonical_video_sha256", return_value=statement.stego_hash) as digest:
        assert verify_video_zkp_video_commitment(statement, "stego.h264", positions)
        digest.assert_called_once_with("stego.h264", positions)
    with patch("src.video_canonicalization.canonical_video_sha256", return_value="ff" * 32):
        assert not verify_video_zkp_video_commitment(statement, "stego.h264", positions)


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

    try:
        build_video_zkp_statement(bytes(range(32)), "00 " * 20 + "0000", "01" * 32, "02" * 32, "03" * 32, "04" * 32, "05" * 32, 0, {"codec": "h264-baseline-cavlc", "embedding_strategy": "t1_sign_flip", "max_modifications_per_block": 1, "proof_backend": "lattice"})
    except ValueError:
        pass
    else:
        raise AssertionError("non-canonical hexadecimal digest accepted")


def t_payload_commitment_is_opening_bound_and_statement_parser_rejects_tampering() -> None:
    from src.video_zkp_contract import VideoZkpStatement, payload_commitment

    assert payload_commitment(b"short", b"a" * 32) != payload_commitment(b"short", b"b" * 32)
    encoded = _statement().to_dict()
    assert VideoZkpStatement.from_dict(encoded).statement_id == encoded["statement_id"]
    encoded["session_id"] = "00 " * 20 + "0000"
    try:
        VideoZkpStatement.from_dict(encoded)
    except ValueError:
        pass
    else:
        raise AssertionError("non-canonical session id accepted")
    encoded = _statement().to_dict()
    encoded["statement_id"] = "00" * 32
    try:
        VideoZkpStatement.from_dict(encoded)
    except ValueError:
        pass
    else:
        raise AssertionError("tampered statement id accepted")


def t_payload_commitment_matches_python_golden_vector_and_statement_omits_opening() -> None:
    import base64

    from src.video_zkp_contract import build_video_zkp_statement, payload_commitment

    payload = b"payload-circuit-golden-v1"
    opening = bytes(range(32))
    commitment = payload_commitment(payload, opening)
    # Python hashlib reference vector; no independent ZK-circuit fixture exists yet.
    assert commitment == "92b61e5dffae4f59a1f08232d0f8e1baf7ea10dc749f007e14889209fa57bfca"

    statement = build_video_zkp_statement(
        session_id=bytes(range(32, 64)),
        payload_commitment_hex=commitment,
        cover_hash="01" * 32,
        stego_hash="02" * 32,
        positions_hash="03" * 32,
        relation_id="04" * 32,
        registry_root="05" * 32,
        registry_epoch=7,
        policy={
            "codec": "h264-baseline-cavlc",
            "embedding_strategy": "t1_sign_flip",
            "max_modifications_per_block": 1,
            "proof_backend": "lattice",
        },
    )
    public_fields = statement.to_dict()
    assert "payload" not in public_fields
    assert "opening" not in public_fields
    public_bytes = statement.to_public_bytes()
    for secret_encoding in (
        payload.decode("ascii"),
        payload.hex(),
        base64.b64encode(payload).decode("ascii"),
        opening.hex(),
        base64.b64encode(opening).decode("ascii"),
    ):
        assert secret_encoding not in public_bytes.decode("ascii")


def t_manifest_preserves_a_future_zkp_statement_identifier() -> None:
    from src.manifest import ProofMetadata, StegoManifest

    statement_id = _statement().statement_id
    restored = StegoManifest.from_json(
        StegoManifest(proof=ProofMetadata(statement_id=statement_id)).to_json()
    )

    assert restored.proof.statement_id == statement_id


def t_carrier_policy_hash_versions_metadata_schema() -> None:
    from src.blind_sync import BlindOperatingContract
    from src.video_zkp_contract import carrier_policy_hash

    contract = BlindOperatingContract(
        version="stable-carriers-video-only-v1",
        signbit_only=True,
        require_bitstream_patchable=True,
        max_modifications_per_block=1,
        stable_carriers_only=True,
    )
    legacy_policy_hash = "9940ab80be24bfaacbc4d691ab11954a9a52fdf80215694eb86841d4c7b2d080"

    assert carrier_policy_hash(contract, 2) != legacy_policy_hash


def t_statement_registry_binding_uses_verifier_pins_and_rejects_mutations() -> None:
    from src.lattice_pq import LatticeSigner
    from src.video_zkp_contract import (
        build_video_zkp_statement,
        payload_commitment,
        policy_hash,
        verify_video_zkp_statement_binding,
    )
    from src.zkp_registry import SignedZkpRelationRegistry

    policy = {
        "codec": "h264-baseline-cavlc",
        "embedding_strategy": "t1_sign_flip",
        "max_modifications_per_block": 1,
        "proof_backend": "lazer",
    }
    descriptor = {
        "zkp_suite": "lazer-v1",
        "constraint_module_hash": "11" * 32,
        "verifier_key_hash": "22" * 32,
        "parameter_set_hash": "33" * 32,
        "policy_hash": policy_hash(policy),
    }
    issuer_public_key, issuer_private_key = LatticeSigner.generate_keypair()
    registry = SignedZkpRelationRegistry.create(epoch=12, relations=[descriptor]).sign(
        issuer_private_key, signer_id="issuer-v1"
    )
    relation_id = registry.relations[0].relation_id
    statement = build_video_zkp_statement(
        session_id=bytes(range(32)),
        payload_commitment_hex=payload_commitment(b"payload", b"o" * 32),
        cover_hash="41" * 32,
        stego_hash="42" * 32,
        positions_hash="43" * 32,
        relation_id=relation_id,
        registry_root=registry.root(),
        registry_epoch=registry.epoch,
        policy=policy,
    )

    assert verify_video_zkp_statement_binding(
        statement,
        registry,
        issuer_public_key,
        expected_relation_id=relation_id,
        expected_policy_hash=descriptor["policy_hash"],
        minimum_epoch=10,
    ) == (registry.root(), registry.epoch)

    invalid_cases = [
        {
            "statement": build_video_zkp_statement(
                bytes(range(32)), statement.payload_commitment, "41" * 32, "42" * 32,
                "43" * 32, "ff" * 32, registry.root(), registry.epoch, policy,
            ),
            "expected_relation_id": relation_id,
            "expected_policy_hash": descriptor["policy_hash"],
        },
        {
            "statement": build_video_zkp_statement(
                bytes(range(32)), statement.payload_commitment, "41" * 32, "42" * 32,
                "43" * 32, relation_id, "ff" * 32, registry.epoch, policy,
            ),
            "expected_relation_id": relation_id,
            "expected_policy_hash": descriptor["policy_hash"],
        },
        {
            "statement": statement,
            "expected_relation_id": relation_id,
            "expected_policy_hash": "ee" * 32,
        },
    ]
    for case in invalid_cases:
        try:
            verify_video_zkp_statement_binding(
                case["statement"],
                registry,
                issuer_public_key,
                expected_relation_id=case["expected_relation_id"],
                expected_policy_hash=case["expected_policy_hash"],
                minimum_epoch=10,
            )
        except ValueError:
            continue
        raise AssertionError("statement binding accepted an unpinned relation, root, or policy")


def t_context_binding_composes_pins_carrier_hash_and_video_commitment() -> None:
    import hashlib
    from dataclasses import replace
    from unittest.mock import patch

    from src.blind_sync import BlindOperatingContract
    from src.lattice_pq import LatticeSigner
    from src.manifest import hash_positions
    from src.video_zkp_contract import (
        build_video_zkp_statement,
        carrier_policy_hash,
        payload_commitment,
        policy_hash,
        verify_video_zkp_context_binding,
        verify_video_zkp_context_binding_video_only,
    )
    from src.zkp_registry import SignedZkpRelationRegistry

    positions = [(1, 2, -1), (5, 3, -4)]
    carrier_contract = BlindOperatingContract(
        version="stable-carriers-video-only-v1",
        signbit_only=True,
        require_bitstream_patchable=True,
        max_modifications_per_block=1,
        stable_carriers_only=True,
    )
    policy = {
        "codec": "h264-baseline-cavlc",
        "embedding_strategy": "t1_sign_flip",
        "max_modifications_per_block": 1,
        "proof_backend": "lazer",
        "carrier_profile_hash": carrier_policy_hash(carrier_contract, len(positions)),
    }
    descriptor = {
        "zkp_suite": "lazer-v1",
        "constraint_module_hash": "11" * 32,
        "verifier_key_hash": "22" * 32,
        "parameter_set_hash": "33" * 32,
        "policy_hash": policy_hash(policy),
    }
    issuer_public_key, issuer_private_key = LatticeSigner.generate_keypair()
    registry = SignedZkpRelationRegistry.create(epoch=12, relations=[descriptor]).sign(
        issuer_private_key, signer_id="issuer-v1"
    )
    relation_id = registry.relations[0].relation_id
    statement = build_video_zkp_statement(
        session_id=bytes(range(32)),
        payload_commitment_hex=payload_commitment(b"payload", b"o" * 32),
        cover_hash="41" * 32,
        stego_hash="42" * 32,
        positions_hash=hash_positions(positions),
        relation_id=relation_id,
        registry_root=registry.root(),
        registry_epoch=registry.epoch,
        policy=policy,
    )

    with patch(
        "src.video_canonicalization.canonical_video_sha256",
        return_value=statement.stego_hash,
    ) as video_hash:
        assert verify_video_zkp_context_binding(
            statement.to_dict(),
            registry,
            issuer_public_key,
            video_path="fixture.h264",
            carrier_positions=positions,
            expected_relation_id=relation_id,
            expected_policy_hash=descriptor["policy_hash"],
            minimum_epoch=10,
        ) == (registry.root(), registry.epoch)
        video_hash.assert_called_once_with("fixture.h264", positions)

        with patch(
            "src.blind_sync.derive_blind_positions_operating_contract",
            return_value=(positions, object()),
        ) as derive_positions:
            try:
                verify_video_zkp_context_binding_video_only(
                    statement.to_dict(),
                    registry,
                    issuer_public_key,
                    video_path="fixture.h264",
                    expected_session_id=bytes(range(32)),
                    required_bits=len(positions),
                    carrier_contract=carrier_contract,
                    expected_relation_id=relation_id,
                    expected_policy_hash="ff" * 32,
                    minimum_epoch=10,
                )
            except ValueError as error:
                assert "policy" in str(error)
            else:
                raise AssertionError("video analysis started for an untrusted policy")
            derive_positions.assert_not_called()

            assert verify_video_zkp_context_binding_video_only(
                statement.to_dict(),
                registry,
                issuer_public_key,
                video_path="fixture.h264",
                expected_session_id=bytes(range(32)),
                required_bits=len(positions),
                carrier_contract=carrier_contract,
                expected_relation_id=relation_id,
                expected_policy_hash=descriptor["policy_hash"],
                minimum_epoch=10,
            ) == (registry.root(), registry.epoch)
            derive_positions.assert_called_once_with(
                "fixture.h264",
                hashlib.sha256(
                    b"zkstego/pq-video/carrier-order-seed/v1\x00"
                    + bytes(range(32))
                ).digest(),
                len(positions),
                carrier_contract,
                cif_mb_count=396,
            )

            # A proof statement that claims t1_sign_flip must not be accepted
            # under a verifier profile that derives magnitude-LSB carriers.
            magnitude_contract = replace(carrier_contract, signbit_only=False)
            magnitude_policy = {
                **policy,
                "carrier_profile_hash": carrier_policy_hash(
                    magnitude_contract, len(positions)
                ),
            }
            magnitude_descriptor = {
                **descriptor,
                "policy_hash": policy_hash(magnitude_policy),
            }
            magnitude_registry = SignedZkpRelationRegistry.create(
                epoch=12, relations=[magnitude_descriptor]
            ).sign(issuer_private_key, signer_id="issuer-v1")
            magnitude_statement = build_video_zkp_statement(
                session_id=bytes(range(32)),
                payload_commitment_hex=payload_commitment(b"payload", b"o" * 32),
                cover_hash="41" * 32,
                stego_hash="42" * 32,
                positions_hash=hash_positions(positions),
                relation_id=magnitude_registry.relations[0].relation_id,
                registry_root=magnitude_registry.root(),
                registry_epoch=magnitude_registry.epoch,
                policy=magnitude_policy,
            )
            derive_positions.reset_mock()
            try:
                verify_video_zkp_context_binding_video_only(
                    magnitude_statement.to_dict(),
                    magnitude_registry,
                    issuer_public_key,
                    video_path="fixture.h264",
                    expected_session_id=bytes(range(32)),
                    required_bits=len(positions),
                    carrier_contract=magnitude_contract,
                    expected_relation_id=magnitude_registry.relations[0].relation_id,
                    expected_policy_hash=magnitude_descriptor["policy_hash"],
                    minimum_epoch=10,
                )
            except ValueError as error:
                assert "sign" in str(error).lower()
            else:
                raise AssertionError(
                    "t1_sign_flip accepted a magnitude-LSB carrier profile"
                )
            derive_positions.assert_not_called()

            contract_mutations = (
                {"version": "changed-profile-v2"},
                {"signbit_only": False},
                {"bottom_rows": 1},
                {"dedup_per_block": False},
                {"max_bits_per_idr": 1},
                {"metadata_bound": True},
                {"require_bitstream_patchable": False},
                {"patchability_headroom": 65},
                {"max_modifications_per_block": 2},
                {"stable_carriers_only": False},
            )
            for mutation in contract_mutations:
                derive_positions.reset_mock()
                try:
                    verify_video_zkp_context_binding_video_only(
                        statement.to_dict(),
                        registry,
                        issuer_public_key,
                        video_path="fixture.h264",
                        expected_session_id=bytes(range(32)),
                        required_bits=len(positions),
                        carrier_contract=replace(carrier_contract, **mutation),
                        expected_relation_id=relation_id,
                        expected_policy_hash=descriptor["policy_hash"],
                        minimum_epoch=10,
                    )
                except ValueError:
                    pass
                else:
                    raise AssertionError(f"accepted mutated carrier contract: {mutation}")
                derive_positions.assert_not_called()

            derive_positions.reset_mock()
            try:
                verify_video_zkp_context_binding_video_only(
                    statement.to_dict(),
                    registry,
                    issuer_public_key,
                    video_path="fixture.h264",
                    expected_session_id=b"x" * 32,
                    required_bits=len(positions),
                    carrier_contract=carrier_contract,
                    expected_relation_id=relation_id,
                    expected_policy_hash=descriptor["policy_hash"],
                    minimum_epoch=10,
                )
            except ValueError as error:
                assert "session id" in str(error)
            else:
                raise AssertionError("accepted a statement outside the verifier session")
            derive_positions.assert_not_called()

            derive_positions.reset_mock()
            try:
                verify_video_zkp_context_binding_video_only(
                    statement.to_dict(),
                    registry,
                    issuer_public_key,
                    video_path="fixture.h264",
                    expected_session_id=bytes(range(32)),
                    required_bits=len(positions) + 1,
                    carrier_contract=carrier_contract,
                    expected_relation_id=relation_id,
                    expected_policy_hash=descriptor["policy_hash"],
                    minimum_epoch=10,
                )
            except ValueError as error:
                assert "profile hash" in str(error)
            else:
                raise AssertionError("accepted a carrier count outside the pinned profile")
            derive_positions.assert_not_called()

            video_hash.reset_mock()
            derive_positions.reset_mock()
            derive_positions.return_value = (positions[:-1], object())
            try:
                verify_video_zkp_context_binding_video_only(
                    statement.to_dict(),
                    registry,
                    issuer_public_key,
                    video_path="fixture.h264",
                    expected_session_id=bytes(range(32)),
                    required_bits=len(positions),
                    carrier_contract=carrier_contract,
                    expected_relation_id=relation_id,
                    expected_policy_hash=descriptor["policy_hash"],
                    minimum_epoch=10,
                )
            except ValueError as error:
                assert "capacity is insufficient" in str(error)
            else:
                raise AssertionError("video-only context accepted insufficient carrier capacity")
            video_hash.assert_not_called()

        video_hash.reset_mock()
        try:
            verify_video_zkp_context_binding(
                statement.to_dict(),
                registry,
                issuer_public_key,
                video_path="fixture.h264",
                carrier_positions=positions + [(9, 9, 1)],
                expected_relation_id=relation_id,
                expected_policy_hash=descriptor["policy_hash"],
                minimum_epoch=10,
            )
        except ValueError as error:
            assert "positions hash" in str(error)
        else:
            raise AssertionError("context binding accepted carrier positions outside the statement")
        video_hash.assert_not_called()

        video_hash.return_value = "ff" * 32
        try:
            verify_video_zkp_context_binding(
                statement.to_dict(),
                registry,
                issuer_public_key,
                video_path="fixture.h264",
                carrier_positions=positions,
                expected_relation_id=relation_id,
                expected_policy_hash=descriptor["policy_hash"],
                minimum_epoch=10,
            )
        except ValueError as error:
            assert "video commitment" in str(error)
        else:
            raise AssertionError("context binding accepted a mismatching video digest")

        try:
            verify_video_zkp_context_binding(
                statement.to_dict(),
                registry,
                issuer_public_key,
                video_path="fixture.h264",
                carrier_positions=iter(positions),
                expected_relation_id=relation_id,
                expected_policy_hash=descriptor["policy_hash"],
                minimum_epoch=10,
            )
        except TypeError as error:
            assert "finite sequence" in str(error)
        else:
            raise AssertionError("context binding accepted a one-shot carrier iterator")


def main() -> None:
    section("PQ video ZKP statement contract")
    results = [
        run_test("statement_is_canonical_and_binds_every_video_artifact", t_statement_is_canonical_and_binds_every_video_artifact),
        run_test("video_commitment_is_recomputed_from_video_and_carrier_positions", t_video_commitment_is_recomputed_from_video_and_carrier_positions),
        run_test("statement_id_changes_for_payload_video_positions_or_policy", t_statement_id_changes_for_payload_video_positions_or_policy),
        run_test("statement_rejects_ambiguous_or_wrongly_sized_inputs", t_statement_rejects_ambiguous_or_wrongly_sized_inputs),
        run_test("payload_commitment_is_opening_bound_and_statement_parser_rejects_tampering", t_payload_commitment_is_opening_bound_and_statement_parser_rejects_tampering),
        run_test(
            "payload_commitment_matches_python_golden_vector_and_statement_omits_opening",
            t_payload_commitment_matches_python_golden_vector_and_statement_omits_opening,
        ),
        run_test("manifest_preserves_a_future_zkp_statement_identifier", t_manifest_preserves_a_future_zkp_statement_identifier),
        run_test("carrier_policy_hash_versions_metadata_schema", t_carrier_policy_hash_versions_metadata_schema),
        run_test("statement_registry_binding_uses_verifier_pins_and_rejects_mutations", t_statement_registry_binding_uses_verifier_pins_and_rejects_mutations),
        run_test("context_binding_composes_pins_carrier_hash_and_video_commitment", t_context_binding_composes_pins_carrier_hash_and_video_commitment),
    ]
    raise SystemExit(summarise(results, "PQ video ZKP statement contract"))


if __name__ == "__main__":
    main()
