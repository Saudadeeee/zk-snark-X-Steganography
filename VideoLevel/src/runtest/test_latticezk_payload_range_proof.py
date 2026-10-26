"""Payload range proof: the commitment hides encode_payload(p) for an L-byte p (stream C3)."""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import math
import random

import numpy as np
import pytest

from src.lattice_zk import bdlop, binary_proof, codec, opening_proof, ring, video_proof
from src.lattice_zk import payload_range_proof as pr
from src.lattice_zk.params import BDLOP_OPEN_128, TOY
from src.runtest.test_latticezk_bdlop import forged_commitment, random_corruptions

STATEMENT = b"payload range statement"
P = pr.PAYLOAD_RANGE_TOY
Q = P.modulus
ENTROPY = b"\x09" * 32


def _seed(label: str) -> bytes:
    return hashlib.sha3_256(("zkstego/lattice-zk/kat/payload-range/v1/" + label).encode("ascii")).digest()


def _payload(length: int) -> bytes:
    return bytes((7 * index + 3) % 256 for index in range(length))


def _setup(params: pr.PayloadRangeParams = P, payload: bytes | None = None, seed: bytes = b"\x01" * 32):
    payload = _payload(6) if payload is None else payload
    randomness = bdlop.sample_randomness(params.base, seed)
    commitment = bdlop.commit(params.base, codec.encode_payload(params.base, payload), randomness)
    return payload, randomness, commitment


@pytest.fixture(scope="module")
def toy_proof():
    payload, randomness, commitment = _setup()
    proof = pr.prove(P, STATEMENT, commitment, payload, randomness)
    return payload, randomness, commitment, proof


def _cheat(message: np.ndarray, bits: np.ndarray, length: int, *, seed: bytes = b"\x04" * 32, **options):
    """Run the protocol on an arbitrary (possibly false) witness."""
    randomness = bdlop.sample_randomness(TOY, seed)
    commitment = bdlop.commit(TOY, message % Q, randomness)
    result = pr._prove(P, STATEMENT, commitment, message % Q, randomness, bits, length, ENTROPY, **options)
    return commitment, result.proof


# ------------------------------------------------------------------- encoding


