"""BDLOP commitment and Fiat-Shamir opening proof: correctness and rejection."""

from __future__ import annotations

import dataclasses
import random

import numpy as np
import pytest

from src.lattice_zk import bdlop, codec, opening_proof, ring, sampling
from src.lattice_zk.params import BDLOP_OPEN_128, TOY

STATEMENT = b"canonical video statement"


def _committed(payload: bytes = b"hidden payload", seed: bytes = b"r" * 32):
    message = codec.encode_payload(TOY, payload)
    randomness = bdlop.sample_randomness(TOY, seed)
    return message, randomness, bdlop.commit(TOY, message, randomness)


def _flip_bit(data: bytes, bit: int) -> bytes:
    mutated = bytearray(data)
    mutated[bit // 8] ^= 0x80 >> (bit % 8)
    return bytes(mutated)


# -- parameters ----------------------------------------------------------- #

def test_parameter_id_pins_every_field() -> None:
    changed = [
        dataclasses.replace(TOY, name="other"),
        dataclasses.replace(TOY, mlwe_rank=2),
        dataclasses.replace(TOY, challenge_weight=11),
        dataclasses.replace(TOY, mask_bound=1 << 13, modulus=4_194_301),
        dataclasses.replace(TOY, setup_seed=b"\x01" * 32),
    ]
    identifiers = {TOY.parameter_id, *(params.parameter_id for params in changed)}
    assert len(identifiers) == len(changed) + 1
    assert TOY.parameter_id == dataclasses.replace(TOY).parameter_id


def test_parameters_reject_unsound_choices() -> None:
    with pytest.raises(ValueError):
        dataclasses.replace(TOY, modulus=8_380_417)  # fully splitting prime
    with pytest.raises(ValueError):
        dataclasses.replace(TOY, mask_bound=1 << 14)  # binding bound wraps q
    with pytest.raises(ValueError):
        dataclasses.replace(TOY, mask_bound=8)  # below the shift bound
    with pytest.raises(ValueError):
        dataclasses.replace(TOY, degree=96)
    with pytest.raises(ValueError):
        TOY.require_production_strength()


def test_sizes_match_serialized_objects() -> None:
    _, randomness, commitment = _committed()
    assert len(commitment.to_bytes(TOY)) == TOY.commitment_bytes
    assert len(opening_proof.prove(TOY, STATEMENT, commitment, randomness)) == TOY.proof_bytes


# -- codec ---------------------------------------------------------------- #

def test_pack_uints_round_trip_and_canonical_rejection() -> None:
    values = np.array([0, 1, 5, 6, 3], dtype=np.int64)
    packed = codec.pack_uints(values, 3)
    assert len(packed) == 2
    assert codec.unpack_uints(packed, 5, 3, 7).tolist() == values.tolist()
    with pytest.raises(ValueError):
        codec.unpack_uints(packed, 5, 3, 6)  # coefficient at the bound
    with pytest.raises(ValueError):
        codec.unpack_uints(packed[:-1], 5, 3, 7)
    with pytest.raises(ValueError):
        codec.unpack_uints(_flip_bit(packed, 15), 5, 3, 7)  # padding bit
    with pytest.raises(ValueError):
        codec.pack_uints(np.array([8]), 3)
    with pytest.raises(ValueError):
        codec.pack_uints(np.array([-1]), 3)


@pytest.mark.parametrize("payload", [b"", b"a", bytes(range(256))[:TOY.max_payload_bytes]])
def test_payload_encoding_round_trip(payload: bytes) -> None:
    message = codec.encode_payload(TOY, payload)
    assert message.shape == (TOY.degree,) and int(message.max()) < TOY.modulus
    assert codec.decode_payload(TOY, message) == payload


def test_payload_encoding_is_injective_and_bounded() -> None:
    assert not np.array_equal(codec.encode_payload(TOY, b"a"), codec.encode_payload(TOY, b"a\x00"))
    with pytest.raises(ValueError):
        codec.encode_payload(TOY, b"x" * (TOY.max_payload_bytes + 1))
    non_canonical = codec.encode_payload(TOY, b"a")
    non_canonical[-1] = 1  # nonzero padding beyond the declared length
    with pytest.raises(ValueError):
        codec.decode_payload(TOY, non_canonical)
    with pytest.raises(ValueError):
        codec.decode_payload(TOY, np.full(TOY.degree, TOY.modulus - 1, dtype=np.int64))


# -- commitment ----------------------------------------------------------- #

def test_key_derivation_is_deterministic_and_seed_bound() -> None:
    key = bdlop.derive_key(TOY)
    other = bdlop.derive_key(dataclasses.replace(TOY, setup_seed=b"\x02" * 32))
    assert key.b1_tail.shape == (1, 2, TOY.degree) and key.b2_tail.shape == (1, 1, TOY.degree)
    assert np.array_equal(key.b1_tail, bdlop.derive_key(dataclasses.replace(TOY)).b1_tail)
    assert not np.array_equal(key.b1_tail, other.b1_tail)


def test_commitment_opens_only_to_its_message_and_randomness() -> None:
    message, randomness, commitment = _committed()
    assert bdlop.verify_opening(TOY, commitment, message, randomness)
    assert not bdlop.verify_opening(TOY, commitment, codec.encode_payload(TOY, b"other"), randomness)
    assert not bdlop.verify_opening(TOY, commitment, message, bdlop.sample_randomness(TOY, b"x" * 32))
    long_randomness = randomness.copy()
    long_randomness[0, 0] = 2
    assert not bdlop.verify_opening(TOY, commitment, message, long_randomness)


def test_commitment_is_randomized_and_serializes_canonically() -> None:
    _, _, first = _committed(seed=b"1" * 32)
    _, _, second = _committed(seed=b"2" * 32)
    assert first.to_bytes(TOY) != second.to_bytes(TOY)
    restored = bdlop.Commitment.from_bytes(TOY, first.to_bytes(TOY))
    assert np.array_equal(restored.t1, first.t1) and np.array_equal(restored.t2, first.t2)
    out_of_range = codec.pack_uints(
        np.full(2 * TOY.degree, TOY.modulus, dtype=np.int64), TOY.modulus_bits
    )
    with pytest.raises(ValueError):
        bdlop.Commitment.from_bytes(TOY, out_of_range)
    assert not np.array_equal(
        bdlop.sample_randomness(TOY), bdlop.sample_randomness(TOY)
    )


# -- opening proof -------------------------------------------------------- #

def test_honest_proof_verifies() -> None:
    _, randomness, commitment = _committed()
    proof = opening_proof.prove(TOY, STATEMENT, commitment, randomness)
    assert opening_proof.verify(TOY, STATEMENT, commitment, proof)


def test_proof_is_bound_to_statement_commitment_and_parameters() -> None:
    _, randomness, commitment = _committed()
    proof = opening_proof.prove(TOY, STATEMENT, commitment, randomness)
    assert not opening_proof.verify(TOY, STATEMENT + b"x", commitment, proof)
    assert not opening_proof.verify(TOY, b"", commitment, proof)
    _, _, other = _committed(seed=b"o" * 32)
    assert not opening_proof.verify(TOY, STATEMENT, other, proof)
    # t2 never enters the verification equation; only the transcript binds it.
    moved = bdlop.Commitment(commitment.t1, (commitment.t2 + 1) % TOY.modulus)
    assert not opening_proof.verify(TOY, STATEMENT, moved, proof)
    reseeded = dataclasses.replace(TOY, name="bdlop-open-toy-v2")
    assert not opening_proof.verify(reseeded, STATEMENT, commitment, proof)


def test_every_region_of_the_proof_is_tamper_evident() -> None:
    _, randomness, commitment = _committed()
    proof = opening_proof.prove(TOY, STATEMENT, commitment, randomness)
    total_bits = len(proof) * 8
    for bit in (0, 255, 256, 257, total_bits // 2, total_bits - 9, total_bits - 1):
        assert not opening_proof.verify(TOY, STATEMENT, commitment, _flip_bit(proof, bit))
    assert not opening_proof.verify(TOY, STATEMENT, commitment, proof[:-1])
    assert not opening_proof.verify(TOY, STATEMENT, commitment, proof + b"\x00")
    assert not opening_proof.verify(TOY, STATEMENT, commitment, b"")
    assert not opening_proof.verify(TOY, STATEMENT, commitment, "not bytes")  # type: ignore[arg-type]


def test_prover_refuses_a_non_ternary_witness() -> None:
    _, randomness, commitment = _committed()
    with pytest.raises(ValueError):
        opening_proof.prove(TOY, STATEMENT, commitment, randomness * 2)
    with pytest.raises(ValueError):
        opening_proof.prove(TOY, STATEMENT, commitment, randomness[:-1])


def test_prover_refuses_randomness_that_does_not_open_the_commitment() -> None:
    _, _, commitment = _committed()
    wrong = bdlop.sample_randomness(TOY, b"w" * 32)
    with pytest.raises(ValueError):
        opening_proof.prove(TOY, STATEMENT, commitment, wrong)


def test_proof_for_another_commitment_does_not_transfer() -> None:
    _, _, target = _committed()
    _, own_randomness, own = _committed(seed=b"w" * 32)
    proof = opening_proof.prove(TOY, STATEMENT, own, own_randomness)
    assert not opening_proof.verify(TOY, STATEMENT, target, proof)
    # Same t1, attacker-chosen t2: the transcript hash still pins t2.
    moved = bdlop.Commitment(own.t1, target.t2)
    assert not opening_proof.verify(TOY, STATEMENT, moved, proof)


def test_mask_stream_is_never_reused_across_statements_or_witnesses() -> None:
    randomness = bdlop.sample_randomness(TOY, b"r" * 32)
    keys = {
        opening_proof.hedged_mask_key(b"e" * 32, b"s1", b"c", randomness),
        opening_proof.hedged_mask_key(b"e" * 32, b"s2", b"c", randomness),
        opening_proof.hedged_mask_key(b"e" * 32, b"s1", b"d", randomness),
        opening_proof.hedged_mask_key(b"e" * 32, b"s1", b"c", -randomness),
        opening_proof.hedged_mask_key(b"f" * 32, b"s1", b"c", randomness),
        opening_proof.hedged_mask_key(b"e" * 32, b"s", b"1c", randomness),
    }
    assert len(keys) == 6


def test_response_bound_leaves_exactly_the_shift_margin() -> None:
    for params in (TOY, BDLOP_OPEN_128):
        assert params.response_bound == params.mask_bound - params.challenge_weight - 1
        # y = z - c r stays inside the mask range [-gamma + 1, gamma] for every accepted z.
        assert -params.response_bound - params.shift_bound >= -params.mask_bound + 1
        assert params.response_bound + params.shift_bound <= params.mask_bound
        assert 2 * params.response_bound < 1 << params.response_bits


def test_respond_accepts_exactly_the_response_range() -> None:
    _, randomness, commitment = _committed()
    key, encoded = bdlop.derive_key(TOY), commitment.to_bytes(TOY)
    zero_witness = np.zeros_like(randomness)
    edge = np.zeros_like(randomness)
    edge[0, 0] = TOY.response_bound
    assert opening_proof._respond(TOY, key, STATEMENT, encoded, zero_witness, edge) is not None
    edge[0, 0] = -TOY.response_bound
    assert opening_proof._respond(TOY, key, STATEMENT, encoded, zero_witness, edge) is not None
    for beyond in (TOY.response_bound + 1, -TOY.response_bound - 1):
        edge[0, 0] = beyond
        assert opening_proof._respond(TOY, key, STATEMENT, encoded, zero_witness, edge) is None


def test_accepted_response_coordinate_is_uniform_for_any_witness() -> None:
    """Tiny mask range, where a wrong margin would visibly skew the edges."""
    tiny = dataclasses.replace(TOY, name="tiny", degree=8, challenge_weight=3, mask_bound=32)
    span = 2 * tiny.response_bound + 1
    message = codec.encode_payload(tiny, b"")
    for label in (b"A", b"B"):
        randomness = bdlop.sample_randomness(tiny, label * 32)
        commitment = bdlop.commit(tiny, message, randomness)
        counts = np.zeros(span, dtype=np.int64)
        for index in range(600):
            proof = opening_proof.prove_with_stats(
                tiny, STATEMENT, commitment, randomness,
                mask_seed=label + index.to_bytes(4, "big") * 7 + b"xyz",
            ).proof
            shifted = codec.unpack_uints(
                proof[32:], tiny.width * tiny.degree, tiny.response_bits, span
            )
            counts += np.bincount(shifted, minlength=span)
        expected = counts.sum() / span
        chi_square = float(((counts - expected) ** 2 / expected).sum())
        assert chi_square < 110.0  # 56 degrees of freedom; p ~ 3e-5
        assert counts.min() > 0.7 * expected  # both edges are as likely as the centre


def test_two_transcripts_with_one_mask_yield_a_relaxed_opening() -> None:
    """Special soundness: the extractor's equations hold for real transcripts."""
    message, randomness, commitment = _committed()
    key, q = bdlop.derive_key(TOY), TOY.modulus
    mask = sampling.mask_vector(sampling.XofStream(b"mask"), TOY.mask_bound // 2, (TOY.width, TOY.degree))
    challenges = [sampling.challenge_poly(bytes([i]) * 32, TOY.degree, TOY.challenge_weight) for i in (1, 2)]
    responses = [
        mask + ring.center(opening_proof._challenge_times(c, randomness, q), q) for c in challenges
    ]
    difference = (challenges[0] - challenges[1]) % q
    opening = (responses[0] - responses[1]) % q
    assert ring.is_invertible(difference, q)
    assert int(np.abs(ring.center(opening, q)).max()) <= 2 * TOY.shift_bound
    assert np.array_equal(
        key.apply_b1(opening), opening_proof._challenge_times(difference, commitment.t1, q)
    )
    scaled_message = (
        ring.poly_mul(difference, commitment.t2, q) - key.apply_b2(opening)
    ) % q
    assert np.array_equal(scaled_message, ring.poly_mul(difference, message, q))


def test_accepted_responses_are_in_range_and_witness_independent() -> None:
    """Accepted z is uniform on its range whatever the witness is."""
    buckets = 8
    span = 2 * TOY.response_bound + 1
    histograms = []
    for label in (b"A", b"B"):
        _, randomness, commitment = _committed(seed=label * 32)
        counts = np.zeros(buckets, dtype=np.int64)
        for index in range(40):
            proof = opening_proof.prove_with_stats(
                TOY, STATEMENT, commitment, randomness, mask_seed=label + bytes([index]) * 31
            ).proof
            shifted = codec.unpack_uints(proof[32:], TOY.width * TOY.degree, TOY.response_bits, span)
            counts += np.bincount(shifted * buckets // span, minlength=buckets)
        histograms.append(counts)
    for counts in histograms:
        expected = counts.sum() / buckets
        chi_square = float(((counts - expected) ** 2 / expected).sum())
        assert chi_square < 30.0  # 7 degrees of freedom; p ~ 1e-4


def test_abort_rate_matches_the_parameter_estimate() -> None:
    _, randomness, commitment = _committed()
    attempts = [
        opening_proof.prove_with_stats(
            TOY, STATEMENT, commitment, randomness, mask_seed=bytes([index]) * 32
        ).attempts
        for index in range(60)
    ]
    observed = len(attempts) / sum(attempts)
    assert TOY.acceptance_probability * 0.8 < observed < TOY.acceptance_probability * 1.3


def test_proving_is_deterministic_only_under_an_explicit_mask_seed() -> None:
    _, randomness, commitment = _committed()
    fixed = [
        opening_proof.prove_with_stats(TOY, STATEMENT, commitment, randomness, mask_seed=b"m" * 32).proof
        for _ in range(2)
    ]
    assert fixed[0] == fixed[1]
    assert opening_proof.prove(TOY, STATEMENT, commitment, randomness) != fixed[0]


# -- production parameter set -------------------------------------------- #

def test_production_set_meets_structural_requirements() -> None:
    params = BDLOP_OPEN_128
    params.require_production_strength()
    assert params.modulus % 8 == 5 and params.width == 13
    assert params.commitment_bytes == 6_720 and params.proof_bytes == 7_520
    assert params.max_payload_bytes == 766
    assert 0.2 < params.acceptance_probability < 0.25


def test_production_set_proves_and_rejects() -> None:
    params = BDLOP_OPEN_128
    payload = b"production payload" * 4
    message = codec.encode_payload(params, payload)
    randomness = bdlop.sample_randomness(params)
    commitment = bdlop.commit(params, message, randomness)
    assert bdlop.verify_opening(params, commitment, message, randomness)
    result = opening_proof.prove_with_stats(params, STATEMENT, commitment, randomness)
    restored = bdlop.Commitment.from_bytes(params, commitment.to_bytes(params))
    assert opening_proof.verify(params, STATEMENT, restored, result.proof)
    assert not opening_proof.verify(params, STATEMENT + b"!", restored, result.proof)
    assert not opening_proof.verify(params, STATEMENT, restored, _flip_bit(result.proof, 4_000))
    assert codec.decode_payload(params, message) == payload


def test_production_challenge_differences_are_invertible() -> None:
    params = BDLOP_OPEN_128
    first = sampling.challenge_poly(b"\x01" * 32, params.degree, params.challenge_weight)
    second = sampling.challenge_poly(b"\x02" * 32, params.degree, params.challenge_weight)
    assert ring.is_invertible((first - second) % params.modulus, params.modulus)


# -- input validation and exception safety ------------------------------- #

def random_corruptions(data: bytes, rng: random.Random, count: int) -> list[bytes]:
    """Distinct corruptions of ``data``: bit flips, byte rewrites, truncation, extension."""
    corrupted = []
    while len(corrupted) < count:
        mutated = bytearray(data)
        kind = rng.randrange(5)
        if kind == 0:
            bit = rng.randrange(len(data) * 8)
            mutated[bit // 8] ^= 0x80 >> (bit % 8)
        elif kind == 1:
            for bit in rng.sample(range(len(data) * 8), rng.randint(2, 8)):
                mutated[bit // 8] ^= 0x80 >> (bit % 8)
        elif kind == 2:
            index = rng.randrange(len(data))
            mutated[index] = (mutated[index] + rng.randint(1, 255)) % 256
        elif kind == 3:
            del mutated[rng.randrange(len(data)):]
        else:
            mutated += rng.randbytes(rng.randint(1, 16))
        assert bytes(mutated) != data
        corrupted.append(bytes(mutated))
    return corrupted


@pytest.mark.parametrize(
    "changes",
    [
        {"name": ""}, {"name": "pärameters"}, {"name": "x" * 70_000}, {"name": 7},
        {"degree": True}, {"degree": 64.0}, {"msis_rank": 1 << 32}, {"modulus": -1_048_573},
        {"challenge_weight": 1 << 32}, {"setup_seed": "s" * 32},
    ],
)
def test_parameters_reject_malformed_field_types(changes: dict) -> None:
    with pytest.raises(ValueError):
        dataclasses.replace(TOY, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"msis_rank": 0}, {"mlwe_rank": 0}, {"challenge_weight": 0},
        {"challenge_weight": TOY.degree + 1}, {"setup_seed": b"s" * 31},
        {"modulus": 5, "mask_bound": 16, "challenge_weight": 1},  # differences not invertible
    ],
)
def test_parameters_reject_out_of_range_values(changes: dict) -> None:
    with pytest.raises(ValueError):
        dataclasses.replace(TOY, **changes)


def test_provers_fail_closed_when_every_attempt_aborts(monkeypatch) -> None:
    from src.lattice_zk import equality_proof

    _, randomness, commitment = _committed()
    monkeypatch.setattr(opening_proof, "MAX_ATTEMPTS", 0)
    monkeypatch.setattr(equality_proof, "MAX_ATTEMPTS", 0)
    with pytest.raises(RuntimeError):
        opening_proof.prove(TOY, STATEMENT, commitment, randomness)
    with pytest.raises(RuntimeError):
        equality_proof.prove(TOY, STATEMENT, commitment, randomness, commitment, randomness)


def test_commit_refuses_malformed_witness_and_message() -> None:
    message, randomness, _ = _committed()
    for value, error in (
        (randomness * 2, ValueError),  # not in S_1: hiding needs ternary randomness
        (randomness[:-1], ValueError),
        (randomness.astype(np.float64), TypeError),
        (randomness.tolist(), TypeError),
        (np.full(randomness.shape, 1 << 63, dtype=np.uint64), ValueError),
    ):
        with pytest.raises(error):
            bdlop.commit(TOY, message, value)
    for value, error in (
        (message.astype(np.float64), TypeError),
        (message[:-1], ValueError),
        (np.full_like(message, TOY.modulus), ValueError),
        (-np.ones_like(message), ValueError),
    ):
        with pytest.raises(error):
            bdlop.commit(TOY, value, randomness)


def test_commitment_is_independent_of_the_integer_dtype() -> None:
    message, randomness, commitment = _committed()
    narrow = bdlop.commit(TOY, message.astype(np.int32), randomness.astype(np.int8))
    assert narrow.to_bytes(TOY) == commitment.to_bytes(TOY)


def test_randomness_seed_must_be_at_least_32_bytes() -> None:
    for seed in (b"", b"s" * 31, "s" * 32, bytearray(32)):
        with pytest.raises(ValueError):
            bdlop.sample_randomness(TOY, seed)  # type: ignore[arg-type]
    assert np.array_equal(
        bdlop.sample_randomness(TOY, b"s" * 32), bdlop.sample_randomness(TOY, b"s" * 32)
    )


def test_mask_seed_must_have_the_fixed_entropy_width() -> None:
    _, randomness, commitment = _committed()
    for seed in (b"m" * 31, b"m" * 33, "m" * 32):
        with pytest.raises(ValueError):
            opening_proof.prove_with_stats(
                TOY, STATEMENT, commitment, randomness, mask_seed=seed  # type: ignore[arg-type]
            )
    # The entropy is hashed without a length prefix, so its width must be fixed.
    with pytest.raises(ValueError):
        opening_proof.hedged_mask_key(b"e" * 31, STATEMENT, randomness)


def _malformed_commitments(commitment: bdlop.Commitment) -> list[object]:
    t1, t2 = commitment.t1, commitment.t2
    return [
        None, "commitment", (t1, t2),
        bdlop.Commitment(t1.reshape(-1), t2),  # used to raise inside verify
        bdlop.Commitment(np.concatenate([t1, t1]), t2),  # broadcastable extra row
        bdlop.Commitment(t1, t2[:-1]),
        bdlop.Commitment(t1.astype(np.float64), t2),
        bdlop.Commitment(t1, np.full_like(t2, TOY.modulus)),  # fits the bit width, not reduced
        bdlop.Commitment(t1, t2 - TOY.modulus),  # congruent but negative
        bdlop.Commitment(t1.tolist(), t2),  # type: ignore[arg-type]
    ]


def test_non_canonical_commitments_are_refused_everywhere() -> None:
    message, randomness, commitment = _committed()
    proof = opening_proof.prove(TOY, STATEMENT, commitment, randomness)
    for malformed in _malformed_commitments(commitment):
        assert opening_proof.verify(TOY, STATEMENT, malformed, proof) is False  # type: ignore[arg-type]
        assert bdlop.verify_opening(TOY, malformed, message, randomness) is False  # type: ignore[arg-type]
        with pytest.raises((TypeError, ValueError)):
            opening_proof.prove(TOY, STATEMENT, malformed, randomness)  # type: ignore[arg-type]
        if isinstance(malformed, bdlop.Commitment):
            assert not malformed.is_canonical(TOY)
            with pytest.raises((TypeError, ValueError)):
                malformed.to_bytes(TOY)
    assert commitment.is_canonical(TOY)


def test_verify_opening_never_raises_on_malformed_witness() -> None:
    message, randomness, commitment = _committed()
    for bad_message, bad_randomness in (
        (message, randomness.tolist()), (message, None), (message.tolist(), randomness),
        (message, randomness.astype(np.float64)), (None, randomness), (message[:3], randomness),
    ):
        assert bdlop.verify_opening(TOY, commitment, bad_message, bad_randomness) is False


def test_packed_fields_must_be_bytes() -> None:
    _, _, commitment = _committed()
    encoded = commitment.to_bytes(TOY)
    with pytest.raises(TypeError):
        bdlop.Commitment.from_bytes(TOY, bytearray(encoded))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        codec.unpack_uints("00", 1, 8, 256)  # type: ignore[arg-type]


# -- randomized properties ------------------------------------------------ #

def test_random_valid_statements_always_verify() -> None:
    rng = random.Random(0x5EED0001)
    for _ in range(25):
        payload = rng.randbytes(rng.randrange(TOY.max_payload_bytes + 1))
        statement = rng.randbytes(rng.randrange(300))
        message = codec.encode_payload(TOY, payload)
        randomness = bdlop.sample_randomness(TOY, rng.randbytes(32))
        commitment = bdlop.commit(TOY, message, randomness)
        restored = bdlop.Commitment.from_bytes(TOY, commitment.to_bytes(TOY))
        proof = opening_proof.prove_with_stats(
            TOY, statement, commitment, randomness, mask_seed=rng.randbytes(32)
        ).proof
        assert opening_proof.verify(TOY, statement, restored, proof)
        assert bdlop.verify_opening(TOY, restored, message, randomness)
        assert codec.decode_payload(TOY, message) == payload
        other = rng.randbytes(rng.randrange(300))
        assert other == statement or not opening_proof.verify(TOY, other, restored, proof)


def test_random_proof_corruptions_never_verify() -> None:
    rng = random.Random(0x5EED0002)
    _, randomness, commitment = _committed()
    proof = opening_proof.prove(TOY, STATEMENT, commitment, randomness)
    for corrupted in random_corruptions(proof, rng, 400):
        assert opening_proof.verify(TOY, STATEMENT, commitment, corrupted) is False


def test_random_commitment_corruptions_are_rejected_or_do_not_verify() -> None:
    rng = random.Random(0x5EED0003)
    _, randomness, commitment = _committed()
    proof = opening_proof.prove(TOY, STATEMENT, commitment, randomness)
    for corrupted in random_corruptions(commitment.to_bytes(TOY), rng, 300):
        try:
            parsed = bdlop.Commitment.from_bytes(TOY, corrupted)
        except ValueError:
            continue
        assert parsed.to_bytes(TOY) == corrupted  # decoding is canonical: one encoding per value
        assert not opening_proof.verify(TOY, STATEMENT, parsed, proof)


def test_random_packed_fields_round_trip_and_decode_canonically() -> None:
    rng = random.Random(0x5EED0004)
    for _ in range(200):
        bits, count = rng.randint(1, 62), rng.randint(0, 40)
        bound = rng.randint(1, 1 << bits)
        values = np.array([rng.randrange(bound) for _ in range(count)], dtype=np.int64)
        packed = codec.pack_uints(values, bits)
        assert np.array_equal(codec.unpack_uints(packed, count, bits, bound), values)
        garbage = rng.randbytes(len(packed))
        try:
            decoded = codec.unpack_uints(garbage, count, bits, bound)
        except ValueError:
            continue
        assert codec.pack_uints(decoded, bits) == garbage


def test_decodable_messages_are_exactly_the_encoder_image() -> None:
    rng = random.Random(0x5EED0005)
    width_bits = 8 * TOY.payload_bytes_per_coefficient
    decoded_any = False
    for _ in range(300):
        message = codec.encode_payload(TOY, rng.randbytes(rng.randrange(TOY.max_payload_bytes + 1)))
        message[rng.randrange(TOY.degree)] = rng.randrange(1 << (width_bits + 1))
        try:
            payload = codec.decode_payload(TOY, message)
        except ValueError:
            continue
        decoded_any = True
        assert np.array_equal(codec.encode_payload(TOY, payload), message)
    assert decoded_any
