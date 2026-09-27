"""Canonical public statement for a reviewed post-quantum video ZKP.

This module defines the exact public instance a future lattice proof must
verify. It is *not* a proof system. In particular, the private payload and
its 32-byte commitment opening never appear in this statement.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


VIDEO_ZKP_STATEMENT_VERSION = "2.0.0"
VIDEO_ZKP_STATEMENT_PROTOCOL = "zkstego-pq-video-statement-v2"
VIDEO_ZKP_HASH_ALGORITHMS = {
    "cover_hash": "sha256(file-bytes)",
    "positions_hash": "sha256(canonical-json)",
    "stego_hash": "sha256(canonical-h264-carrier-normalization-v1)",
    "payload_commitment": "sha3-256(domain||opening||payload)",
    "relation_id": "sha256(relation-descriptor-canonical-json)",
    "registry_root": "sha256(domain||issuer-bound-registry-payload-canonical-json)",
    "statement_id": "sha3-256(domain||canonical-json)",
}
_PAYLOAD_DOMAIN = b"zkstego/pq-video-statement/v1/"
_STATEMENT_DOMAIN = b"zkstego/pq-video-statement/v2/"
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
    return hashlib.sha3_256(_PAYLOAD_DOMAIN + b"payload/" + opening + payload).hexdigest()


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


@dataclass(frozen=True)
class ContextAugmentedLatticeRelation:
    """Experimental public linear instance binding a LaZer relation to video context.

    This data structure is not a proof and has not received cryptographic review.
    ``lazer_t`` follows LaZer's demonstrated ``A*s + t = 0`` convention.
    """

    matrix: tuple[tuple[tuple[int, ...], ...], ...]
    lazer_t: tuple[tuple[int, ...], ...]
    witness_suffix: tuple[tuple[int, ...], ...]
    context_units: tuple[int, ...]


_LAZER_CONTEXT_DOMAIN = b"zkstego/lazer-context-binding/v1/"
_U64_MAX = (1 << 64) - 1
_MILLER_RABIN_BASES_U64 = (2, 325, 9375, 28178, 450775, 9780504, 1795265022)


def _is_prime_u64(value: int) -> bool:
    """Deterministically test primality for integers in the unsigned 64-bit range."""
    if value < 2 or value > _U64_MAX:
        return False
    small_primes = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)
    for prime in small_primes:
        if value == prime:
            return True
        if value % prime == 0:
            return False

    odd_part = value - 1
    powers_of_two = 0
    while odd_part % 2 == 0:
        powers_of_two += 1
        odd_part //= 2

    for base in _MILLER_RABIN_BASES_U64:
        witness = base % value
        if witness == 0:
            continue
        residue = pow(witness, odd_part, value)
        if residue in (1, value - 1):
            continue
        for _ in range(powers_of_two - 1):
            residue = residue * residue % value
            if residue == value - 1:
                break
        else:
            return False
    return True


def _validate_context_statement_and_modulus(
    statement: VideoZkpStatement, modulus: int
) -> tuple[VideoZkpStatement, bytes]:
    if not isinstance(statement, VideoZkpStatement):
        raise ValueError("statement must be a VideoZkpStatement")
    if (
        isinstance(modulus, bool)
        or not isinstance(modulus, int)
        or modulus < 3
        or not _is_prime_u64(modulus)
    ):
        raise ValueError("modulus must be a prime integer in the unsigned 64-bit range")
    canonical_statement = VideoZkpStatement.from_dict(statement.to_dict())
    return canonical_statement, canonical_statement.to_public_bytes()


def derive_statement_context_units(
    statement: VideoZkpStatement, modulus: int
) -> tuple[int, ...]:
    """Encode a canonical statement digest as nonzero elements of a prime field.

    The little-endian base-``modulus - 1`` digits are shifted by one, so every
    returned element is a unit modulo ``modulus``. This is a building block for
    an experimental LaZer public-instance transform, not a ZK proof.
    """
    canonical_statement, statement_bytes = _validate_context_statement_and_modulus(
        statement, modulus
    )
    del canonical_statement
    digest = hashlib.sha3_256(
        _LAZER_CONTEXT_DOMAIN
        + len(statement_bytes).to_bytes(8, "big")
        + statement_bytes
    ).digest()
    remaining = int.from_bytes(digest, "big")
    base = modulus - 1
    target_range = 1 << (8 * len(digest))
    unit_count = 1
    capacity = base
    while capacity < target_range:
        capacity *= base
        unit_count += 1

    units: list[int] = []
    for _ in range(unit_count):
        remaining, digit = divmod(remaining, base)
        units.append(digit + 1)
    if remaining:
        raise ArithmeticError("internal error: statement digest did not fit in field limbs")
    return tuple(units)


def _polynomial_coefficients(value: object, degree: int, modulus: int) -> tuple[int, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or len(value) != degree
    ):
        raise ValueError("every ring element must be a coefficient sequence of equal degree")
    if any(isinstance(coefficient, bool) or not isinstance(coefficient, int) for coefficient in value):
        raise ValueError("ring coefficients must be integers")
    return tuple(coefficient % modulus for coefficient in value)


def build_context_augmented_lattice_relation(
    statement: VideoZkpStatement,
    matrix: Sequence[Sequence[Sequence[int]]],
    target: Sequence[Sequence[int]],
    modulus: int,
) -> ContextAugmentedLatticeRelation:
    """Build an experimental LaZer relation instance tied to a video statement.

    The base relation is ``A*s = target`` over ``Z_q[X]/(X^d + 1)``. Diagonal
    context rows add public unit equations ``h_i*b_i = h_i``; the returned
    witness suffix is ``b_i = 1``. A caller must also constrain each auxiliary
    witness polynomial to coefficient infinity norm at most one. The result
    must not be treated as secure or passed to a proof backend until the exact
    LaZer parameterization and this transform receive independent review.
    """
    canonical_statement, _statement_bytes = _validate_context_statement_and_modulus(
        statement, modulus
    )
    if (
        not isinstance(matrix, Sequence)
        or isinstance(matrix, (str, bytes, bytearray))
        or not matrix
    ):
        raise ValueError("matrix must be a non-empty rectangular sequence")
    if (
        not isinstance(target, Sequence)
        or isinstance(target, (str, bytes, bytearray))
        or len(target) != len(matrix)
    ):
        raise ValueError("target must contain one ring element for each matrix row")

    first_row = matrix[0]
    if (
        not isinstance(first_row, Sequence)
        or isinstance(first_row, (str, bytes, bytearray))
        or not first_row
    ):
        raise ValueError("matrix must have at least one column")
    row_count = len(matrix)
    column_count = len(first_row)
    first_element = first_row[0]
    if (
        not isinstance(first_element, Sequence)
        or isinstance(first_element, (str, bytes, bytearray))
        or not first_element
    ):
        raise ValueError("matrix elements must be non-empty polynomial coefficient sequences")
    degree = len(first_element)
    base_matrix: list[tuple[tuple[int, ...], ...]] = []
    for row in matrix:
        if (
            not isinstance(row, Sequence)
            or isinstance(row, (str, bytes, bytearray))
            or len(row) != column_count
        ):
            raise ValueError("matrix must be rectangular")
        base_matrix.append(
            tuple(_polynomial_coefficients(element, degree, modulus) for element in row)
        )
    base_target = tuple(
        _polynomial_coefficients(element, degree, modulus) for element in target
    )

    units = derive_statement_context_units(canonical_statement, modulus)
    zero = (0,) * degree
    context_rows: list[tuple[tuple[int, ...], ...]] = []
    for index, unit in enumerate(units):
        row = [zero] * (column_count + len(units))
        row[column_count + index] = (unit,) + (0,) * (degree - 1)
        context_rows.append(tuple(row))

    augmented_matrix = tuple(
        tuple(row) + (zero,) * len(units) for row in base_matrix
    ) + tuple(context_rows)
    public_target = base_target + tuple(
        (unit,) + (0,) * (degree - 1) for unit in units
    )
    lazer_t = tuple(
        tuple((-coefficient) % modulus for coefficient in polynomial)
        for polynomial in public_target
    )
    witness_suffix = tuple((1,) + (0,) * (degree - 1) for _ in units)
    return ContextAugmentedLatticeRelation(
        matrix=augmented_matrix,
        lazer_t=lazer_t,
        witness_suffix=witness_suffix,
        context_units=units,
    )


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
    statement_id = hashlib.sha3_256(
        _STATEMENT_DOMAIN + b"statement/" + _canonical_json_bytes(unsigned)
    ).hexdigest()
    return VideoZkpStatement(
        version=unsigned["version"], protocol=unsigned["protocol"], session_id=unsigned["session_id"],
        payload_commitment=unsigned["payload_commitment"], cover_hash=unsigned["cover_hash"],
        stego_hash=unsigned["stego_hash"], positions_hash=unsigned["positions_hash"],
        relation_id=unsigned["relation_id"], registry_root=unsigned["registry_root"],
        registry_epoch=unsigned["registry_epoch"], policy_canonical=policy_canonical,
        statement_id=statement_id,
    )


def verify_video_zkp_video_commitment(
    statement: VideoZkpStatement,
    video_path: str,
    carrier_positions: list[tuple[int, int, int]],
) -> bool:
    """Recompute the carrier-normalized video digest in a public statement.

    This checks only that the supplied video and carrier list reproduce
    ``statement.stego_hash``. It does not validate a ZK proof, the carrier-list
    origin, the cover hash, or a relation registry. Those remain separate
    verifier obligations.
    """
    if not isinstance(statement, VideoZkpStatement):
        raise ValueError("statement must be a VideoZkpStatement")
    canonical_statement = VideoZkpStatement.from_dict(statement.to_dict())
    from .video_canonicalization import canonical_video_sha256

    return canonical_video_sha256(video_path, carrier_positions) == canonical_statement.stego_hash


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
