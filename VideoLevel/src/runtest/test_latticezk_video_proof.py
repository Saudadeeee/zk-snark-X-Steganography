"""Video statement binding and fixed-size envelope for the BDLOP backend."""

from __future__ import annotations

import dataclasses
import random

import pytest

from src.lattice_zk import equality_proof, video_proof
from src.lattice_zk.params import BDLOP_OPEN_128, TOY
from src.runtest.test_latticezk_bdlop import random_corruptions

PINS = video_proof.VerifierPins(
    relation_id=b"R" * 32,
    registry_root=b"G" * 32,
    registry_epoch=7,
    codec_policy_id=b"C" * 32,
    carrier_profile_id=b"P" * 32,
)
SESSION = b"S" * 32
NONCE = b"N" * 32


def _statement(**overrides) -> video_proof.VideoStatement:
    arguments = {
        "carrier_count": 1_000,
        "positions_hash": b"H" * 32,
        "canonical_video_sha256": b"V" * 32,
    }
    session = overrides.pop("session_challenge", SESSION)
    pins = overrides.pop("pins", PINS)
    arguments.update(overrides)
    return video_proof.build_statement(TOY, pins, session, **arguments)


def test_statement_encoding_is_fixed_width_and_injective_per_field() -> None:
    base = _statement()
    assert len(base.to_bytes()) == 2 + 8 * 32 + 2 * 8
    variants = [
        _statement(session_challenge=b"T" * 32),
        _statement(carrier_count=1_001),
        _statement(positions_hash=b"I" * 32),
        _statement(canonical_video_sha256=b"W" * 32),
        *(
            _statement(pins=dataclasses.replace(PINS, **{field: value}))
            for field, value in (
                ("relation_id", b"r" * 32), ("registry_root", b"g" * 32), ("registry_epoch", 8),
                ("codec_policy_id", b"c" * 32), ("carrier_profile_id", b"p" * 32),
            )
        ),
        video_proof.build_statement(
            BDLOP_OPEN_128, PINS, SESSION, carrier_count=1_000,
            positions_hash=b"H" * 32, canonical_video_sha256=b"V" * 32,
        ),
    ]
    encodings = {base.to_bytes(), *(variant.to_bytes() for variant in variants)}
    assert len(encodings) == len(variants) + 1
    assert base.statement_id != variants[0].statement_id
    assert base.video_commitment != b"V" * 32  # domain separated


def test_statement_rejects_malformed_fields() -> None:
    with pytest.raises(ValueError):
        _statement(session_challenge=b"short")
    with pytest.raises(ValueError):
        _statement(carrier_count=-1)
    with pytest.raises(ValueError):
        _statement(carrier_count=True)
    with pytest.raises(ValueError):
        _statement(canonical_video_sha256=b"x")


def test_envelope_round_trip_verifies_and_hides_the_payload() -> None:
    statement = _statement()
    payload = b"secret provenance record"
    data, opening = video_proof.create_envelope(TOY, statement, payload)
    assert len(data) == video_proof.envelope_size(TOY) == len(video_proof.placeholder_envelope(TOY))
    assert video_proof.verify_envelope(TOY, statement, data)
    assert payload not in data
    assert video_proof.self_check_opening(TOY, data, opening)
    forged = dataclasses.replace(opening, payload=b"another record")
    assert not video_proof.self_check_opening(TOY, data, forged)


@pytest.mark.parametrize(
    "changed",
    [
        {"session_challenge": b"T" * 32},
        {"carrier_count": 999},
        {"positions_hash": b"I" * 32},
        {"canonical_video_sha256": b"W" * 32},
        {"pins": dataclasses.replace(PINS, relation_id=b"r" * 32)},
        {"pins": dataclasses.replace(PINS, registry_root=b"g" * 32)},
        {"pins": dataclasses.replace(PINS, registry_epoch=8)},
        {"pins": dataclasses.replace(PINS, codec_policy_id=b"c" * 32)},
        {"pins": dataclasses.replace(PINS, carrier_profile_id=b"p" * 32)},
    ],
)
def test_envelope_is_rejected_under_any_other_statement(changed: dict) -> None:
    data, _ = video_proof.create_envelope(TOY, _statement(), b"payload")
    assert not video_proof.verify_envelope(TOY, _statement(**changed), data)


