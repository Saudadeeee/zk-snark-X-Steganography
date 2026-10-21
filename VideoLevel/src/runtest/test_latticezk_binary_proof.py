"""Binary-message proof for BDLOP commitments (roadmap B2)."""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import math
import random

import numpy as np
import pytest

from src.lattice_zk import binary_proof as bp
from src.lattice_zk import bdlop, codec, equality_proof, fast_ring, opening_proof, ring
from src.lattice_zk.params import BDLOP_OPEN_128, TOY
from src.runtest.test_latticezk_bdlop import random_corruptions

STATEMENT = b"binary statement"
P = bp.BINARY_TOY
Q = P.modulus


def _seed(label: str) -> bytes:
    return hashlib.sha3_256(("zkstego/lattice-zk/kat/binary/v1/" + label).encode("ascii")).digest()


def _kat_message(params: bp.BinaryParams) -> bytes:
    return bytes((7 * index + 3) % 256 for index in range(params.message_bytes))


def _setup(params: bp.BinaryParams = P, data: bytes | None = None, seed: bytes = b"\x01" * 32):
    data = _kat_message(params) if data is None else data
    message = bp.encode_bits(params, data)
    randomness = bp.sample_randomness(params, seed)
    return message, randomness, bp.commit(params, message, randomness)


@pytest.fixture(scope="module")
def toy_proof():
    message, randomness, commitment = _setup()
    proof = bp.prove(P, STATEMENT, commitment, message, randomness)
    return message, randomness, commitment, proof


# ------------------------------------------------------------------ fast_ring


@pytest.mark.parametrize("q, degree", [((1 << 30) - 35, 256), (TOY.modulus, 64), (13, 8)])
def test_fast_ring_matches_the_reference_multiplication(q: int, degree: int) -> None:
    rng = np.random.default_rng(degree)
    extremes = np.full(degree, q - 1, dtype=np.int64)
    for trial in range(12):
        a = extremes if trial == 0 else rng.integers(0, q, degree)
        b = extremes if trial < 2 else rng.integers(0, q, degree)
        assert np.array_equal(fast_ring.mul(a, b, q), ring.poly_mul(a, b, q))
    matrix = rng.integers(0, q, (3, 5, degree))
    matrix[0] = q - 1
    vector = np.full((5, degree), q - 1, dtype=np.int64)
    assert np.array_equal(fast_ring.matvec(matrix, vector, q), ring.mat_vec(matrix, vector, q))
    expected_dot = ring.mat_vec(matrix[:1], vector, q)[0]
    assert np.array_equal(fast_ring.dot(matrix[0], vector, q), expected_dot)
    poly = rng.integers(0, q, degree)
    assert np.array_equal(
        fast_ring.scale(poly, vector, q), np.stack([ring.poly_mul(poly, row, q) for row in vector])
    )


def test_fast_ring_rejects_unsupported_input(monkeypatch) -> None:
    q = TOY.modulus
    poly = np.zeros(64, dtype=np.int64)
    with pytest.raises(ValueError):
        fast_ring.mul(poly, poly, (1 << 31) - 1)
    with pytest.raises(ValueError):
        fast_ring.mul(poly - 1, poly, q)
    with pytest.raises(ValueError):
        fast_ring.mul(poly + q, poly, q)
    with pytest.raises(ValueError):
        fast_ring.matvec(np.zeros((2, 3, 64), dtype=np.int64), np.zeros((2, 64), dtype=np.int64), q)
    with pytest.raises(ValueError):
        fast_ring.scale(poly, poly, q)
    monkeypatch.setattr(fast_ring, "MAX_TERMS", 127)
    with pytest.raises(ValueError):
        fast_ring.matvec(np.zeros((1, 2, 64), dtype=np.int64), np.zeros((2, 64), dtype=np.int64), q)
    with pytest.raises(ValueError):
        fast_ring.scale(np.zeros(128, dtype=np.int64), np.zeros((1, 128), dtype=np.int64), q)


