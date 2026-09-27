"""Canonical public statement for a reviewed post-quantum video ZKP.

This module defines the exact public instance a future lattice proof must
verify. It is *not* a proof system. In particular, the private payload and
its 32-byte commitment opening never appear in this statement.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any


VIDEO_ZKP_STATEMENT_VERSION = "1.0.0"
VIDEO_ZKP_STATEMENT_PROTOCOL = "zkstego-pq-video-statement-v1"
VIDEO_ZKP_HASH_ALGORITHMS = {
    "cover_hash": "sha256(file-bytes)",
    "positions_hash": "sha256(canonical-json)",
    "stego_hash": "sha256(file-bytes)",
    "payload_commitment": "sha3-256(domain||opening||payload)",
    "relation_id": "sha256(relation-descriptor-canonical-json)",
    "registry_root": "sha256(domain||issuer-bound-registry-payload-canonical-json)",
    "statement_id": "sha3-256(domain||canonical-json)",
}
_DOMAIN = b"zkstego/pq-video-statement/v1/"
_POLICY_FIELDS = {
    "codec",
    "embedding_strategy",
    "max_modifications_per_block",
    "proof_backend",
}


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def _digest_hex(value: str, field_name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field_name} must be a 32-byte lowercase hexadecimal digest")
    return value


def payload_commitment(payload: bytes, opening: bytes) -> str:
    """Commit to ``payload`` with a private, uniformly random 32-byte opening."""
    if not isinstance(payload, bytes) or not payload:
        raise ValueError("payload must be non-empty bytes")
    if not isinstance(opening, bytes) or len(opening) != 32:
        raise ValueError("opening must be exactly 32 random bytes")
    return hashlib.sha3_256(_DOMAIN + b"payload/" + opening + payload).hexdigest()


def _canonical_policy(policy: dict[str, Any]) -> str:
    if not isinstance(policy, dict) or set(policy) != _POLICY_FIELDS:
        raise ValueError(f"policy must contain exactly {sorted(_POLICY_FIELDS)}")
    if policy["codec"] != "h264-baseline-cavlc":
        raise ValueError("policy.codec must be h264-baseline-cavlc")
    if policy["embedding_strategy"] not in {"t1_sign_flip", "cost_guided_hamming_7_3"}:
        raise ValueError("policy.embedding_strategy is unsupported")
    maximum = policy["max_modifications_per_block"]
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 8:
        raise ValueError("policy.max_modifications_per_block must be an integer from 1 to 8")
    if policy["proof_backend"] not in {"lattice", "lazer"}:
        raise ValueError("policy.proof_backend must be lattice or lazer")
    try:
        encoded = _canonical_json_bytes(policy)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("policy must contain only finite JSON values") from error
    return encoded.decode("ascii")


def policy_hash(policy: dict[str, Any]) -> str:
    """Return the descriptor-bound hash for an admissible video ZKP policy."""
    return hashlib.sha256(
        b"zkstego/pq-video-policy/v1/" + _canonical_policy(policy).encode("ascii")
    ).hexdigest()


@dataclass(frozen=True)
class VideoZkpStatement:
    version: str
    protocol: str
    session_id: str
    payload_commitment: str
    cover_hash: str
    stego_hash: str
    positions_hash: str
    relation_id: str
    registry_root: str
    registry_epoch: int
    policy_canonical: str
    statement_id: str

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "protocol": self.protocol,
            "session_id": self.session_id,
            "payload_commitment": self.payload_commitment,
            "cover_hash": self.cover_hash,
            "stego_hash": self.stego_hash,
            "positions_hash": self.positions_hash,
            "relation_id": self.relation_id,
            "registry_root": self.registry_root,
            "registry_epoch": self.registry_epoch,
            "hash_algorithms": VIDEO_ZKP_HASH_ALGORITHMS,
            "policy": json.loads(self.policy_canonical),
        }

    def to_public_bytes(self) -> bytes:
        """Stable byte sequence that the prover and verifier must share."""
        return _canonical_json_bytes(self._unsigned_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self._unsigned_dict(), "statement_id": self.statement_id}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VideoZkpStatement":
        """Parse an untrusted public statement and recompute its identifier."""
        expected_fields = set(cls.__dataclass_fields__) - {"policy_canonical"}
        expected_fields.update({"policy", "hash_algorithms"})
        if not isinstance(data, dict) or set(data) != expected_fields:
            raise ValueError("statement has an invalid field set")
        if data["version"] != VIDEO_ZKP_STATEMENT_VERSION or data["protocol"] != VIDEO_ZKP_STATEMENT_PROTOCOL:
            raise ValueError("statement version or protocol is unsupported")
        if data["hash_algorithms"] != VIDEO_ZKP_HASH_ALGORITHMS:
            raise ValueError("statement hash algorithms do not match this protocol")
        try:
            rebuilt = build_video_zkp_statement(
                session_id=bytes.fromhex(data["session_id"]),
                payload_commitment_hex=data["payload_commitment"],
                cover_hash=data["cover_hash"],
                stego_hash=data["stego_hash"],
                positions_hash=data["positions_hash"],
                relation_id=data["relation_id"],
                registry_root=data["registry_root"],
                registry_epoch=data["registry_epoch"],
                policy=data["policy"],
            )
        except (TypeError, ValueError) as error:
            raise ValueError("statement is malformed") from error
        if data["statement_id"] != rebuilt.statement_id:
            raise ValueError("statement_id does not match the canonical statement")
        return rebuilt


def build_video_zkp_statement(
    session_id: bytes,
    payload_commitment_hex: str,
    cover_hash: str,
    stego_hash: str,
    positions_hash: str,
    relation_id: str,
    registry_root: str,
    registry_epoch: int,
    policy: dict[str, Any],
) -> VideoZkpStatement:
    """Build a non-ambiguous public instance after stego reconstruction.

    ``relation_id`` identifies a reviewed relation/verifier-key configuration.
    ``registry_root`` and ``registry_epoch`` bind it to an independently
    published registry snapshot; a proof therefore cannot select its own
    semantics silently.
    """
    if not isinstance(session_id, bytes) or len(session_id) != 32:
        raise ValueError("session_id must be exactly 32 random bytes")
    if isinstance(registry_epoch, bool) or not isinstance(registry_epoch, int) or registry_epoch < 0:
        raise ValueError("registry_epoch must be a non-negative integer")
    policy_canonical = _canonical_policy(policy)
    unsigned = {
        "version": VIDEO_ZKP_STATEMENT_VERSION,
        "protocol": VIDEO_ZKP_STATEMENT_PROTOCOL,
        "session_id": session_id.hex(),
        "payload_commitment": _digest_hex(payload_commitment_hex, "payload_commitment"),
        "cover_hash": _digest_hex(cover_hash, "cover_hash"),
        "stego_hash": _digest_hex(stego_hash, "stego_hash"),
        "positions_hash": _digest_hex(positions_hash, "positions_hash"),
        "relation_id": _digest_hex(relation_id, "relation_id"),
        "registry_root": _digest_hex(registry_root, "registry_root"),
        "registry_epoch": registry_epoch,
        "hash_algorithms": VIDEO_ZKP_HASH_ALGORITHMS,
        "policy": json.loads(policy_canonical),
    }
    statement_id = hashlib.sha3_256(_DOMAIN + b"statement/" + _canonical_json_bytes(unsigned)).hexdigest()
    return VideoZkpStatement(
        version=unsigned["version"], protocol=unsigned["protocol"], session_id=unsigned["session_id"],
        payload_commitment=unsigned["payload_commitment"], cover_hash=unsigned["cover_hash"],
        stego_hash=unsigned["stego_hash"], positions_hash=unsigned["positions_hash"],
        relation_id=unsigned["relation_id"], registry_root=unsigned["registry_root"],
        registry_epoch=unsigned["registry_epoch"], policy_canonical=policy_canonical,
        statement_id=statement_id,
    )


def verify_video_zkp_statement_binding(
    statement: VideoZkpStatement,
    registry: object,
    issuer_public_key: bytes,
    *,
    expected_relation_id: str,
    expected_policy_hash: str,
    minimum_epoch: int = 0,
) -> tuple[str, int]:
    """Verify canonical statement fields against verifier-pinned registry data.

    The relation ID, policy hash, issuer key, and minimum registry epoch are
    verifier configuration. They must not be copied from ``statement`` or a
    video. This helper validates the statement/registry trust binding only; it
    does not verify a ZK proof or the files named by relation artifact hashes.
    """
    from .zkp_registry import SignedZkpRelationRegistry

    if not isinstance(statement, VideoZkpStatement):
        raise ValueError("statement must be a VideoZkpStatement")
    if not isinstance(registry, SignedZkpRelationRegistry):
        raise ValueError("registry must be a SignedZkpRelationRegistry")

    # Reparse to reject manually constructed or mutated dataclass instances
    # whose cached statement_id does not match the canonical public bytes.
    canonical_statement = VideoZkpStatement.from_dict(statement.to_dict())
    statement_policy_hash = policy_hash(json.loads(canonical_statement.policy_canonical))
    return registry.verify_statement_binding(
        issuer_public_key,
        statement_relation_id=canonical_statement.relation_id,
        expected_relation_id=expected_relation_id,
        statement_policy_hash=statement_policy_hash,
        expected_policy_hash=expected_policy_hash,
        statement_registry_root=canonical_statement.registry_root,
        statement_registry_epoch=canonical_statement.registry_epoch,
        minimum_epoch=minimum_epoch,
    )