def test_envelope_rejects_tampering_and_malformed_framing() -> None:
    statement = _statement()
    data, _ = video_proof.create_envelope(TOY, statement, b"payload")
    size = len(data)
    for offset in (0, 4, 5, 37, 69, 69 + TOY.commitment_bytes, size - 1):
        mutated = bytearray(data)
        mutated[offset] ^= 0x01
        assert not video_proof.verify_envelope(TOY, statement, bytes(mutated))
    assert not video_proof.verify_envelope(TOY, statement, data[:-1])
    assert not video_proof.verify_envelope(TOY, statement, data + b"\x00")
    assert not video_proof.verify_envelope(TOY, statement, video_proof.placeholder_envelope(TOY))
    with pytest.raises(ValueError):
        video_proof.decode_envelope(TOY, b"")


def test_replaying_an_envelope_in_another_session_fails() -> None:
    first = _statement()
    data, _ = video_proof.create_envelope(TOY, first, b"payload")
    replay = bytearray(data)
    replay[37:69] = b"T" * 32  # rewrite the in-band session field
    assert not video_proof.verify_envelope(TOY, _statement(session_challenge=b"T" * 32), bytes(replay))


def test_envelope_is_bound_to_the_pinned_parameter_set() -> None:
    statement = _statement()
    data, _ = video_proof.create_envelope(TOY, statement, b"payload")
    other = dataclasses.replace(TOY, name="bdlop-open-toy-v2")
    assert not video_proof.verify_envelope(other, statement, data)
    with pytest.raises(ValueError):
        video_proof.create_envelope(other, statement, b"payload")
    with pytest.raises(ValueError):
        video_proof.create_envelope(TOY, statement, b"x" * (TOY.max_payload_bytes + 1))


def test_production_envelope_has_the_registered_wire_size() -> None:
    statement = video_proof.build_statement(
        BDLOP_OPEN_128, PINS, SESSION, carrier_count=1,
        positions_hash=b"H" * 32, canonical_video_sha256=b"V" * 32,
    )
    data, opening = video_proof.create_envelope(BDLOP_OPEN_128, statement, b"p" * 100)
    assert len(data) == 14_309
    assert video_proof.verify_envelope(BDLOP_OPEN_128, statement, data)
    assert video_proof.self_check_opening(BDLOP_OPEN_128, data, opening)
    disclosure = video_proof.create_disclosure(
        BDLOP_OPEN_128, data, opening, statement_id=statement.statement_id, nonce=NONCE
    )
    assert len(disclosure) == 39 + 100 + equality_proof.proof_bytes(BDLOP_OPEN_128)
    assert video_proof.verify_disclosure_proof(
        BDLOP_OPEN_128, data, disclosure, statement_id=statement.statement_id, nonce=NONCE
    )


# -- registered-commitment (proof-only) envelope -------------------------- #

def _credential(seed: bytes = b"c" * 32):
    from src.lattice_zk import bdlop, codec

    randomness = bdlop.sample_randomness(TOY, seed)
    commitment = bdlop.commit(TOY, codec.encode_payload(TOY, b"device credential"), randomness)
    return commitment, randomness


def test_registered_envelope_carries_only_the_proof() -> None:
    statement = _statement()
    commitment, randomness = _credential()
    data = video_proof.create_registered_envelope(TOY, statement, commitment, randomness)
    assert len(data) == video_proof.envelope_size(TOY, registered=True) == 69 + TOY.proof_bytes
    assert len(data) == len(video_proof.placeholder_envelope(TOY, registered=True))
    assert video_proof.verify_registered_envelope(TOY, statement, commitment, data)
    assert video_proof.envelope_session(TOY, data, registered=True) == SESSION