# ---------------------------------------------------------------------- sigma


def test_sigma_turns_the_constant_coefficient_into_an_inner_product() -> None:
    rng = np.random.default_rng(3)
    a, b, c = (rng.integers(0, Q, 64) for _ in range(3))
    assert int(ring.poly_mul(bp.sigma(a, Q), b, Q)[0]) == int(np.dot(a, b) % Q)
    assert np.array_equal(bp.sigma(bp.sigma(a, Q), Q), a)
    # sigma is a ring automorphism and an isometry of the coefficient vector.
    assert np.array_equal(bp.sigma(ring.poly_mul(a, c, Q), Q),
                          ring.poly_mul(bp.sigma(a, Q), bp.sigma(c, Q), Q))
    assert int(np.dot(bp.sigma(a, Q), bp.sigma(b, Q)) % Q) == int(np.dot(a, b) % Q)


def test_check_polynomial_constant_term_is_the_random_functional_of_the_error() -> None:
    """ct(E_t) = sum_i <rho_ti, u_i - sigma(gamma_i o m)> + mu_ti ct(u_i (m - J))."""
    rng = np.random.default_rng(5)
    message = rng.integers(0, Q, 64)
    gammas = rng.integers(0, Q, (2, 64))
    honest = bp.sigma((gammas * message) % Q, Q)
    lifts = (honest + rng.integers(0, Q, (2, 64))) % Q
    check = bp._check_challenges(P, b"\x07" * 32, gammas)
    masks = bp._masks_from(P, check, lifts, np.zeros((2, 64), dtype=np.int64), message)
    rho = bp.sigma(check.sigma_rho, Q)
    shifted = (message - 1) % Q
    defect = (message * shifted) % Q
    for i in range(2):
        # For the honest lift, ct(u_i (m - J)) = <gamma_i, m o (m - 1)>.
        assert int(ring.poly_mul(honest[i], shifted, Q)[0]) == int(np.dot(gammas[i], defect) % Q)
    for t in range(2):
        expected = 0
        for i in range(2):
            expected += int(np.dot(rho[t, i], (lifts[i] - honest[i]) % Q))
            expected += int(check.mu[t, i]) * int(ring.poly_mul(lifts[i], shifted, Q)[0])
        assert int(masks[t, 0]) == expected % Q


# ----------------------------------------------------------------- parameters


def test_parameter_sets_are_consistent() -> None:
    production = bp.BINARY_128
    assert production.base is BDLOP_OPEN_128
    assert production.aux_slots == 11 and production.aux_width == 24
    assert production.proof_bytes == 43_022
    assert production.soundness_bits > 149
    production.require_production_strength()
    with pytest.raises(ValueError):
        P.require_production_strength()
    assert set(production.round_soundness_log2) == {"lift", "check", "combine", "challenge"}
    assert bp.abort_probability_log2(production) < -256
    assert bp.abort_probability_log2(P, 1) < 0
    assert production.parameter_id != P.parameter_id
    assert production.mlwe_samples == 17
    assert len(production.parameter_id) == 32


def test_too_few_repetitions_are_not_production_strength() -> None:
    weak = dataclasses.replace(bp.BINARY_128, name="weak", lift_repetitions=4)
    assert 119 < weak.soundness_bits < 128
    with pytest.raises(ValueError):
        weak.require_production_strength()


def test_parser_checks_the_total_length_itself(toy_proof) -> None:
    proof = toy_proof[3]
    with pytest.raises(ValueError):
        bp._parse(P, proof[:-1])
    assert bp._parse(P, proof).seed == proof[P.aux_commitment_bytes + P.mask_bytes + P.garbage_bytes:][:32]


def test_abort_probability_is_minus_infinity_when_every_attempt_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(bp.BinaryParams, "acceptance_probability", property(lambda self: 1.0))
    assert bp.abort_probability_log2(P) == -math.inf


