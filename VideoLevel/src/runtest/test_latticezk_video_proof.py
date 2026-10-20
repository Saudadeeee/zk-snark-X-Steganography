"""Video statement binding and fixed-size envelope for the BDLOP backend."""

from __future__ import annotations

import dataclasses

import pytest

from src.lattice_zk import video_proof
from src.lattice_zk.params import BDLOP_OPEN_128, TOY

PINS = video_proof.VerifierPins(
    relation_id=b"R" * 32,
    registry_root=b"G" * 32,
    registry_epoch=7,
    codec_policy_id=b"C" * 32,
    carrier_profile_id=b"P" * 32,
)
SESSION = b"S" * 32


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
    assert video_proof.verify_disclosure(TOY, data, opening)
    forged = dataclasses.replace(opening, payload=b"another record")
    assert not video_proof.verify_disclosure(TOY, data, forged)


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
    assert video_proof.verify_disclosure(BDLOP_OPEN_128, data, opening)


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