def test_registered_envelope_authenticates_the_pinned_commitment() -> None:
    statement = _statement()
    commitment, randomness = _credential()
    data = video_proof.create_registered_envelope(TOY, statement, commitment, randomness)
    other_commitment, other_randomness = _credential(b"d" * 32)
    assert not video_proof.verify_registered_envelope(TOY, statement, other_commitment, data)
    with pytest.raises(ValueError):
        video_proof.create_registered_envelope(TOY, statement, commitment, other_randomness)
    impostor = video_proof.create_registered_envelope(
        TOY, statement, other_commitment, other_randomness
    )
    assert not video_proof.verify_registered_envelope(TOY, statement, commitment, impostor)
    assert not video_proof.verify_registered_envelope(
        TOY, _statement(session_challenge=b"T" * 32), commitment, data
    )
    assert not video_proof.verify_registered_envelope(
        TOY, _statement(canonical_video_sha256=b"W" * 32), commitment, data
    )


def test_envelope_kinds_are_not_interchangeable() -> None:
    statement = _statement()
    commitment, randomness = _credential()
    registered = video_proof.create_registered_envelope(TOY, statement, commitment, randomness)
    in_band, _ = video_proof.create_envelope(TOY, statement, b"payload")
    assert not video_proof.verify_envelope(TOY, statement, registered)
    assert not video_proof.verify_registered_envelope(TOY, statement, commitment, in_band)
    relabelled = b"ZKLB" + registered[4:]
    assert not video_proof.verify_registered_envelope(TOY, statement, commitment, relabelled)
    with pytest.raises(ValueError):
        video_proof.envelope_session(TOY, registered[:-1], registered=True)


# -- input validation and randomized tampering ---------------------------- #

@pytest.mark.parametrize(
    "changes",
    [
        {"relation_id": b"r" * 31}, {"registry_root": "g" * 32}, {"codec_policy_id": None},
        {"carrier_profile_id": b"p" * 33}, {"registry_epoch": -1}, {"registry_epoch": 1 << 64},
        {"registry_epoch": True},
    ],
)
def test_verifier_pins_reject_malformed_fields(changes: dict) -> None:
    with pytest.raises(ValueError):
        dataclasses.replace(PINS, **changes)


def test_verifiers_return_false_for_non_statement_or_non_opening_inputs() -> None:
    statement = _statement()
    data, opening = video_proof.create_envelope(TOY, statement, b"payload")
    commitment, randomness = _credential()
    registered = video_proof.create_registered_envelope(TOY, statement, commitment, randomness)
    for bogus in (None, statement.to_bytes(), dataclasses.asdict(statement)):
        assert video_proof.verify_envelope(TOY, bogus, data) is False  # type: ignore[arg-type]
        assert video_proof.verify_registered_envelope(
            TOY, bogus, commitment, registered  # type: ignore[arg-type]
        ) is False
    for bogus_commitment in (None, b"commitment", dataclasses.replace(commitment, t2=commitment.t2[:-1])):
        assert video_proof.verify_registered_envelope(
            TOY, statement, bogus_commitment, registered  # type: ignore[arg-type]
        ) is False
    for bogus_opening in (
        None, (opening.payload, opening.randomness),
        dataclasses.replace(opening, randomness=opening.randomness.tolist()),
        dataclasses.replace(opening, payload="payload"),
    ):
        assert video_proof.self_check_opening(TOY, data, bogus_opening) is False  # type: ignore[arg-type]


def test_envelope_constructors_refuse_malformed_inputs() -> None:
    statement = _statement()
    data, _ = video_proof.create_envelope(TOY, statement, b"payload")
    envelope = video_proof.decode_envelope(TOY, data)
    with pytest.raises(TypeError):
        video_proof.create_envelope(TOY, statement.to_bytes(), b"payload")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        video_proof.encode_envelope(TOY, (envelope.commitment, envelope.proof))  # type: ignore[arg-type]
    for changes in ({"session_challenge": "S" * 32}, {"session_challenge": b"S" * 31},
                    {"proof": list(envelope.proof)}, {"proof": envelope.proof[:-1]},
                    {"parameter_id": b"\x00" * 32}):
        with pytest.raises(ValueError):
            video_proof.encode_envelope(TOY, dataclasses.replace(envelope, **changes))
    assert video_proof.encode_envelope(TOY, envelope) == data