@pytest.mark.parametrize("change", [
    {"name": ""}, {"name": "é"}, {"name": "x" * 70_000}, {"base": "toy"},
    {"lift_repetitions": 0}, {"check_repetitions": 65}, {"lift_repetitions": True},
    {"setup_seed": b"short"},
])
def test_parameter_validation(change: dict) -> None:
    with pytest.raises((TypeError, ValueError)):
        dataclasses.replace(P, **change)


def test_parameters_need_a_fast_ring_modulus_and_byte_aligned_degree() -> None:
    modulus = next(value for value in range((1 << 30) + 5, 1 << 31, 8) if ring._is_prime(value))
    big = dataclasses.replace(TOY, name="big-q", modulus=modulus)
    with pytest.raises(ValueError):
        dataclasses.replace(P, base=big)
    odd = dataclasses.replace(TOY, name="tiny", degree=4, challenge_weight=2, mask_bound=1 << 6)
    with pytest.raises(ValueError):
        dataclasses.replace(P, base=odd)


# -------------------------------------------------------------------- messages


def test_bit_encoding_round_trips_and_is_strict() -> None:
    data = bytes(range(8))
    message = bp.encode_bits(P, data)
    assert set(np.unique(message)) <= {0, 1}
    assert int(message[15]) == 1 and int(message[:15].sum()) == 0  # MSB first: bytes 00 01
    assert bp.decode_bits(P, message) == data
    for bad in (b"", bytes(9), "x" * 8):
        with pytest.raises(ValueError):
            bp.encode_bits(P, bad)
    with pytest.raises(ValueError):
        bp.decode_bits(P, np.full(64, 2, dtype=np.int64))
    with pytest.raises(ValueError):
        bp.binary_message(P, np.full(64, -1, dtype=np.int64))
    with pytest.raises(TypeError):
        bp.binary_message(P, [0] * 64)


# ----------------------------------------------------------------- completeness


@pytest.mark.parametrize("data", [bytes(8), b"\xff" * 8, bytes(range(1, 9)), b"\x80\x01\xaa\x55\x00\xff\x0f\xf0"])
def test_toy_completeness(data: bytes) -> None:
    message, randomness, commitment = _setup(data=data)
    result = bp.prove_with_stats(P, STATEMENT, commitment, message, randomness)
    assert len(result.proof) == P.proof_bytes
    assert 1 <= result.attempts <= bp.MAX_ATTEMPTS
    assert bp.verify(P, STATEMENT, commitment, result.proof)


def test_binary_commitment_stays_compatible_with_the_base_proofs(toy_proof) -> None:
    message, randomness, commitment, proof = toy_proof
    opening = opening_proof.prove(TOY, STATEMENT, commitment, randomness)
    assert opening_proof.verify(TOY, STATEMENT, commitment, opening)
    public = bdlop.commit(TOY, message, np.zeros((TOY.width, TOY.degree), dtype=np.int64))
    equal = equality_proof.prove(
        TOY, STATEMENT, commitment, randomness, public, np.zeros((TOY.width, TOY.degree), dtype=np.int64)
    )
    assert equality_proof.verify(TOY, STATEMENT, commitment, public, equal)
    assert bp.verify(P, STATEMENT, commitment, proof)


def test_repeated_proofs_use_fresh_auxiliary_commitments(toy_proof) -> None:
    message, randomness, commitment, proof = toy_proof
    again = bp.prove(P, STATEMENT, commitment, message, randomness)
    assert again != proof and bp.verify(P, STATEMENT, commitment, again)
    width = P.aux_commitment_bytes
    assert again[:width] != proof[:width]