@pytest.mark.parametrize("params", [pr.PAYLOAD_RANGE_TOY, pr.PAYLOAD_RANGE_128], ids=lambda p: p.name)
def test_bit_decomposition_reproduces_the_payload_encoding(params: pr.PayloadRangeParams) -> None:
    rng = random.Random(params.degree)
    lengths = sorted({0, 1, 2, 3, params.degree // 8, params.degree // 8 + 1, params.max_payload_bytes})
    for length in lengths:
        for payload in (bytes(length), b"\xff" * length, rng.randbytes(length)):
            bits = pr.decompose(params, payload)
            assert bits.shape == (params.layout(length).binary_polys, params.degree)
            assert set(np.unique(bits)) <= {0, 1}
            assert np.array_equal(pr.recompose(params, length, bits), codec.encode_payload(params.base, payload))
            assert np.packbits(bits.reshape(-1).astype(np.uint8)).tobytes()[:length] == payload


def test_encoding_map_has_power_of_two_weights_on_payload_coefficients() -> None:
    encoding = pr.payload_encoding(BDLOP_OPEN_128, 32)
    assert int(encoding.offset[0]) == 32 << 8 and not encoding.offset[1:].any()
    assert encoding.index.size == 256
    assert int(encoding.index.min()) == 0 and int(encoding.index.max()) == 11  # 34 framed bytes
    assert all(int(weight) & (int(weight) - 1) == 0 for weight in encoding.weight)
    assert int(encoding.weight.max()) == 1 << 23
    # every 24-bit coefficient receives each weight at most once
    pairs = set(zip(encoding.index.tolist(), encoding.weight.tolist()))
    assert len(pairs) == encoding.index.size
    toy = pr.payload_encoding(TOY, 3)
    assert int(toy.offset[0]) == 3 and int(toy.weight.max()) == 1 << 15
    with pytest.raises(ValueError):
        toy.offset[0] = 1


def test_decompose_and_recompose_validate_input() -> None:
    with pytest.raises(TypeError):
        pr.decompose(P, "payload")
    with pytest.raises(ValueError):
        pr.decompose(P, bytes(P.max_payload_bytes + 1))
    with pytest.raises(ValueError):
        pr.recompose(P, 9, np.zeros((1, 64), dtype=np.int64))
    with pytest.raises(TypeError):
        pr.recompose(P, 1, [[0] * 64])


def test_link_functional_is_the_transpose_of_the_encoding() -> None:
    """ct(sigma(rho) m) - sum_j ct(sigma(A_j^T rho) beta_j) - <rho, e_L> = <rho, m - A beta - e_L>."""
    rng = np.random.default_rng(11)
    length = 13
    layout = P.layout(length)
    gammas = rng.integers(0, Q, (layout.lifts, 64))
    check = pr._check_challenges(P, layout, b"\x03" * 32, gammas)
    bits = rng.integers(0, Q, (layout.binary_polys, 64))
    message = rng.integers(0, Q, 64)
    rho = binary_proof.sigma(check.link_m, Q)
    for t in range(layout.checks):
        value = int(ring.poly_mul(check.link_m[t], message, Q)[0]) - int(check.link_const[t])
        for j in range(layout.binary_polys):
            value -= int(ring.poly_mul(check.link_bits[t, j], bits[j], Q)[0])
        residual = (message - pr.recompose(P, length, bits)) % Q
        assert value % Q == int(np.dot(rho[t], residual) % Q)


def test_check_polynomial_constant_term_is_the_random_functional_of_the_error() -> None:
    """ct(h_t - g_t) = sum_a <rho_ta, Delta_a> + mu_ta Q_a + <rho^L_t, m - A beta - e_L>."""
    rng = np.random.default_rng(5)
    length = 10
    layout = P.layout(length)
    k = P.lift_repetitions
    bits = rng.integers(0, Q, (layout.binary_polys, 64))
    message = rng.integers(0, Q, 64)
    gammas = rng.integers(0, Q, (layout.lifts, 64))
    honest = binary_proof.sigma((gammas * np.repeat(bits, k, axis=0)) % Q, Q)
    lifts = (honest + rng.integers(0, Q, honest.shape)) % Q
    check = pr._check_challenges(P, layout, b"\x07" * 32, gammas)
    masks = pr._masks_from(P, layout, check, lifts, np.zeros((layout.checks, 64), dtype=np.int64), bits, message)
    rho = binary_proof.sigma(check.sigma_rho, Q)
    rho_link = binary_proof.sigma(check.link_m, Q)
    residual = (message - pr.recompose(P, length, bits)) % Q
    for t in range(layout.checks):
        expected = int(np.dot(rho_link[t], residual) % Q)
        for a in range(layout.lifts):
            shifted = (bits[a // k] - 1) % Q
            expected += int(np.dot(rho[t, a], (lifts[a] - honest[a]) % Q) % Q)
            expected += int(check.mu[t, a]) * int(ring.poly_mul(lifts[a], shifted, Q)[0])
        assert int(masks[t, 0]) == expected % Q
    # The honest lift turns Q_a into <gamma_a, beta o (beta - 1)>.
    defect = (bits[0] * ((bits[0] - 1) % Q)) % Q
    assert int(ring.poly_mul(honest[0], (bits[0] - 1) % Q, Q)[0]) == int(np.dot(gammas[0], defect) % Q)


# ----------------------------------------------------------------- parameters


def test_parameter_sets_are_consistent() -> None:
    production = pr.PAYLOAD_RANGE_128
    assert production is pr.PAYLOAD_RANGE_128_V2 and production.base is BDLOP_OPEN_128
    assert production.max_payload_bytes == 128 and P.max_payload_bytes == 32
    layout = production.layout(32)
    assert (layout.binary_polys, layout.slots, layout.aux_width) == (1, 12, 26)
    assert production.proof_bytes(32) == 46_670
    assert production.proof_bytes(0) == production.proof_bytes(1) == 46_670
    assert pr.PAYLOAD_RANGE_128_V1.proof_bytes(32) == 44_558
    assert production.layout(33).binary_polys == 2 and production.layout(128).binary_polys == 4
    assert production.proof_bytes(128) > production.proof_bytes(64) > production.proof_bytes(32)
    assert production.mlwe_samples(32) == 19
    assert 148.9 < production.soundness_bits < 149.1
    production.require_production_strength()
    with pytest.raises(ValueError):
        P.require_production_strength()
    assert set(production.round_soundness_log2) == {"lift", "check", "combine", "challenge"}
    # Completeness error after MAX_ATTEMPTS stays below 2^-128 at every length
    # (2^-177 at 128 bytes for the v3-based set).
    for length in (0, 32, 64, 96, 128):
        assert pr.abort_probability_log2(production, length) < -170
    assert 0.0075 < production.acceptance_probability(32) < 0.0085
    assert pr.abort_probability_log2(P, 3, 1) < 0
    assert len({production.parameter_id, P.parameter_id, binary_proof.BINARY_128.parameter_id}) == 3


def test_too_few_repetitions_are_not_production_strength() -> None:
    weak = dataclasses.replace(pr.PAYLOAD_RANGE_128, name="weak", check_repetitions=4)
    assert 119 < weak.soundness_bits < 128
    with pytest.raises(ValueError):
        weak.require_production_strength()


def test_abort_probability_is_minus_infinity_when_every_attempt_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(pr.PayloadRangeParams, "acceptance_probability", lambda self, length: 1.0)
    assert pr.abort_probability_log2(P, 1) == -math.inf


@pytest.mark.parametrize("change", [
    {"name": ""}, {"name": "é"}, {"name": "x" * 70_000}, {"base": "toy"},
    {"lift_repetitions": 0}, {"check_repetitions": 65}, {"lift_repetitions": True},
    {"max_binary_polys": 0}, {"max_binary_polys": 17}, {"setup_seed": b"short"},
])
def test_parameter_validation(change: dict) -> None:
    with pytest.raises((TypeError, ValueError)):
        dataclasses.replace(P, **change)


def test_parameters_need_a_fast_ring_modulus_byte_aligned_degree_and_payload_room() -> None:
    modulus = next(value for value in range((1 << 30) + 5, 1 << 31, 8) if ring._is_prime(value))
    with pytest.raises(ValueError):
        dataclasses.replace(P, base=dataclasses.replace(TOY, name="big-q", modulus=modulus))
    with pytest.raises(ValueError):
        dataclasses.replace(P, base=dataclasses.replace(
            TOY, name="tiny", degree=4, challenge_weight=2, mask_bound=1 << 6))
    small = next(value for value in range(12_000, 1 << 16) if value % 8 == 5 and ring._is_prime(value))
    narrow = dataclasses.replace(TOY, name="narrow", modulus=small, mask_bound=1 << 5, challenge_weight=4)
    assert narrow.payload_bytes_per_coefficient == 1
    dataclasses.replace(P, base=narrow)
    tiny_q = next(value for value in range(200, 256) if value % 8 == 5 and ring._is_prime(value))
    with pytest.raises(ValueError):
        dataclasses.replace(P, base=dataclasses.replace(
            TOY, name="no-room", modulus=tiny_q, degree=8, mask_bound=1 << 2, challenge_weight=1))


@pytest.mark.parametrize("length", [-1, 33, True, "3", 2.0])
def test_layout_rejects_bad_lengths(length) -> None:
    with pytest.raises(ValueError):
        P.layout(length)


def test_auxiliary_keys_depend_on_the_number_of_bit_polynomials() -> None:
    one, two = pr.derive_aux_key(P, 1), pr.derive_aux_key(P, 2)
    assert one is pr.derive_aux_key(P, 1)
    assert one.rows.shape == (1 + 6, 8, 64) and two.rows.shape == (1 + 9, 11, 64)
    assert not np.array_equal(one.rows[0, 1], two.rows[0, 1])
    assert not one.rows.flags.writeable
    for bad in (0, 5, True, 1.0):
        with pytest.raises(ValueError):
            pr.derive_aux_key(P, bad)


# ----------------------------------------------------------------- completeness


@pytest.mark.parametrize("length", [0, 1, 7, 8, 9, 20, 32])
def test_toy_completeness(length: int) -> None:
    payload, randomness, commitment = _setup(payload=_payload(length))
    result = pr.prove_with_stats(P, STATEMENT, commitment, payload, randomness)
    assert len(result.proof) == P.proof_bytes(length)
    assert 1 <= result.attempts <= pr.MAX_ATTEMPTS
    assert pr.verify(P, STATEMENT, commitment, length, result.proof)
    for other in {max(length - 1, 0), length + 1} - {length}:
        if other <= P.max_payload_bytes:
            assert not pr.verify(P, STATEMENT, commitment, other, result.proof)


def test_production_completeness_with_two_bit_polynomials() -> None:
    production = pr.PAYLOAD_RANGE_128
    payload, randomness, commitment = _setup(production, _payload(40), _seed("randomness/" + production.name))
    result = pr.prove_with_stats(  # deterministic: this seed needs 892 attempts
        production, b"kat statement", commitment, payload, randomness,
        mask_seed=_seed(f"mask/{production.name}/40/2"),
    )
    assert result.attempts == 892 and len(result.proof) == production.proof_bytes(40)
    assert pr.verify(production, b"kat statement", commitment, 40, result.proof)
    assert not pr.verify(production, b"kat statement", commitment, 41, result.proof)


def test_payload_commitment_stays_compatible_with_disclosure_and_opening(toy_proof) -> None:
    payload, randomness, commitment, proof = toy_proof
    opening = opening_proof.prove(TOY, STATEMENT, commitment, randomness)
    assert opening_proof.verify(TOY, STATEMENT, commitment, opening)
    disclosure = video_proof.create_commitment_disclosure(
        TOY, commitment, video_proof.PayloadOpening(payload, randomness),
        statement_id=b"\x01" * 32, nonce=b"\x02" * 32,
    )
    assert video_proof.verify_commitment_disclosure(
        TOY, commitment, disclosure, statement_id=b"\x01" * 32, nonce=b"\x02" * 32,
        allow_toy_parameters=True,
    )
    assert video_proof.decode_disclosure(TOY, disclosure).payload == payload
    assert pr.verify(P, STATEMENT, commitment, len(payload), proof)


def test_repeated_proofs_use_fresh_auxiliary_commitments(toy_proof) -> None:
    payload, randomness, commitment, proof = toy_proof
    again = pr.prove(P, STATEMENT, commitment, payload, randomness)
    assert again != proof and pr.verify(P, STATEMENT, commitment, len(payload), again)
    first = P.proof_parts(len(payload))["aux_commitment_d0"]
    assert again[:first] != proof[:first]


def test_explicit_mask_seed_is_deterministic(toy_proof) -> None:
    payload, randomness, commitment, _ = toy_proof
    first = pr.prove_with_stats(P, STATEMENT, commitment, payload, randomness, mask_seed=b"\x05" * 32)
    second = pr.prove_with_stats(P, STATEMENT, commitment, payload, randomness, mask_seed=b"\x05" * 32)
    other = pr.prove_with_stats(P, STATEMENT, commitment, payload, randomness, mask_seed=b"\x06" * 32)
    assert first == second and first.proof != other.proof
    assert pr.verify(P, STATEMENT, commitment, len(payload), other.proof)
    with pytest.raises(ValueError):
        pr.prove_with_stats(P, STATEMENT, commitment, payload, randomness, mask_seed=b"\x05" * 31)


# Known-answer vectors: SHA-256 of the commitment and of the proof bytes, attempts.
KAT = {
    "bdlop-payload-range-toy-v1": (
        20,
        "a8f8d365c5afdca0d39aeac072dd4837bad94a7c0a153d3d983683f119111ca7",
        "dc406902eeaa050ec25aee2996a7e480fab731084d0f70ef9a1df73e4bc59f82",
        "bb084a5cd3a1e82e4a9858f6d02dd0bcd8de1992515415b9e1e5b6e3d7a92751",
        6,
    ),
    "bdlop-payload-range-128-v1": (
        32,
        "40cb8489b024556d7b35bbdb09527373b1c762bf5332d0645d06d38b327f0122",
        "f69d1efca0183cfb8e95be277e200ed896664a6fde55fa0432571211bb5a1c11",
        "bcbcdc6606965a867af72d108f5379f5f842c36ba9df7b2d5216974a34f5530d",
        41,
    ),
    "bdlop-payload-range-128-v2": (
        32,
        "be31fc9fa76f52ea1434dce2b7929da343693e5611fab03f7934bc957230cdb6",
        "8f1f355f7530770bcb30b0546304e5998c4cd1044190ca205094c0dca04c04c4",
        "20a551594a0b6d54813a77f1be35782a8986c5117fe4fc01d96487730703de66",
        204,
    ),
}


@functools.lru_cache(maxsize=3)
def _kat(params: pr.PayloadRangeParams):
    length = KAT[params.name][0]
    payload, randomness, commitment = _setup(params, _payload(length), _seed("randomness/" + params.name))
    result = pr.prove_with_stats(
        params, b"kat statement", commitment, payload, randomness,
        mask_seed=_seed(f"mask/{params.name}/{length}"),
    )
    return length, commitment, result


@pytest.mark.parametrize(
    "params", [pr.PAYLOAD_RANGE_TOY, pr.PAYLOAD_RANGE_128_V1, pr.PAYLOAD_RANGE_128],
    ids=lambda p: p.name,
)
def test_known_answer_vector(params: pr.PayloadRangeParams) -> None:
    """Production-sized completeness plus a pinned, platform-independent proof."""
    _, parameter_id, commitment_digest, proof_digest, attempts = KAT[params.name]
    length, commitment, result = _kat(params)
    assert params.parameter_id.hex() == parameter_id
    assert hashlib.sha256(commitment.to_bytes(params.base)).hexdigest() == commitment_digest
    assert hashlib.sha256(result.proof).hexdigest() == proof_digest
    assert result.attempts == attempts
    assert len(result.proof) == params.proof_bytes(length)
    assert pr.verify(params, b"kat statement", commitment, length, result.proof)
    assert not pr.verify(params, b"kat statement!", commitment, length, result.proof)


# ------------------------------------------------------------ prover refusals


def test_prover_refuses_bad_witnesses(toy_proof) -> None:
    payload, randomness, commitment, _ = toy_proof
    with pytest.raises(ValueError):
        pr.prove(P, STATEMENT, commitment, payload[:-1], randomness)
    with pytest.raises(ValueError):
        pr.prove(P, STATEMENT, commitment, bytes([payload[0] ^ 1]) + payload[1:], randomness)
    with pytest.raises(ValueError):
        pr.prove(P, STATEMENT, commitment, payload, bdlop.sample_randomness(TOY, b"\x03" * 32))
    with pytest.raises(ValueError):
        pr.prove(P, STATEMENT, commitment, payload, randomness * 2)
    with pytest.raises(ValueError):
        pr.prove(P, STATEMENT, commitment, bytes(P.max_payload_bytes + 1), randomness)
    with pytest.raises(TypeError):
        pr.prove(P, STATEMENT, commitment, list(payload), randomness)
    with pytest.raises(TypeError):
        pr.prove(P, "statement", commitment, payload, randomness)
    with pytest.raises(TypeError):
        pr.prove(P, STATEMENT, (commitment.t1, commitment.t2), payload, randomness)
    with pytest.raises(TypeError):
        pr.prove(TOY, STATEMENT, commitment, payload, randomness)
    with pytest.raises(TypeError):
        pr.prove(binary_proof.BINARY_TOY, STATEMENT, commitment, payload, randomness)


def test_prover_refuses_a_commitment_outside_the_encoder_image() -> None:
    message = codec.encode_payload(TOY, _payload(4))
    message[30] = 1  # nonzero padding: no payload of any length encodes to this
    randomness = bdlop.sample_randomness(TOY, b"\x02" * 32)
    commitment = bdlop.commit(TOY, message, randomness)
    with pytest.raises(ValueError):
        pr.prove(P, STATEMENT, commitment, _payload(4), randomness)


def test_prover_cap_raises(monkeypatch, toy_proof) -> None:
    payload, randomness, commitment, _ = toy_proof
    monkeypatch.setattr(pr, "MAX_ATTEMPTS", 0)
    with pytest.raises(RuntimeError):
        pr.prove(P, STATEMENT, commitment, payload, randomness)


# ------------------------------------------------------- malicious provers


def test_honest_internal_run_is_accepted() -> None:
    payload = _payload(6)
    commitment, proof = _cheat(codec.encode_payload(TOY, payload), pr.decompose(P, payload), 6)
    assert pr.verify(P, STATEMENT, commitment, 6, proof)


@pytest.mark.parametrize("position, value", [(0, 2), (1, 4), (17, Q - 1), (47, (Q + 1) // 2)])
def test_out_of_range_coefficient_with_consistent_decomposition_is_rejected(position: int, value: int) -> None:
    """m = e_L + A beta holds exactly, but beta is not binary and a coefficient leaves [0, 2^16)."""
    bits = pr.decompose(P, _payload(6))
    bits[0, position] = value
    message = pr.recompose(P, 6, bits)
    assert int(message.max()) >= 1 << (8 * TOY.payload_bytes_per_coefficient)
    commitment, proof = _cheat(message, bits, 6)
    assert not pr.verify(P, STATEMENT, commitment, 6, proof)


def test_coefficient_one_past_the_range_is_rejected() -> None:
    """Coefficient 2^16 + c with the honest bits of c: the decomposition is inconsistent."""
    payload = _payload(6)
    message = codec.encode_payload(TOY, payload)
    message[1] += 1 << 16
    commitment, proof = _cheat(message, pr.decompose(P, payload), 6)
    assert not pr.verify(P, STATEMENT, commitment, 6, proof)


def test_inconsistent_decomposition_is_rejected() -> None:
    """beta is binary but encodes another payload than the committed one."""
    message = codec.encode_payload(TOY, _payload(6))
    other = pr.decompose(P, bytes(range(20, 26)))
    commitment, proof = _cheat(message, other, 6)
    assert not pr.verify(P, STATEMENT, commitment, 6, proof)


def test_nonzero_coefficient_beyond_the_encoding_is_rejected() -> None:
    payload = _payload(6)
    message = codec.encode_payload(TOY, payload)
    message[40] = 1
    commitment, proof = _cheat(message, pr.decompose(P, payload), 6)
    assert not pr.verify(P, STATEMENT, commitment, 6, proof)


def test_wrong_length_field_is_rejected() -> None:
    payload = _payload(6)
    message = codec.encode_payload(TOY, payload + b"\x00")  # length field 7, same bits
    commitment, proof = _cheat(message, pr.decompose(P, payload), 6)
    assert not pr.verify(P, STATEMENT, commitment, 6, proof)
    assert not pr.verify(P, STATEMENT, commitment, 7, proof)


def test_lifts_chosen_to_cancel_the_binary_defect_are_rejected() -> None:
    """Make every ct(u_a (beta_j - J)) vanish for a non-binary beta; u_a is then inconsistent."""
    bits = pr.decompose(P, _payload(6))
    bits[0, 9] = 2
    message = pr.recompose(P, 6, bits)
    shifted = (bits[0] - 1) % Q

    def cancel(lifts: np.ndarray, gammas: np.ndarray) -> np.ndarray:
        forged = lifts.copy()
        for index in range(len(forged)):
            defect = int(ring.poly_mul(forged[index], shifted, Q)[0])
            fixed = binary_proof.sigma(forged[index], Q)
            fixed[9] = (fixed[9] - defect) % Q  # (beta - J)_9 = 1
            forged[index] = binary_proof.sigma(fixed, Q)
            assert int(ring.poly_mul(forged[index], shifted, Q)[0]) == 0
        return forged

    commitment, proof = _cheat(message, bits, 6, lift_override=cancel)
    assert not pr.verify(P, STATEMENT, commitment, 6, proof)


def test_inconsistent_lifts_for_an_honest_witness_are_rejected() -> None:
    payload = _payload(6)
    commitment, proof = _cheat(
        codec.encode_payload(TOY, payload), pr.decompose(P, payload), 6,
        lift_override=lambda lifts, gammas: (lifts + 1) % Q,
    )
    assert not pr.verify(P, STATEMENT, commitment, 6, proof)


# --------------------------------------------------------------- verifier input


def test_wrong_statement_commitment_length_and_parameters_are_rejected(toy_proof) -> None:
    payload, randomness, commitment, proof = toy_proof
    length = len(payload)
    assert pr.verify(P, STATEMENT, commitment, length, proof)
    assert not pr.verify(P, STATEMENT + b"x", commitment, length, proof)
    assert not pr.verify(P, b"", commitment, length, proof)
    other = bdlop.commit(TOY, codec.encode_payload(TOY, payload), bdlop.sample_randomness(TOY, b"\x07" * 32))
    assert not pr.verify(P, STATEMENT, other, length, proof)
    changed = bdlop.commit(TOY, codec.encode_payload(TOY, payload[::-1]), randomness)
    assert not pr.verify(P, STATEMENT, changed, length, proof)
    for wrong in (length - 1, length + 1):
        assert P.proof_bytes(wrong) == len(proof)
        assert not pr.verify(P, STATEMENT, commitment, wrong, proof)
    renamed = dataclasses.replace(P, name="bdlop-payload-range-toy-v1-other")
    assert not pr.verify(renamed, STATEMENT, commitment, length, proof)
    assert not pr.verify(TOY, STATEMENT, commitment, length, proof)
    assert not pr.verify(binary_proof.BINARY_TOY, STATEMENT, commitment, length, proof)
    assert not pr.verify(pr.PAYLOAD_RANGE_128, STATEMENT, commitment, length, proof)


def test_binary_proof_bytes_are_not_a_payload_proof(toy_proof) -> None:
    payload, randomness, commitment, _ = toy_proof
    message = binary_proof.encode_bits(binary_proof.BINARY_TOY, bytes(8))
    binary_commitment = binary_proof.commit(binary_proof.BINARY_TOY, message, randomness)
    proof = binary_proof.prove(binary_proof.BINARY_TOY, STATEMENT, binary_commitment, message, randomness)
    assert not any(pr.verify(P, STATEMENT, binary_commitment, length, proof) for length in range(33))


def test_malformed_inputs_return_false(toy_proof) -> None:
    payload, _, commitment, proof = toy_proof
    length = len(payload)
    assert not pr.verify(P, "statement", commitment, length, proof)
    assert not pr.verify(P, STATEMENT, commitment, length, bytearray(proof))
    assert not pr.verify(P, STATEMENT, (commitment.t1, commitment.t2), length, proof)
    # Objects built around the validating constructor (defence in depth).
    listed = forged_commitment(commitment.t1.tolist(), commitment.t2, P.base)
    assert not pr.verify(P, STATEMENT, listed, length, proof)
    raised = commitment.t2.copy()
    raised[0] += Q
    unreduced = forged_commitment(commitment.t1, raised, P.base)
    assert not pr.verify(P, STATEMENT, unreduced, length, proof)
    assert not pr.verify(P, STATEMENT, commitment, length, b"")
    for bad_length in (-1, P.max_payload_bytes + 1, True, "6", None):
        assert not pr.verify(P, STATEMENT, commitment, bad_length, proof)


def test_truncated_and_extended_proofs_are_rejected(toy_proof) -> None:
    payload, _, commitment, proof = toy_proof
    for candidate in (proof[:-1], proof[1:], proof + b"\x00", b"\x00" + proof, proof[: len(proof) // 2]):
        assert not pr.verify(P, STATEMENT, commitment, len(payload), candidate)
    with pytest.raises(ValueError):
        pr._parse(P, P.layout(len(payload)), proof[:-1])


def test_every_proof_field_is_authenticated(toy_proof) -> None:
    payload, _, commitment, proof = toy_proof
    offsets = np.cumsum([0, *P.proof_parts(len(payload)).values()])
    assert offsets[-1] == len(proof)
    for start, end in zip(offsets[:-1], offsets[1:]):
        for position in (int(start), int(end) - 1, (int(start) + int(end)) // 2):
            for bit in (0, 7):
                mutated = bytearray(proof)
                mutated[position] ^= 1 << bit
                assert not pr.verify(P, STATEMENT, commitment, len(payload), bytes(mutated))


def test_random_corruptions_are_rejected(toy_proof) -> None:
    payload, _, commitment, proof = toy_proof
    rng = random.Random(20261021)
    for corrupted in random_corruptions(proof, rng, 120):
        assert not pr.verify(P, STATEMENT, commitment, len(payload), corrupted)


def _rewrite_field(proof: bytes, start: int, length: int, count: int, bits: int, index: int, value: int) -> bytes:
    field = proof[start:start + length]
    values = codec.unpack_uints(field, count, bits, 1 << bits)
    values[index] = value
    return proof[:start] + codec.pack_uints(values, bits) + proof[start + length:]


def test_out_of_range_proof_coefficients_are_rejected(toy_proof) -> None:
    payload, _, commitment, proof = toy_proof
    length, base = len(payload), P.base
    parts, layout = P.proof_parts(length), P.layout(length)
    response_start = len(proof) - parts["responses_z_z_aux"]
    too_large = _rewrite_field(
        proof, response_start, parts["responses_z_z_aux"], (base.width + layout.aux_width) * P.degree,
        base.response_bits, 11, 2 * base.response_bound + 1,
    )
    assert not pr.verify(P, STATEMENT, commitment, length, too_large)
    first = _rewrite_field(proof, 0, parts["aux_commitment_d0"], layout.first_rows * P.degree,
                           base.modulus_bits, 3, Q)
    assert not pr.verify(P, STATEMENT, commitment, length, first)
    second_start = parts["aux_commitment_d0"]
    second = _rewrite_field(proof, second_start, parts["aux_commitment_d1"], layout.second_rows * P.degree,
                            base.modulus_bits, 0, Q + 1)
    assert not pr.verify(P, STATEMENT, commitment, length, second)


def test_nonzero_padding_is_rejected_on_the_production_layout() -> None:
    production = pr.PAYLOAD_RANGE_128
    length, commitment, result = _kat(production)
    parts = production.proof_parts(length)
    padding_bits = 8 * parts["masks_h"] - production.check_repetitions * (production.degree - 1) * 30
    assert padding_bits == 6
    last_mask_byte = parts["aux_commitment_d0"] + parts["aux_commitment_d1"] + parts["masks_h"] - 1
    mutated = bytearray(result.proof)
    mutated[last_mask_byte] |= 1
    assert not pr.verify(production, b"kat statement", commitment, length, bytes(mutated))