def test_random_in_band_envelope_corruptions_never_verify() -> None:
    rng = random.Random(0x5EED0021)
    statement = _statement()
    data, _ = video_proof.create_envelope(TOY, statement, b"payload")
    for corrupted in random_corruptions(data, rng, 400):
        assert video_proof.verify_envelope(TOY, statement, corrupted) is False
        try:
            video_proof.decode_envelope(TOY, corrupted)
        except ValueError:
            pass  # the only exception a malformed envelope may raise


def test_random_registered_envelope_corruptions_never_verify() -> None:
    rng = random.Random(0x5EED0022)
    statement = _statement()
    commitment, randomness = _credential()
    data = video_proof.create_registered_envelope(TOY, statement, commitment, randomness)
    for corrupted in random_corruptions(data, rng, 400):
        assert video_proof.verify_registered_envelope(TOY, statement, commitment, corrupted) is False


def test_random_garbage_never_decodes_as_an_envelope() -> None:
    rng = random.Random(0x5EED0023)
    for registered in (False, True):
        size = video_proof.envelope_size(TOY, registered=registered)
        for _ in range(100):
            garbage = rng.randbytes(rng.choice((size, rng.randrange(2 * size))))
            with pytest.raises(ValueError):
                video_proof.envelope_session(TOY, garbage, registered=registered)


def test_random_statements_verify_only_their_own_envelope() -> None:
    rng = random.Random(0x5EED0024)
    statements = [
        _statement(
            session_challenge=rng.randbytes(32), carrier_count=rng.randrange(1 << 64),
            positions_hash=rng.randbytes(32), canonical_video_sha256=rng.randbytes(32),
        )
        for _ in range(6)
    ]
    envelopes = [video_proof.create_envelope(TOY, s, rng.randbytes(40))[0] for s in statements]
    for i, statement in enumerate(statements):
        for j, data in enumerate(envelopes):
            assert video_proof.verify_envelope(TOY, statement, data) is (i == j)


# -- zero-knowledge disclosure (no randomness handed over) ----------------- #

def _disclosed(payload: bytes = b"secret provenance record"):
    statement = _statement()
    data, opening = video_proof.create_envelope(TOY, statement, payload)
    disclosure = video_proof.create_disclosure(
        TOY, data, opening, statement_id=statement.statement_id, nonce=NONCE
    )
    return statement, data, opening, disclosure


def _accepts(data: bytes, disclosure: bytes, statement_id: bytes, nonce: bytes = NONCE) -> bool:
    return video_proof.verify_disclosure_proof(
        TOY, data, disclosure, statement_id=statement_id, nonce=nonce
    )


def test_disclosure_reveals_the_payload_and_verifies() -> None:
    statement, data, _, disclosure = _disclosed()
    assert _accepts(data, disclosure, statement.statement_id)
    decoded = video_proof.decode_disclosure(TOY, disclosure)
    assert decoded.payload == b"secret provenance record"
    assert video_proof.encode_disclosure(TOY, decoded) == disclosure


def test_disclosure_does_not_contain_the_randomness() -> None:
    _, _, opening, disclosure = _disclosed()
    decoded = video_proof.decode_disclosure(TOY, disclosure)
    # The wire format is exactly header, payload and an equality proof.
    assert len(disclosure) == 39 + len(decoded.payload) + equality_proof.proof_bytes(TOY)
    assert set(vars(decoded)) == {"payload", "proof"}
    for encoding in (opening.randomness.astype(">i8").tobytes(),
                     opening.randomness.astype("i1").tobytes(),
                     (opening.randomness + 1).astype("u1").tobytes()):
        assert encoding not in disclosure


