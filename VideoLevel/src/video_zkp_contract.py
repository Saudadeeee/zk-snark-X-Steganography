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
_OPTIONAL_POLICY_FIELDS = {"carrier_profile_hash"}
CarrierPosition = tuple[int, int, int]
_CARRIER_PROFILE_DOMAIN = b"zkstego/pq-video/carrier-profile/v1\x00"
_CARRIER_SEED_DOMAIN = b"zkstego/pq-video/carrier-order-seed/v1\x00"
_CARRIER_CIF_MB_COUNT = 396
_CARRIER_CIF_MB_WIDTH = 22
_CARRIER_BOTTOM_ROW_START = 14


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
    if (
        not isinstance(policy, dict)
        or not _POLICY_FIELDS.issubset(policy)
        or set(policy) - (_POLICY_FIELDS | _OPTIONAL_POLICY_FIELDS)
    ):
        allowed = sorted(_POLICY_FIELDS | _OPTIONAL_POLICY_FIELDS)
        raise ValueError(f"policy must contain the required fields and no fields outside {allowed}")
    if policy["codec"] != "h264-baseline-cavlc":
        raise ValueError("policy.codec must be h264-baseline-cavlc")
    if policy["embedding_strategy"] not in {"t1_sign_flip", "cost_guided_hamming_7_3"}:
        raise ValueError("policy.embedding_strategy is unsupported")
    maximum = policy["max_modifications_per_block"]
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 8:
        raise ValueError("policy.max_modifications_per_block must be an integer from 1 to 8")
    if policy["proof_backend"] not in {"lattice", "lazer"}:
        raise ValueError("policy.proof_backend must be lattice or lazer")
    if "carrier_profile_hash" in policy:
        _digest_hex(policy["carrier_profile_hash"], "policy.carrier_profile_hash")
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


def carrier_policy_hash(carrier_contract: object, required_bits: int) -> str:
    """Hash every blind-carrier behavior knob plus count and seed derivation.

    The resulting digest belongs in the signed/registered statement policy.
    The verifier separately recomputes it from its local contract and expected
    count before deriving any positions from a video.
    """
    from .blind_sync import BlindOperatingContract

    if not isinstance(carrier_contract, BlindOperatingContract):
        raise TypeError("carrier_contract must be a BlindOperatingContract")
    if isinstance(required_bits, bool) or not isinstance(required_bits, int) or required_bits <= 0:
        raise ValueError("required_bits must be a positive integer")
    if not isinstance(carrier_contract.version, str) or not carrier_contract.version:
        raise ValueError("carrier contract version must be non-empty text")
    boolean_fields = (
        "signbit_only",
        "dedup_per_block",
        "metadata_bound",
        "require_bitstream_patchable",
        "stable_carriers_only",
    )
    integer_fields = (
        "bottom_rows",
        "max_bits_per_idr",
        "patchability_headroom",
        "max_modifications_per_block",
    )
    if any(type(getattr(carrier_contract, field)) is not bool for field in boolean_fields):
        raise ValueError("carrier contract boolean fields must be bool")
    for field in integer_fields:
        value = getattr(carrier_contract, field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"carrier contract {field} must be a non-negative integer")
    candidate_derivation = (
        "CAVLC trailing-one sign carriers (encoded as negative coefficient indexes) "
        "from positive-length patchable luma blocks"
        if carrier_contract.signbit_only
        else "first luma AC coefficient with abs(level)>=4, nonzero, and outside "
        "CAVLC trailing-ones from positive-length patchable luma blocks"
    )
    descriptor = {
        "contract_version": carrier_contract.version,
        "signbit_only": carrier_contract.signbit_only,
        "bottom_rows": carrier_contract.bottom_rows,
        "dedup_per_block": carrier_contract.dedup_per_block,
        "max_bits_per_idr": carrier_contract.max_bits_per_idr,
        "metadata_bound": carrier_contract.metadata_bound,
        "require_bitstream_patchable": carrier_contract.require_bitstream_patchable,
        "patchability_headroom": carrier_contract.patchability_headroom,
        "max_modifications_per_block": carrier_contract.max_modifications_per_block,
        "stable_carriers_only": carrier_contract.stable_carriers_only,
        "required_bits": required_bits,
        "session_seed_derivation": "sha256(domain||expected-session-id-bytes)",
        "candidate_derivation": candidate_derivation,
        "candidate_filtering": (
            "intersect stable candidates with safe positions when stable_carriers_only; "
            "then apply signbit_only and bottom_rows contract filters when enabled"
        ),
        "ordering_key_derivation": (
            "metadata_bound ? HMAC-SHA256(session_seed, seed_base||b'|blind-order-v1') : session_seed"
        ),
        "seed_base_derivation": (
            "sha256(canonical-json(version,codec,profile,idr_count,raw_safe_bits,"
            "patchable_block_count,stable_candidate_count,candidate_fingerprint))"
        ),
        "position_shuffle": (
            "ChaosTransformer-v1: logistic keys over candidate order; prioritize local rows >=14; "
            "round-robin candidates over ascending IDR-frame indices"
        ),
        "chaos_key_derivation": (
            "sha256(b'chaos:'||ordering_key); logistic_seed=0.1+uint32_be(digest[4:8])/2^32*0.8; r=3.9999"
        ),
        "cif_macroblock_count": _CARRIER_CIF_MB_COUNT,
        "cif_macroblock_width": _CARRIER_CIF_MB_WIDTH,
        "bottom_row_start": _CARRIER_BOTTOM_ROW_START,
    }
    return hashlib.sha256(
        _CARRIER_PROFILE_DOMAIN + _canonical_json_bytes(descriptor)
    ).hexdigest()


