"""Canonical public statement for a reviewed post-quantum video ZKP.

This module deliberately defines *what* a future lattice proof must bind.  It
does not implement a proof system and must not be represented as a ZKP by
itself.  LaZer (or another reviewed backend) receives ``to_public_bytes()`` as
the domain-separated public statement after a relation-specific adapter exists.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


VIDEO_ZKP_STATEMENT_VERSION = "1.0.0"
VIDEO_ZKP_STATEMENT_PROTOCOL = "zkstego-pq-video-statement-v1"
_DOMAIN = b"zkstego/pq-video-statement/v1/"


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def _digest_hex(value: str, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field_name} must be a 32-byte lowercase hexadecimal SHA-256/SHA3-256 digest")
    try:
        bytes.fromhex(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be hexadecimal") from error
    if value != value.lower():
        raise ValueError(f"{field_name} must be lowercase hexadecimal")
    return value


def payload_commitment(payload: bytes) -> str:
    """Commit to a private payload without placing it in a public statement."""
    if not isinstance(payload, bytes) or not payload:
        raise ValueError("payload must be non-empty bytes")
    return hashlib.sha3_256(_DOMAIN + b"payload/" + payload).hexdigest()


def _canonical_policy(policy: dict[str, Any]) -> str:
    if not isinstance(policy, dict) or not policy:
        raise ValueError("policy must be a non-empty JSON object")
    try:
        encoded = _canonical_json_bytes(policy)
        decoded = json.loads(encoded)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("policy must contain only finite JSON values") from error
    if not isinstance(decoded, dict):
        raise ValueError("policy must be a JSON object")
    return encoded.decode("ascii")


@dataclass(frozen=True)
class VideoZkpStatement:
    version: str
    protocol: str
    session_id: str
    payload_commitment: str
    cover_hash: str
    stego_hash: str
    positions_hash: str
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
            "policy": json.loads(self.policy_canonical),
        }

    def to_public_bytes(self) -> bytes:
        """Stable byte sequence an external prover and verifier must share."""
        return _canonical_json_bytes(self._unsigned_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self._unsigned_dict(), "statement_id": self.statement_id}


def build_video_zkp_statement(
    session_id: bytes,
    payload_commitment_hex: str,
    cover_hash: str,
    stego_hash: str,
    positions_hash: str,
    policy: dict[str, Any],
) -> VideoZkpStatement:
    """Build a non-ambiguous public statement after stego reconstruction.

    ``session_id`` must be generated before embedding and committed into the
    in-video reference.  The other hashes are finalized afterward.  This avoids
    a circular dependency between a proof sidecar and the stego file hash.
    """
    if not isinstance(session_id, bytes) or len(session_id) != 32:
        raise ValueError("session_id must be exactly 32 random bytes")
    policy_canonical = _canonical_policy(policy)
    unsigned = {
        "version": VIDEO_ZKP_STATEMENT_VERSION,
        "protocol": VIDEO_ZKP_STATEMENT_PROTOCOL,
        "session_id": session_id.hex(),
        "payload_commitment": _digest_hex(payload_commitment_hex, "payload_commitment"),
        "cover_hash": _digest_hex(cover_hash, "cover_hash"),
        "stego_hash": _digest_hex(stego_hash, "stego_hash"),
        "positions_hash": _digest_hex(positions_hash, "positions_hash"),
        "policy": json.loads(policy_canonical),
    }
    statement_id = hashlib.sha3_256(_DOMAIN + b"statement/" + _canonical_json_bytes(unsigned)).hexdigest()
    return VideoZkpStatement(
        version=unsigned["version"], protocol=unsigned["protocol"], session_id=unsigned["session_id"],
        payload_commitment=unsigned["payload_commitment"], cover_hash=unsigned["cover_hash"],
        stego_hash=unsigned["stego_hash"], positions_hash=unsigned["positions_hash"],
        policy_canonical=policy_canonical, statement_id=statement_id,
    )
