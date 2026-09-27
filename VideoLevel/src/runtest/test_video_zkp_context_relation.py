"""Experimental algebraic context-binding contract for the pinned LaZer API."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtest._helpers import run_test, section, summarise


def _statement(session_byte: int = 0):
    from src.video_zkp_contract import build_video_zkp_statement, payload_commitment

    return build_video_zkp_statement(
        session_id=bytes([session_byte]) * 32,
        payload_commitment_hex=payload_commitment(b"payload", b"o" * 32),
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
            "proof_backend": "lazer",
        },
    )


def t_context_units_encode_full_digest_in_nonzero_field_elements() -> None:
    from src.video_zkp_contract import derive_statement_context_units

    statement = _statement()
    modulus = 2**32 - 4607
    units = derive_statement_context_units(statement, modulus)
    encoded = sum((unit - 1) * (modulus - 1) ** index for index, unit in enumerate(units))
    digest = hashlib.sha3_256(
        b"zkstego/lazer-context-binding/v1/"
        + len(statement.to_public_bytes()).to_bytes(8, "big")
        + statement.to_public_bytes()
    ).digest()

    assert len(units) == 9
    assert all(1 <= unit < modulus for unit in units)
    assert encoded == int.from_bytes(digest, "big")


def t_augmented_relation_preserves_base_equation_and_constrains_context_witness() -> None:
    from src.video_zkp_contract import build_context_augmented_lattice_relation

    statement = _statement()
    modulus = 101
    matrix = (((2, 3),),)
    target = ((4, 6),)
    result = build_context_augmented_lattice_relation(
        statement, matrix, target, modulus
    )
    degree = 2
    context_count = len(result.context_units)

    assert len(result.matrix) == 1 + context_count
    assert all(len(row) == 1 + context_count for row in result.matrix)
    assert result.matrix[0][0] == (2, 3)
    assert result.lazer_t[0] == ((-4) % modulus, (-6) % modulus)
    assert len(result.witness_suffix) == context_count
    assert all(witness == (1, 0) for witness in result.witness_suffix)

    # A=(2+3X), s=2 in Z_101[X]/(X^2+1), so A*s=(4+6X)=target.
    assert ((2 * 2) % modulus, (3 * 2) % modulus) == target[0]
    for index, unit in enumerate(result.context_units):
        row = 1 + index
        column = 1 + index
        assert result.matrix[row][column] == (unit, 0)
        assert result.lazer_t[row] == ((-unit) % modulus, 0)
        # The public equation h_i*b_i + t_i = 0 forces b_i=1 as h_i is a unit.
        assert (unit * result.witness_suffix[index][0] + result.lazer_t[row][0]) % modulus == 0
    assert degree == len(result.matrix[0][0])


def t_statement_mutation_changes_public_augmented_relation() -> None:
    from src.video_zkp_contract import build_context_augmented_lattice_relation

    matrix = (((2,),),)
    target = ((4,),)
    first = build_context_augmented_lattice_relation(_statement(0), matrix, target, 101)
    second = build_context_augmented_lattice_relation(_statement(1), matrix, target, 101)

    assert first.context_units != second.context_units
    assert first.matrix != second.matrix or first.lazer_t != second.lazer_t


def t_context_relation_rejects_statement_of_wrong_type() -> None:
    from src.video_zkp_contract import _validate_context_statement_and_modulus

    try:
        _validate_context_statement_and_modulus("not a statement", 101)  # type: ignore[arg-type]
    except TypeError:
        return
    raise AssertionError("wrong statement type must raise TypeError")


def t_context_relation_rejects_bad_modulus_and_ragged_polynomials() -> None:
    from src.video_zkp_contract import (
        _validate_context_statement_and_modulus,
        build_context_augmented_lattice_relation,
    )

    statement = _statement()
    try:
        _validate_context_statement_and_modulus(statement, 2)
    except ValueError:
        pass
    else:
        raise AssertionError("binary modulus accepted for nonzero-limb encoding")

    for matrix, target, modulus in (
        ((((1,),),), ((1,),), 15),
        ((((1, 2),),), ((1,),), 101),
        ((((1,),),), ((1,), (2,)), 101),
    ):
        try:
            build_context_augmented_lattice_relation(statement, matrix, target, modulus)
        except ValueError:
            continue
        raise AssertionError("invalid context-bound relation input was accepted")


def main() -> None:
    section("Experimental LaZer statement-context relation")
    results = [
        run_test(
            "context_units_encode_full_digest_in_nonzero_field_elements",
            t_context_units_encode_full_digest_in_nonzero_field_elements,
        ),
        run_test(
            "augmented_relation_preserves_base_equation_and_constrains_context_witness",
            t_augmented_relation_preserves_base_equation_and_constrains_context_witness,
        ),
        run_test(
            "statement_mutation_changes_public_augmented_relation",
            t_statement_mutation_changes_public_augmented_relation,
        ),
        run_test(
            "context_relation_rejects_statement_of_wrong_type",
            t_context_relation_rejects_statement_of_wrong_type,
        ),
        run_test(
            "context_relation_rejects_bad_modulus_and_ragged_polynomials",
            t_context_relation_rejects_bad_modulus_and_ragged_polynomials,
        ),
    ]
    raise SystemExit(summarise(results, "Experimental LaZer statement-context relation"))


if __name__ == "__main__":
    main()