def _derive_carrier_seed(session_id: bytes) -> bytes:
    return hashlib.sha256(_CARRIER_SEED_DOMAIN + session_id).digest()


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
        raise TypeError("statement must be a VideoZkpStatement")
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


def verify_video_zkp_context_binding(
    statement: VideoZkpStatement | dict[str, Any],
    registry: object,
    issuer_public_key: bytes,
    *,
    video_path: str,
    carrier_positions: Sequence[CarrierPosition],
    expected_relation_id: str,
    expected_policy_hash: str,
    minimum_epoch: int = 0,
) -> tuple[str, int]:
    """Verify canonical statement, pinned registry, carriers, and video digest.

    This is a context-integrity helper, **not** a ZK proof verifier. It does
    not derive/authenticate the carrier list, verify ``cover_hash``, fetch or
    hash registry artifacts, open the payload commitment, or verify the
    application relation. Those checks must be performed by a future reviewed
    proof backend and trusted extraction policy.

    Raises ``ValueError`` on any mismatch and returns the validated registry
    root and epoch on success.
    """
    from .manifest import hash_positions

    if isinstance(statement, VideoZkpStatement):
        canonical_statement = VideoZkpStatement.from_dict(statement.to_dict())
    else:
        canonical_statement = VideoZkpStatement.from_dict(statement)

    if not isinstance(carrier_positions, Sequence) or isinstance(
        carrier_positions, (str, bytes, bytearray)
    ):
        raise TypeError("carrier positions must be a finite sequence")
    try:
        normalized_positions = tuple(tuple(position) for position in carrier_positions)
        actual_positions_hash = hash_positions(normalized_positions)
    except (TypeError, ValueError) as error:
        raise ValueError("carrier positions are malformed") from error
    if actual_positions_hash != canonical_statement.positions_hash:
        raise ValueError("carrier positions hash does not match the canonical statement")

    registry_binding = verify_video_zkp_statement_binding(
        canonical_statement,
        registry,
        issuer_public_key,
        expected_relation_id=expected_relation_id,
        expected_policy_hash=expected_policy_hash,
        minimum_epoch=minimum_epoch,
    )
    if not verify_video_zkp_video_commitment(
        canonical_statement, video_path, list(normalized_positions)
    ):
        raise ValueError("canonical video commitment does not match the statement")
    return registry_binding