def test_explicit_mask_seed_is_deterministic(toy_proof) -> None:
    message, randomness, commitment, _ = toy_proof
    first = bp.prove_with_stats(P, STATEMENT, commitment, message, randomness, mask_seed=b"\x05" * 32)
    second = bp.prove_with_stats(P, STATEMENT, commitment, message, randomness, mask_seed=b"\x05" * 32)
    other = bp.prove_with_stats(P, STATEMENT, commitment, message, randomness, mask_seed=b"\x06" * 32)
    assert first == second and first.proof != other.proof
    assert bp.verify(P, STATEMENT, commitment, other.proof)
    with pytest.raises(ValueError):
        bp.prove_with_stats(P, STATEMENT, commitment, message, randomness, mask_seed=b"\x05" * 31)


# Known-answer vectors: SHA-256 of the commitment and of the proof bytes.
KAT = {
    "bdlop-binary-toy-v1": (
        "0d5e22ce9b3c581f5727c3ce2abcbeb3f198f6e2f1700fce5b851d7289fef818",
        "6048b6b2d3095c5a0a1cb9515de3e4f98663b7cddc61a4163df3e8aa0cadfee3",
        "80c3d543228e5256b051783f2f0ee7684e7a09645cf2169e9a0e1066afc43620",
        24,
    ),
    "bdlop-binary-128-v2": (
        "1fc36ad8f392b1119c28b7c714b7cf31cb82ebf7033ede8860aeb1ca000379ca",
        "cd4019d75376125df72e7093fb15c4b7cca9b7615ce88404934dc64bf4db3357",
        "dd809cf28126d1c18c86bb8df6ede12e9b4325ba584f1d8681e3fd48a644ea65",
        115,
    ),
}


@functools.lru_cache(maxsize=2)
def _kat(params: bp.BinaryParams):
    message, randomness, commitment = _setup(params, seed=_seed("randomness/" + params.name))
    result = bp.prove_with_stats(
        params, b"kat statement", commitment, message, randomness, mask_seed=_seed("mask/" + params.name)
    )
    return commitment, result


@pytest.mark.parametrize("params", [bp.BINARY_TOY, bp.BINARY_128], ids=lambda p: p.name)
def test_known_answer_vector(params: bp.BinaryParams) -> None:
    """Production-sized completeness plus a pinned, platform-independent proof."""
    parameter_id, commitment_digest, proof_digest, attempts = KAT[params.name]
    commitment, result = _kat(params)
    assert params.parameter_id.hex() == parameter_id
    assert hashlib.sha256(commitment.to_bytes(params.base)).hexdigest() == commitment_digest
    assert hashlib.sha256(result.proof).hexdigest() == proof_digest
    assert result.attempts == attempts
    assert len(result.proof) == params.proof_bytes
    assert bp.verify(params, b"kat statement", commitment, result.proof)
    assert not bp.verify(params, b"kat statement!", commitment, result.proof)


# ------------------------------------------------------------ prover refusals


def test_prover_refuses_non_binary_messages() -> None:
    randomness = bp.sample_randomness(P, b"\x02" * 32)
    for value in (2, Q - 1):
        message = np.zeros(64, dtype=np.int64)
        message[17] = value
        commitment = bp.commit(P, message, randomness)
        with pytest.raises(ValueError):
            bp.prove(P, STATEMENT, commitment, message, randomness)


def test_prover_refuses_bad_witnesses(toy_proof) -> None:
    message, randomness, commitment, _ = toy_proof
    flipped = message.copy()
    flipped[0] ^= 1
    with pytest.raises(ValueError):
        bp.prove(P, STATEMENT, commitment, flipped, randomness)
    with pytest.raises(ValueError):
        bp.prove(P, STATEMENT, commitment, message, bp.sample_randomness(P, b"\x03" * 32))
    with pytest.raises(ValueError):
        bp.prove(P, STATEMENT, commitment, message, randomness * 2)
    with pytest.raises(TypeError):
        bp.prove(P, "statement", commitment, message, randomness)
    with pytest.raises(TypeError):
        bp.prove(P, STATEMENT, (commitment.t1, commitment.t2), message, randomness)
    with pytest.raises(TypeError):
        bp.prove(TOY, STATEMENT, commitment, message, randomness)


