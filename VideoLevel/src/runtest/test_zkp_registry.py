"""Contracts for the signed relation registry that gates future ZKP statements."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtest._helpers import run_test, section, summarise


def _relation_descriptor() -> dict[str, str]:
    from src.video_zkp_contract import policy_hash

    return {
        "zkp_suite": "lazer-v1",
        "constraint_module_hash": "01" * 32,
        "verifier_key_hash": "02" * 32,
        "parameter_set_hash": "03" * 32,
        "policy_hash": policy_hash({"codec": "h264-baseline-cavlc", "embedding_strategy": "t1_sign_flip", "max_modifications_per_block": 1, "proof_backend": "lazer"}),
    }


def _issuer_keys() -> tuple[bytes, bytes]:
    from src.lattice_pq import LatticeSigner

    return LatticeSigner.generate_keypair()


def t_signed_registry_resolves_only_a_registered_lazer_relation() -> None:
    from src.zkp_registry import SignedZkpRelationRegistry

    public_key, private_key = _issuer_keys()
    registry = SignedZkpRelationRegistry.create(epoch=4, relations=[_relation_descriptor()]).sign(private_key, signer_id="issuer-v1")
    restored = SignedZkpRelationRegistry.from_dict(registry.to_dict())

    assert restored.verify(public_key)
    assert restored.resolve(registry.relations[0].relation_id, "lazer-v1", registry.relations[0].policy_hash) == (restored.root(), 4)
    try:
        restored.resolve(registry.relations[0].relation_id, "lazer-v1", "ff" * 32)
    except ValueError:
        pass
    else:
        raise AssertionError("relation accepted a policy not registered by its descriptor")


def t_registry_rejects_tampering_unknown_relation_or_wrong_issuer() -> None:
    from src.zkp_registry import SignedZkpRelationRegistry

    public_key, private_key = _issuer_keys()
    registry = SignedZkpRelationRegistry.create(epoch=4, relations=[_relation_descriptor()]).sign(private_key, signer_id="issuer-v1")
    encoded = registry.to_dict()
    encoded["epoch"] = 5
    tampered = SignedZkpRelationRegistry.from_dict(encoded)

    assert not tampered.verify(public_key)
    try:
        registry.resolve("02" * 32, "lazer-v1", registry.relations[0].policy_hash)
    except ValueError:
        pass
    else:
        raise AssertionError("unknown relation accepted")
    encoded = registry.to_dict()
    encoded["signer_id"] = "retagged-issuer"
    assert not SignedZkpRelationRegistry.from_dict(encoded).verify(public_key)


def t_verifier_binding_requires_its_pinned_relation_and_signed_snapshot() -> None:
    from src.zkp_registry import SignedZkpRelationRegistry

    public_key, private_key = _issuer_keys()
    registry = SignedZkpRelationRegistry.create(
        epoch=9, relations=[_relation_descriptor()]
    ).sign(private_key, signer_id="issuer-v1")
    relation_id = registry.relations[0].relation_id
    policy_digest = registry.relations[0].policy_hash
    statement_binding = {
        "statement_relation_id": relation_id,
        "expected_relation_id": relation_id,
        "statement_policy_hash": policy_digest,
        "expected_policy_hash": policy_digest,
        "statement_registry_root": registry.root(),
        "statement_registry_epoch": registry.epoch,
        "minimum_epoch": 8,
    }

    assert registry.verify_statement_binding(public_key, **statement_binding) == (
        registry.root(),
        registry.epoch,
    )

    mismatches = [
        {"expected_relation_id": "ff" * 32},
        {"expected_policy_hash": "ee" * 32},
        {"statement_registry_root": "dd" * 32},
        {"statement_registry_epoch": registry.epoch + 1},
        {"minimum_epoch": registry.epoch + 1},
    ]
    for mismatch in mismatches:
        candidate = {**statement_binding, **mismatch}
        try:
            registry.verify_statement_binding(public_key, **candidate)
        except ValueError:
            continue
        raise AssertionError(f"verifier accepted a mismatched registry binding: {mismatch}")

    try:
        registry.verify_statement_binding(b"x" * len(public_key), **statement_binding)
    except ValueError:
        pass
    else:
        raise AssertionError("verifier accepted a registry signed by an untrusted key")


def t_embedder_gate_requires_an_issuer_verified_lazer_registry() -> None:
    from src.embedder import _resolve_future_zkp_registration
    from src.zkp_registry import SignedZkpRelationRegistry

    public_key, private_key = _issuer_keys()
    registry = SignedZkpRelationRegistry.create(epoch=9, relations=[_relation_descriptor()]).sign(private_key, signer_id="issuer-v1")

    relation_id = registry.relations[0].relation_id
    assert _resolve_future_zkp_registration(relation_id, registry, public_key, registry.relations[0].policy_hash) == (registry.root(), 9)
    try:
        _resolve_future_zkp_registration(relation_id, registry, b"x" * len(public_key), registry.relations[0].policy_hash)
    except ValueError:
        pass
    else:
        raise AssertionError("registry with an untrusted issuer was accepted")


def main() -> None:
    section("Signed future-ZKP relation registry")
    results = [
        run_test("signed_registry_resolves_only_a_registered_lazer_relation", t_signed_registry_resolves_only_a_registered_lazer_relation),
        run_test("registry_rejects_tampering_unknown_relation_or_wrong_issuer", t_registry_rejects_tampering_unknown_relation_or_wrong_issuer),
        run_test("verifier_binding_requires_its_pinned_relation_and_signed_snapshot", t_verifier_binding_requires_its_pinned_relation_and_signed_snapshot),
        run_test("embedder_gate_requires_an_issuer_verified_lazer_registry", t_embedder_gate_requires_an_issuer_verified_lazer_registry),
    ]
    raise SystemExit(summarise(results, "Signed future-ZKP relation registry"))


if __name__ == "__main__":
    main()