def test_disclosure_rejects_wrong_payload_context_or_envelope() -> None:
    statement, data, opening, disclosure = _disclosed()
    decoded = video_proof.decode_disclosure(TOY, disclosure)
    for payload in (b"secret provenance recorD", b"", b"secret provenance record!"):
        swapped = video_proof.encode_disclosure(TOY, video_proof.Disclosure(payload, decoded.proof))
        assert not _accepts(data, swapped, statement.statement_id)
    assert not _accepts(data, disclosure, statement.statement_id, nonce=b"M" * 32)
    assert not _accepts(data, disclosure, _statement(carrier_count=7).statement_id)
    other, _ = video_proof.create_envelope(TOY, statement, b"secret provenance record")
    assert not _accepts(other, disclosure, statement.statement_id)
    with pytest.raises(ValueError):  # the holder cannot disclose a payload it did not commit
        video_proof.create_disclosure(
            TOY, data, dataclasses.replace(opening, payload=b"another record"),
            statement_id=statement.statement_id, nonce=NONCE,
        )
    with pytest.raises(ValueError):  # another envelope's opening does not open this one
        video_proof.create_disclosure(
            TOY, other, opening, statement_id=statement.statement_id, nonce=NONCE
        )


def test_tampered_or_malformed_disclosures_are_rejected() -> None:
    rng = random.Random(0x5EED0025)
    statement, data, _, disclosure = _disclosed()
    for offset in (0, 4, 5, 36, 37, 38, 39, 50, len(disclosure) - 1):
        mutated = bytearray(disclosure)
        mutated[offset] ^= 0x01
        assert not _accepts(data, bytes(mutated), statement.statement_id)
    for corrupted in random_corruptions(disclosure, rng, 200):
        assert not _accepts(data, corrupted, statement.statement_id)
    for bogus in (disclosure[:-1], disclosure + b"\x00", b"", disclosure[:38], "ZKLD"):
        assert not _accepts(data, bogus, statement.statement_id)  # type: ignore[arg-type]
    assert not _accepts(data[:-1], disclosure, statement.statement_id)
    for statement_id, nonce in ((b"x", NONCE), (statement.statement_id, b"n" * 31),
                                (statement.statement_id, "N" * 32)):
        assert not _accepts(data, disclosure, statement_id, nonce)  # type: ignore[arg-type]
    oversized = bytearray(disclosure)
    oversized[37:39] = (TOY.max_payload_bytes + 1).to_bytes(2, "big")
    with pytest.raises(ValueError):
        video_proof.decode_disclosure(TOY, bytes(oversized))


def test_disclosure_is_bound_to_the_parameter_set_and_kind() -> None:
    statement, data, opening, disclosure = _disclosed()
    other = dataclasses.replace(TOY, name="bdlop-open-toy-v2")
    assert not video_proof.verify_disclosure_proof(
        other, data, disclosure, statement_id=statement.statement_id, nonce=NONCE
    )
    linkage_like = equality_proof.verify(  # not usable as an equality proof elsewhere
        TOY, statement.statement_id, video_proof.decode_envelope(TOY, data).commitment,
        video_proof._public_commitment(TOY, opening.payload)[0],
        video_proof.decode_disclosure(TOY, disclosure).proof,
    )
    assert not linkage_like
    with pytest.raises(TypeError):
        video_proof.create_disclosure(
            TOY, data, (opening.payload, opening.randomness),  # type: ignore[arg-type]
            statement_id=statement.statement_id, nonce=NONCE,
        )
    with pytest.raises(ValueError):
        video_proof.create_disclosure(
            TOY, data, opening, statement_id=statement.statement_id, nonce=b"short"
        )


def test_registered_credential_disclosure_works_on_the_commitment() -> None:
    commitment, randomness = _credential()
    opening = video_proof.PayloadOpening(b"device credential", randomness)
    relation = b"R" * 32
    disclosure = video_proof.create_commitment_disclosure(
        TOY, commitment, opening, statement_id=relation, nonce=NONCE
    )
    assert video_proof.verify_commitment_disclosure(
        TOY, commitment, disclosure, statement_id=relation, nonce=NONCE
    )
    stranger, _ = _credential(b"d" * 32)
    assert not video_proof.verify_commitment_disclosure(
        TOY, stranger, disclosure, statement_id=relation, nonce=NONCE
    )
    assert not video_proof.verify_commitment_disclosure(
        TOY, b"commitment", disclosure, statement_id=relation, nonce=NONCE  # type: ignore[arg-type]
    )