def test_prover_cap_raises(monkeypatch, toy_proof) -> None:
    message, randomness, commitment, _ = toy_proof
    monkeypatch.setattr(bp, "MAX_ATTEMPTS", 0)
    with pytest.raises(RuntimeError):
        bp.prove(P, STATEMENT, commitment, message, randomness)


# ------------------------------------------------------- malicious provers


def _cheat(message: np.ndarray, randomness: np.ndarray, **options) -> tuple[bdlop.Commitment, bytes]:
    commitment = bp.commit(P, message % Q, randomness)
    result = bp._prove(P, STATEMENT, commitment, message % Q, randomness, b"\x09" * 32, **options)
    return commitment, result.proof


@pytest.mark.parametrize("value", [2, 3, Q - 1, (Q + 1) // 2])
def test_verifier_rejects_honestly_run_protocol_on_non_binary_message(value: int) -> None:
    message = bp.encode_bits(P, b"\x0f" * 8)
    message[5] = value
    commitment, proof = _cheat(message, bp.sample_randomness(P, b"\x04" * 32))
    assert not bp.verify(P, STATEMENT, commitment, proof)


def test_verifier_rejects_lifts_chosen_to_cancel_the_binary_defect() -> None:
    """A prover that makes every ct(u_i (m - J)) vanish must break u_i = sigma(gamma_i o m)."""
    message = bp.encode_bits(P, b"\x33" * 8)
    message[9] = 2
    shifted = (message - 1) % Q

    def cancel(lifts: np.ndarray, gammas: np.ndarray) -> np.ndarray:
        forged = lifts.copy()
        for index in range(len(forged)):
            defect = int(ring.poly_mul(forged[index], shifted, Q)[0])
            # ct(u (m - J)) = <sigma(u), m - J>; adjust sigma(u)_9 where (m - J)_9 = 1.
            fixed = bp.sigma(forged[index], Q)
            fixed[9] = (fixed[9] - defect) % Q
            forged[index] = bp.sigma(fixed, Q)
            assert int(ring.poly_mul(forged[index], shifted, Q)[0]) == 0
        return forged

    commitment, proof = _cheat(message, bp.sample_randomness(P, b"\x05" * 32), lift_override=cancel)
    assert not bp.verify(P, STATEMENT, commitment, proof)


def test_verifier_rejects_inconsistent_lifts_for_a_binary_message() -> None:
    message = bp.encode_bits(P, b"\x5a" * 8)
    commitment, proof = _cheat(
        message, bp.sample_randomness(P, b"\x06" * 32),
        lift_override=lambda lifts, gammas: (lifts + 1) % Q,
    )
    assert not bp.verify(P, STATEMENT, commitment, proof)


# --------------------------------------------------------------- verifier input


def test_wrong_statement_commitment_and_parameters_are_rejected(toy_proof) -> None:
    message, randomness, commitment, proof = toy_proof
    assert bp.verify(P, STATEMENT, commitment, proof)
    assert not bp.verify(P, STATEMENT + b"x", commitment, proof)
    assert not bp.verify(P, b"", commitment, proof)
    other = bp.commit(P, message, bp.sample_randomness(P, b"\x07" * 32))
    assert not bp.verify(P, STATEMENT, other, proof)
    flipped = message.copy()
    flipped[3] ^= 1
    assert not bp.verify(P, STATEMENT, bp.commit(P, flipped, randomness), proof)
    renamed = dataclasses.replace(P, name="bdlop-binary-toy-v1-other")
    assert renamed.proof_bytes == P.proof_bytes
    assert not bp.verify(renamed, STATEMENT, commitment, proof)
    assert not bp.verify(TOY, STATEMENT, commitment, proof)
    assert not bp.verify(bp.BINARY_128, STATEMENT, commitment, proof)


def test_malformed_inputs_return_false(toy_proof) -> None:
    _, _, commitment, proof = toy_proof
    assert not bp.verify(P, "statement", commitment, proof)
    assert not bp.verify(P, STATEMENT, commitment, bytearray(proof))
    assert not bp.verify(P, STATEMENT, (commitment.t1, commitment.t2), proof)
    wrapped = bdlop.Commitment(commitment.t1.tolist(), commitment.t2)
    assert not bp.verify(P, STATEMENT, wrapped, proof)
    unreduced = bdlop.Commitment(commitment.t1, commitment.t2.copy())
    unreduced.t2[0] += Q
    assert not bp.verify(P, STATEMENT, unreduced, proof)
    assert not bp.verify(P, STATEMENT, commitment, b"")


def test_truncated_and_extended_proofs_are_rejected(toy_proof) -> None:
    _, _, commitment, proof = toy_proof
    for candidate in (proof[:-1], proof[1:], proof + b"\x00", b"\x00" + proof, proof[: len(proof) // 2]):
        assert not bp.verify(P, STATEMENT, commitment, candidate)


def test_every_proof_field_is_authenticated(toy_proof) -> None:
    _, _, commitment, proof = toy_proof
    offsets = np.cumsum([0, P.aux_commitment_bytes, P.mask_bytes, P.garbage_bytes, 32, P.response_bytes])
    assert offsets[-1] == len(proof)
    for start, end in zip(offsets[:-1], offsets[1:]):
        for position in (int(start), int(end) - 1, (int(start) + int(end)) // 2):
            for bit in (0, 7):
                mutated = bytearray(proof)
                mutated[position] ^= 1 << bit
                assert not bp.verify(P, STATEMENT, commitment, bytes(mutated))


def test_random_corruptions_are_rejected(toy_proof) -> None:
    _, _, commitment, proof = toy_proof
    rng = random.Random(20261021)
    for corrupted in random_corruptions(proof, rng, 120):
        assert not bp.verify(P, STATEMENT, commitment, corrupted)


def _rewrite_field(proof: bytes, start: int, length: int, count: int, bits: int, index: int, value: int) -> bytes:
    field = proof[start:start + length]
    values = codec.unpack_uints(field, count, bits, 1 << bits)
    values[index] = value
    return proof[:start] + codec.pack_uints(values, bits) + proof[start + length:]


def test_out_of_range_coefficients_are_rejected(toy_proof) -> None:
    _, _, commitment, proof = toy_proof
    base = P.base
    response_start = len(proof) - P.response_bytes
    too_large = _rewrite_field(
        proof, response_start, P.response_bytes, P.response_polys * P.degree,
        base.response_bits, 11, 2 * base.response_bound + 1,
    )
    assert not bp.verify(P, STATEMENT, commitment, too_large)
    rows = (base.msis_rank + P.lift_repetitions + P.check_repetitions) * P.degree
    unreduced = _rewrite_field(proof, 0, P.aux_commitment_bytes, rows, base.modulus_bits, 3, Q)
    assert not bp.verify(P, STATEMENT, commitment, unreduced)
    garbage_start = P.aux_commitment_bytes + P.mask_bytes
    unreduced_garbage = _rewrite_field(proof, garbage_start, P.garbage_bytes, P.degree, base.modulus_bits, 0, Q + 1)
    assert not bp.verify(P, STATEMENT, commitment, unreduced_garbage)


def test_nonzero_padding_is_rejected_on_the_production_layout() -> None:
    production = bp.BINARY_128
    padding_bits = 8 * production.mask_bytes - production.check_repetitions * (production.degree - 1) * 30
    assert padding_bits == 6
    commitment, result = _kat(production)
    proof = result.proof
    last_mask_byte = production.aux_commitment_bytes + production.mask_bytes - 1
    mutated = bytearray(proof)
    mutated[last_mask_byte] |= 1
    assert not bp.verify(production, b"kat statement", commitment, bytes(mutated))
