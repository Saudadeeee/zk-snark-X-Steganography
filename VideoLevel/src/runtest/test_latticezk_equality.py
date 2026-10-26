"""Equality (linear-relation) proof between two BDLOP commitments."""

from __future__ import annotations

import math
import random

import numpy as np
import pytest

from src.lattice_zk import bdlop, codec, equality_proof, opening_proof
from src.lattice_zk.params import BDLOP_OPEN_128, BDLOP_OPEN_128_V1, TOY
from src.runtest.test_latticezk_bdlop import forged_commitment, random_corruptions

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
        bdlop.Commitment(c.t1, (c.t2 + 5) % TOY.modulus, params=TOY) for c in commitments
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
    assert len(proof) == 17_312
    assert equality_proof.verify(params, STATEMENT, commitments[0], commitments[1], proof)
    assert not equality_proof.verify(params, b"other", commitments[0], commitments[1], proof)


def test_verify_never_raises_on_malformed_commitment_objects() -> None:
    commitments, randomness = _pair()
    proof = _prove(commitments, randomness)
    first = commitments[0]
    for malformed in (
        None, "commitment",
        forged_commitment(first.t1.reshape(-1), first.t2),
        forged_commitment(first.t1, np.full_like(first.t2, TOY.modulus)),
        forged_commitment(first.t1.astype(np.float64), first.t2),
    ):
        assert equality_proof.verify(TOY, STATEMENT, malformed, commitments[1], proof) is False
        assert equality_proof.verify(TOY, STATEMENT, commitments[0], malformed, proof) is False
        with pytest.raises((TypeError, ValueError)):
            equality_proof.prove(
                TOY, STATEMENT, malformed, randomness[0], commitments[1], randomness[1]
            )
    assert equality_proof.verify(TOY, "statement", commitments[0], commitments[1], proof) is False


def test_commitment_integer_dtype_does_not_change_the_verdict() -> None:
    """Unsigned arrays must not wrap in t2_a - t2_b; values are normalized to int64."""
    commitments, randomness = _pair()
    proof = _prove(commitments, randomness)
    narrow = [
        bdlop.Commitment(c.t1.astype(np.uint32), c.t2.astype(np.uint32), params=TOY)
        for c in commitments
    ]
    assert equality_proof.verify(TOY, STATEMENT, narrow[0], narrow[1], proof)
    def deterministic(pair, witnesses) -> bytes:
        return equality_proof.prove_with_stats(
            TOY, STATEMENT, pair[0], witnesses[0], pair[1], witnesses[1], mask_seed=b"m" * 32
        ).proof

    narrow_witnesses = [r.astype(np.int8) for r in randomness]
    assert deterministic(narrow, narrow_witnesses) == deterministic(commitments, randomness)
    opening = opening_proof.prove(TOY, STATEMENT, narrow[0], randomness[0])
    assert opening_proof.verify(TOY, STATEMENT, commitments[0], opening)
    assert opening_proof.verify(TOY, STATEMENT, narrow[0], opening)


def test_prover_refuses_malformed_witness_types_and_mask_seed() -> None:
    commitments, randomness = _pair()
    with pytest.raises(TypeError):
        _prove(commitments, [randomness[0].tolist(), randomness[1]])
    with pytest.raises(TypeError):
        _prove(commitments, randomness, statement="statement")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        equality_proof.prove_with_stats(
            TOY, STATEMENT, commitments[0], randomness[0], commitments[1], randomness[1],
            mask_seed=b"short",
        )


def test_random_equal_payloads_always_prove_equal() -> None:
    rng = random.Random(0x5EED0011)
    for _ in range(12):
        payload = rng.randbytes(rng.randrange(TOY.max_payload_bytes + 1))
        statement = rng.randbytes(rng.randrange(200))
        randomness = [bdlop.sample_randomness(TOY, rng.randbytes(32)) for _ in range(2)]
        commitments = [
            bdlop.commit(TOY, codec.encode_payload(TOY, payload), r) for r in randomness
        ]
        proof = equality_proof.prove_with_stats(
            TOY, statement, commitments[0], randomness[0], commitments[1], randomness[1],
            mask_seed=rng.randbytes(32),
        ).proof
        assert equality_proof.verify(TOY, statement, commitments[0], commitments[1], proof)
        assert not equality_proof.verify(TOY, statement, commitments[1], commitments[0], proof)


def test_random_equality_proof_corruptions_never_verify() -> None:
    rng = random.Random(0x5EED0012)
    commitments, randomness = _pair()
    proof = _prove(commitments, randomness)
    for corrupted in random_corruptions(proof, rng, 300):
        assert equality_proof.verify(
            TOY, STATEMENT, commitments[0], commitments[1], corrupted
        ) is False


# -- zero randomness (disclosure) and completeness cap --------------------- #

def test_zero_randomness_opens_the_public_commitment_of_a_message() -> None:
    """``Com(m; 0) = (0, m)`` is a valid ternary opening the prover accepts."""
    commitments, randomness = _pair()
    zero = np.zeros((TOY.width, TOY.degree), dtype=np.int64)
    message = codec.encode_payload(TOY, b"credential")
    public = bdlop.commit(TOY, message, zero)
    assert not public.t1.any() and np.array_equal(public.t2, message)
    proof = equality_proof.prove(TOY, STATEMENT, commitments[0], randomness[0], public, zero)
    assert equality_proof.verify(TOY, STATEMENT, commitments[0], public, proof)
    other = bdlop.commit(TOY, codec.encode_payload(TOY, b"credentiaL"), zero)
    assert not equality_proof.verify(TOY, STATEMENT, commitments[0], other, proof)
    with pytest.raises(ValueError):
        equality_proof.prove(TOY, STATEMENT, commitments[0], randomness[0], other, zero)
    # Zero randomness on both sides is the trivial case and still verifies.
    trivial = equality_proof.prove(TOY, STATEMENT, public, zero, public, zero)
    assert equality_proof.verify(TOY, STATEMENT, public, public, trivial)


@pytest.mark.parametrize("params", [TOY, BDLOP_OPEN_128], ids=lambda p: p.name)
def test_equality_prover_cap_gives_negligible_completeness_error(params) -> None:
    """Both responses must be accepted: p_acc^2 per attempt, own cap below 2^-128."""
    accepted = params.acceptance_probability ** 2
    bound = equality_proof.MAX_ATTEMPTS * math.log2(1.0 - accepted)
    assert bound == pytest.approx(equality_proof.abort_probability_log2(params))
    assert bound < -equality_proof.COMPLETENESS_ERROR_BITS
    assert equality_proof.MAX_ATTEMPTS > opening_proof.MAX_ATTEMPTS


def test_shared_opening_cap_would_not_have_sufficed_for_production() -> None:
    # The 2^-35 of the security review (item D4) was measured on v1.
    capped = equality_proof.abort_probability_log2(BDLOP_OPEN_128_V1, opening_proof.MAX_ATTEMPTS)
    assert -36 < capped < -34
    for params in (BDLOP_OPEN_128_V1, BDLOP_OPEN_128):
        assert opening_proof.MAX_ATTEMPTS * math.log2(1 - params.acceptance_probability) < -128
        assert equality_proof.abort_probability_log2(params, opening_proof.MAX_ATTEMPTS) > -40
