"""Equality (linear-relation) proof between two BDLOP commitments."""

from __future__ import annotations

import numpy as np
import pytest

from src.lattice_zk import bdlop, codec, equality_proof, opening_proof
from src.lattice_zk.params import BDLOP_OPEN_128, TOY

STATEMENT = b"video statement"


def _pair(params=TOY, first_payload: bytes = b"credential", second_payload: bytes = b"credential"):
    randomness = [bdlop.sample_randomness(params, bytes([index]) * 32) for index in (1, 2)]
    commitments = [
        bdlop.commit(params, codec.encode_payload(params, payload), r)
        for payload, r in zip((first_payload, second_payload), randomness)
    ]
    return commitments, randomness


def _prove(commitments, randomness, params=TOY, statement: bytes = STATEMENT) -> bytes:
    return equality_proof.prove(
        params, statement, commitments[0], randomness[0], commitments[1], randomness[1]
    )


def test_equal_messages_verify_with_the_size_of_two_opening_proofs() -> None:
    commitments, randomness = _pair()
    proof = _prove(commitments, randomness)
    assert len(proof) == equality_proof.proof_bytes(TOY) == 2 * TOY.proof_bytes - 32
    assert equality_proof.verify(TOY, STATEMENT, commitments[0], commitments[1], proof)


def test_different_messages_cannot_be_proved_equal() -> None:
    commitments, randomness = _pair(second_payload=b"credentiaL")
    with pytest.raises(ValueError):
        _prove(commitments, randomness)
    honest, honest_randomness = _pair()
    proof = _prove(honest, honest_randomness)
    assert not equality_proof.verify(TOY, STATEMENT, honest[0], commitments[1], proof)


def test_each_commitment_still_needs_its_own_opening() -> None:
    commitments, randomness = _pair()
    stranger = bdlop.sample_randomness(TOY, b"\x09" * 32)
    with pytest.raises(ValueError):
        _prove(commitments, [randomness[0], stranger])


def test_proof_is_bound_to_statement_order_and_both_commitments() -> None:
    commitments, randomness = _pair()
    proof = _prove(commitments, randomness)
    assert not equality_proof.verify(TOY, STATEMENT + b"x", commitments[0], commitments[1], proof)
    assert not equality_proof.verify(TOY, STATEMENT, commitments[1], commitments[0], proof)
    shifted = [
        bdlop.Commitment(c.t1, (c.t2 + 5) % TOY.modulus) for c in commitments
    ]  # same message gap, different commitments
    assert not equality_proof.verify(TOY, STATEMENT, shifted[0], shifted[1], proof)
    other, _ = _pair(first_payload=b"z", second_payload=b"z")
    assert not equality_proof.verify(TOY, STATEMENT, commitments[0], other[1], proof)


def test_tampered_or_malformed_proofs_are_rejected() -> None:
    commitments, randomness = _pair()
    proof = _prove(commitments, randomness)
    for position in (0, 31, 32, len(proof) // 2, len(proof) - 1):
        mutated = bytearray(proof)
        mutated[position] ^= 0x10
        assert not equality_proof.verify(TOY, STATEMENT, commitments[0], commitments[1], bytes(mutated))
    assert not equality_proof.verify(TOY, STATEMENT, commitments[0], commitments[1], proof[:-1])
    assert not equality_proof.verify(TOY, STATEMENT, commitments[0], commitments[1], b"")


def test_an_opening_proof_is_not_an_equality_proof() -> None:
    commitments, randomness = _pair()
    opening = opening_proof.prove(TOY, STATEMENT, commitments[0], randomness[0])
    padded = opening + bytes(equality_proof.proof_bytes(TOY) - len(opening))
    assert not equality_proof.verify(TOY, STATEMENT, commitments[0], commitments[1], padded)


def test_prover_refuses_non_ternary_randomness() -> None:
    commitments, randomness = _pair()
    with pytest.raises(ValueError):
        _prove(commitments, [randomness[0], randomness[1] * 2])


def test_responses_stay_in_range() -> None:
    commitments, randomness = _pair()
    proof = _prove(commitments, randomness)
    span = 2 * TOY.response_bound + 1
    shifted = codec.unpack_uints(proof[32:], 2 * TOY.width * TOY.degree, TOY.response_bits, span)
    assert int(np.abs(shifted - TOY.response_bound).max()) <= TOY.response_bound


def test_production_parameters_prove_equality() -> None:
    params = BDLOP_OPEN_128
    commitments, randomness = _pair(params)
    proof = _prove(commitments, randomness, params)
    assert len(proof) == 15_008
    assert equality_proof.verify(params, STATEMENT, commitments[0], commitments[1], proof)
    assert not equality_proof.verify(params, b"other", commitments[0], commitments[1], proof)