def verify_video_zkp_context_binding_video_only(
    statement: VideoZkpStatement | dict[str, Any],
    registry: object,
    issuer_public_key: bytes,
    *,
    video_path: str,
    expected_session_id: bytes,
    required_bits: int,
    carrier_contract: object,
    expected_relation_id: str,
    expected_policy_hash: str,
    minimum_epoch: int = 0,
) -> tuple[str, int]:
    """Derive carriers from the video, then verify its pinned context fields.

    ``required_bits`` and ``carrier_contract`` are verifier configuration,
    never values loaded from a prover sidecar. Their complete canonical profile
    hash must be present in and pinned by the statement policy. The session id
    must equal a verifier-issued challenge; it deterministically seeds carrier
    ordering under a domain separator. The function re-derives positions from
    ``video_path`` and passes them to the ordinary context checker, which
    validates the statement's positions hash, registry pins, and
    carrier-normalized video digest. It does **not** verify a ZK proof, payload
    commitment opening, or application predicate.
    """
    from .blind_sync import (
        BlindOperatingContract,
        derive_blind_positions_operating_contract,
    )

    canonical_statement = (
        VideoZkpStatement.from_dict(statement.to_dict())
        if isinstance(statement, VideoZkpStatement)
        else VideoZkpStatement.from_dict(statement)
    )
    if not isinstance(expected_session_id, bytes) or len(expected_session_id) != 32:
        raise ValueError("expected_session_id must be a 32-byte verifier challenge")
    if canonical_statement.session_id != expected_session_id.hex():
        raise ValueError("statement session id does not match the verifier challenge")
    if (
        isinstance(required_bits, bool)
        or not isinstance(required_bits, int)
        or required_bits <= 0
    ):
        raise ValueError("required_bits must be a positive integer from verifier configuration")
    if not isinstance(carrier_contract, BlindOperatingContract):
        raise TypeError("carrier_contract must be a BlindOperatingContract")
    if (
        not carrier_contract.stable_carriers_only
        or not carrier_contract.require_bitstream_patchable
        or carrier_contract.max_modifications_per_block != 1
    ):
        raise ValueError(
            "video-only context verification requires stable, patchability-checked "
            "carriers with one modification per block"
        )
    policy = json.loads(canonical_statement.policy_canonical)
    if (
        policy["embedding_strategy"] == "t1_sign_flip"
        and not carrier_contract.signbit_only
    ):
        raise ValueError(
            "t1_sign_flip requires a trailing-one sign-bit carrier profile"
        )
    registered_profile_hash = policy.get("carrier_profile_hash")
    if registered_profile_hash is None:
        raise ValueError("statement policy does not pin a carrier profile")
    if carrier_policy_hash(carrier_contract, required_bits) != registered_profile_hash:
        raise ValueError("verifier carrier configuration does not match the registered profile hash")
    if carrier_contract.max_modifications_per_block != policy["max_modifications_per_block"]:
        raise ValueError("carrier contract modification limit differs from the statement policy")

    # Reject untrusted statement/registry bindings before parsing/analyzing the
    # caller-supplied video, which is the expensive and attacker-controlled step.
    verify_video_zkp_statement_binding(
        canonical_statement,
        registry,
        issuer_public_key,
        expected_relation_id=expected_relation_id,
        expected_policy_hash=expected_policy_hash,
        minimum_epoch=minimum_epoch,
    )

    carrier_seed = _derive_carrier_seed(expected_session_id)
    positions, _metadata = derive_blind_positions_operating_contract(
        video_path,
        carrier_seed,
        required_bits,
        carrier_contract,
        cif_mb_count=_CARRIER_CIF_MB_COUNT,
    )
    if len(positions) != required_bits:
        raise ValueError(
            f"video-derived carrier capacity is insufficient: need {required_bits}, got {len(positions)}"
        )
    return verify_video_zkp_context_binding(
        canonical_statement,
        registry,
        issuer_public_key,
        video_path=video_path,
        carrier_positions=positions,
        expected_relation_id=expected_relation_id,
        expected_policy_hash=expected_policy_hash,
        minimum_epoch=minimum_epoch,
    )
