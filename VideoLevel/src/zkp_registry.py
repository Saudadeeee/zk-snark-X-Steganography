"""Signed trust-anchor registry for future post-quantum ZKP relations.

The registry is deliberately separate from a video sidecar. A verifier pins
the issuer public key out of band, verifies this document, then accepts only a
relation identifier and registry root that resolve from it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from pqcrypto.sign import ml_dsa_65

from .lattice_pq import LATTICE_SIGNATURE_ALGORITHM, LatticeSigner


REGISTRY_VERSION = "1.0.0"
REGISTRY_PROTOCOL = "zkstego-pq-zkp-relation-registry-v1"
REGISTRY_SIGNATURE_ALGORITHM = LATTICE_SIGNATURE_ALGORITHM
REGISTRY_ZKP_SUITE = "lazer-v1"
_DOMAIN = b"zkstego/pq-zkp-relation-registry/v1/"
_HEX_256 = re.compile(r"[0-9a-f]{64}")
_DESCRIPTOR_FIELDS = {
    "zkp_suite",
    "constraint_module_hash",
    "verifier_key_hash",
    "parameter_set_hash",
    "policy_hash",
}


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def _digest(value: str, field_name: str) -> str:
    if not isinstance(value, str) or _HEX_256.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a 32-byte lowercase hexadecimal digest")
    return value


@dataclass(frozen=True)
class RelationRecord:
    zkp_suite: str
    constraint_module_hash: str
    verifier_key_hash: str
    parameter_set_hash: str
    policy_hash: str

    def descriptor(self) -> dict[str, str]:
        return {
            "zkp_suite": self.zkp_suite,
            "constraint_module_hash": self.constraint_module_hash,
            "verifier_key_hash": self.verifier_key_hash,
            "parameter_set_hash": self.parameter_set_hash,
            "policy_hash": self.policy_hash,
        }

    @property
    def relation_id(self) -> str:
        return hashlib.sha256(_DOMAIN + b"relation/" + _canonical_json_bytes(self.descriptor())).hexdigest()

    @classmethod
    def from_descriptor(cls, value: dict[str, Any]) -> "RelationRecord":
        if not isinstance(value, dict) or set(value) != _DESCRIPTOR_FIELDS:
            raise ValueError("relation descriptor has an invalid field set")
        if value["zkp_suite"] != REGISTRY_ZKP_SUITE:
            raise ValueError("relation record uses an unsupported ZKP suite")
        return cls(
            zkp_suite=value["zkp_suite"],
            constraint_module_hash=_digest(value["constraint_module_hash"], "constraint_module_hash"),
            verifier_key_hash=_digest(value["verifier_key_hash"], "verifier_key_hash"),
            parameter_set_hash=_digest(value["parameter_set_hash"], "parameter_set_hash"),
            policy_hash=_digest(value["policy_hash"], "policy_hash"),
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RelationRecord":
        if not isinstance(value, dict) or set(value) != _DESCRIPTOR_FIELDS | {"relation_id"}:
            raise ValueError("relation record has an invalid field set")
        record = cls.from_descriptor({field: value[field] for field in _DESCRIPTOR_FIELDS})
        if _digest(value["relation_id"], "relation_id") != record.relation_id:
            raise ValueError("relation_id does not match the signed relation descriptor")
        return record

    def to_dict(self) -> dict[str, str]:
        return {**self.descriptor(), "relation_id": self.relation_id}


@dataclass(frozen=True)
class SignedZkpRelationRegistry:
    epoch: int
    relations: tuple[RelationRecord, ...]
    signer_id: str | None = None
    signature: str | None = None

    @classmethod
    def create(cls, *, epoch: int, relations: Iterable[dict[str, Any]]) -> "SignedZkpRelationRegistry":
        if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
            raise ValueError("epoch must be a non-negative integer")
        parsed = tuple(RelationRecord.from_descriptor(record) for record in relations)
        if not parsed:
            raise ValueError("registry must contain at least one relation")
        if len({record.relation_id for record in parsed}) != len(parsed):
            raise ValueError("registry relation identifiers must be unique")
        return cls(epoch=epoch, relations=tuple(sorted(parsed, key=lambda record: record.relation_id)))

    def _unsigned_dict(self) -> dict[str, Any]:
        if self.signer_id is None:
            raise ValueError("registry must have a signer_id before computing a root or signature")
        return {
            "version": REGISTRY_VERSION,
            "protocol": REGISTRY_PROTOCOL,
            "epoch": self.epoch,
            "relations": [record.to_dict() for record in self.relations],
            "signer_id": self.signer_id,
        }

    def root(self) -> str:
        return hashlib.sha256(_DOMAIN + b"root/" + _canonical_json_bytes(self._unsigned_dict())).hexdigest()

    def _signing_bytes(self) -> bytes:
        return _DOMAIN + b"signature/" + _canonical_json_bytes(self._unsigned_dict())

    def sign(self, private_key: bytes, *, signer_id: str) -> "SignedZkpRelationRegistry":
        if not isinstance(signer_id, str) or not signer_id:
            raise ValueError("signer_id must be a non-empty string")
        unsigned = SignedZkpRelationRegistry(self.epoch, self.relations, signer_id)
        signature = LatticeSigner.sign(private_key, unsigned._signing_bytes()).hex()
        return SignedZkpRelationRegistry(self.epoch, self.relations, signer_id, signature)

    def verify(self, public_key: bytes) -> bool:
        if self.signature is None or self.signer_id is None:
            return False
        try:
            signature = bytes.fromhex(self.signature)
            if len(signature) != ml_dsa_65.SIGNATURE_SIZE:
                return False
            return LatticeSigner.verify(public_key, self._signing_bytes(), signature)
        except ValueError:
            return False

    def resolve(self, relation_id: str, zkp_suite: str, expected_policy_hash: str) -> tuple[str, int]:
        relation_id = _digest(relation_id, "relation_id")
        if zkp_suite != REGISTRY_ZKP_SUITE:
            raise ValueError("unsupported ZKP suite")
        expected_policy_hash = _digest(expected_policy_hash, "expected_policy_hash")
        if not any(
            record.relation_id == relation_id
            and record.zkp_suite == zkp_suite
            and record.policy_hash == expected_policy_hash
            for record in self.relations
        ):
            raise ValueError("relation is not registered for this ZKP suite")
        return self.root(), self.epoch

    def to_dict(self) -> dict[str, Any]:
        if self.signature is None or self.signer_id is None:
            raise ValueError("registry must be signed before serialization")
        return {
            **self._unsigned_dict(),
            "signature_algorithm": REGISTRY_SIGNATURE_ALGORITHM,
            "signer_id": self.signer_id,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SignedZkpRelationRegistry":
        required = {
            "version", "protocol", "epoch", "relations", "signature_algorithm", "signer_id", "signature",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("registry has an invalid field set")
        if value["version"] != REGISTRY_VERSION or value["protocol"] != REGISTRY_PROTOCOL:
            raise ValueError("registry version or protocol is unsupported")
        if value["signature_algorithm"] != REGISTRY_SIGNATURE_ALGORITHM:
            raise ValueError("registry signature algorithm is unsupported")
        if not isinstance(value["relations"], list):
            raise ValueError("registry relations must be a JSON array")
        parsed = tuple(RelationRecord.from_dict(record) for record in value["relations"])
        if not parsed or len({record.relation_id for record in parsed}) != len(parsed):
            raise ValueError("registry relations must be unique and non-empty")
        registry = cls(value["epoch"], tuple(sorted(parsed, key=lambda record: record.relation_id)))
        if isinstance(registry.epoch, bool) or not isinstance(registry.epoch, int) or registry.epoch < 0:
            raise ValueError("epoch must be a non-negative integer")
        if not isinstance(value["signer_id"], str) or not value["signer_id"]:
            raise ValueError("registry signer_id must be a non-empty string")
        signature_pattern = rf"[0-9a-f]{{{ml_dsa_65.SIGNATURE_SIZE * 2}}}"
        if not isinstance(value["signature"], str) or re.fullmatch(signature_pattern, value["signature"]) is None:
            raise ValueError("registry signature must be canonical lowercase ML-DSA-65 hexadecimal")
        return cls(registry.epoch, registry.relations, value["signer_id"], value["signature"])
