"""In-band envelopes with an attached payload range proof (video_proof.py)."""

from __future__ import annotations

import pytest

from src.lattice_zk import payload_range_proof as pr
from src.lattice_zk import video_proof
from src.lattice_zk.params import BDLOP_OPEN_128, BDLOP_OPEN_128_V2, TOY

PINS = video_proof.VerifierPins(
    relation_id=b"R" * 32, registry_root=b"T" * 32, registry_epoch=3,
    codec_policy_id=b"C" * 32, carrier_profile_id=b"P" * 32,
)
SESSION = b"S" * 32
LENGTH = 20


def _statement(params, session: bytes = SESSION) -> video_proof.VideoStatement:
    return video_proof.build_statement(
        params, PINS, session, carrier_count=7, positions_hash=b"H" * 32,
        canonical_video_sha256=b"V" * 32,
    )


@pytest.fixture(scope="module")
def attached():
    attachment = video_proof.payload_range_attachment(TOY, LENGTH)
    statement = _statement(TOY)
    payload = video_proof.pad_payload(b"hidden record", LENGTH)
    data, opening = video_proof.create_envelope(TOY, statement, payload, attachment=attachment)
    return attachment, statement, payload, data, opening


# ------------------------------------------------------------- parameter sets


def test_attachment_parameters_follow_the_base_set() -> None:
    assert video_proof.payload_range_params_for(BDLOP_OPEN_128) is pr.PAYLOAD_RANGE_128_V2
    assert video_proof.payload_range_params_for(BDLOP_OPEN_128_V2) is pr.PAYLOAD_RANGE_128_V1
    assert video_proof.payload_range_params_for(TOY) is pr.PAYLOAD_RANGE_TOY
    attachment = video_proof.payload_range_attachment(BDLOP_OPEN_128, 32)
    assert attachment.size == 3 + pr.PAYLOAD_RANGE_128.proof_bytes(32) == 46_673
    assert video_proof.envelope_size(BDLOP_OPEN_128, attachment=attachment) == 16_421 + 46_673
    with pytest.raises(ValueError):
        video_proof.envelope_size(BDLOP_OPEN_128, registered=True, attachment=attachment)
    with pytest.raises(ValueError):
        video_proof.envelope_size(TOY, attachment=attachment)  # built on another base
    with pytest.raises(ValueError):
        video_proof.PayloadRangeAttachment(pr.PAYLOAD_RANGE_128, 129)
    assert attachment.descriptor() == {
        "type": "payload-range", "parameter_id": pr.PAYLOAD_RANGE_128.parameter_id.hex(),
        "payload_length": 32,
    }


def test_padding_round_trips_and_rejects_malformed_input() -> None:
    padded = video_proof.pad_payload(b"abc", 8)
    assert padded == b"abc\x80\x00\x00\x00\x00"
    assert video_proof.unpad_payload(padded) == b"abc"
    assert video_proof.unpad_payload(video_proof.pad_payload(b"", 1)) == b""
    with pytest.raises(ValueError):
        video_proof.pad_payload(b"abcdefgh", 8)  # no room for the marker
    for bad in (b"", b"\x00\x00", b"abc", b"abc\x81"):
        with pytest.raises(ValueError):
            video_proof.unpad_payload(bad)


# --------------------------------------------------------------- envelopes


def test_attached_envelope_verifies_and_discloses(attached) -> None:
    attachment, statement, payload, data, opening = attached
    assert len(data) == video_proof.envelope_size(TOY, attachment=attachment)
    assert data[4] == video_proof.ATTACHED_ENVELOPE_VERSION
    assert video_proof.verify_envelope(TOY, statement, data, allow_toy_parameters=True, attachment=attachment)
    assert video_proof.self_check_opening(TOY, data, opening, attachment)
    assert video_proof.envelope_session(TOY, data, attachment=attachment) == SESSION
    disclosure = video_proof.create_disclosure(
        TOY, data, opening, statement_id=statement.statement_id, nonce=b"N" * 32, attachment=attachment
    )
    assert video_proof.verify_disclosure_proof(
        TOY, data, disclosure, statement_id=statement.statement_id, nonce=b"N" * 32,
        allow_toy_parameters=True, attachment=attachment,
    )
    assert video_proof.unpad_payload(video_proof.decode_disclosure(TOY, disclosure).payload) == b"hidden record"


def test_attached_envelope_is_rejected_without_the_pin_and_vice_versa(attached) -> None:
    attachment, statement, _, data, _ = attached
    # A verifier that pins no attachment never accepts the longer envelope.
    assert not video_proof.verify_envelope(TOY, statement, data, allow_toy_parameters=True)
    # A verifier that pins an attachment never accepts a plain envelope.
    plain, _ = video_proof.create_envelope(TOY, statement, b"plain")
    assert not video_proof.verify_envelope(TOY, statement, plain, allow_toy_parameters=True, attachment=attachment)
    with pytest.raises(ValueError):
        video_proof.envelope_session(TOY, plain, attachment=attachment)


def test_attachment_binds_length_statement_and_proof_bytes(attached) -> None:
    attachment, statement, _, data, _ = attached
    other_length = video_proof.payload_range_attachment(TOY, LENGTH + 1)
    assert not video_proof.verify_envelope(TOY, statement, data, allow_toy_parameters=True, attachment=other_length)
    # Same envelope, another session: the opening proof fails first.
    other_session = _statement(TOY, b"X" * 32)
    assert not video_proof.verify_envelope(TOY, other_session, data, allow_toy_parameters=True, attachment=attachment)
    # Attachment header tampering and range proof tampering both reject.
    end = len(data) - attachment.size
    for index in (end, end + 1, end + 2, end + 3, len(data) - 1):
        mutated = bytearray(data)
        mutated[index] ^= 1
        assert not video_proof.verify_envelope(
            TOY, statement, bytes(mutated), allow_toy_parameters=True, attachment=attachment
        )


def test_attached_range_proof_cannot_be_transplanted(attached) -> None:
    """A valid opening proof with a range proof taken from another envelope rejects."""
    attachment, statement, payload, data, _ = attached
    other, _ = video_proof.create_envelope(TOY, statement, payload, attachment=attachment)
    end = len(data) - attachment.proof_bytes
    frankenstein = data[:end] + other[end:]
    assert not video_proof.verify_envelope(TOY, statement, frankenstein, allow_toy_parameters=True, attachment=attachment)


def test_prover_refuses_a_payload_of_another_length() -> None:
    attachment = video_proof.payload_range_attachment(TOY, LENGTH)
    with pytest.raises(ValueError):
        video_proof.create_envelope(TOY, _statement(TOY), b"short", attachment=attachment)
    with pytest.raises(ValueError):
        video_proof.create_envelope(
            TOY, _statement(TOY), b"x" * LENGTH,
            attachment=video_proof.payload_range_attachment(BDLOP_OPEN_128, LENGTH),
        )


def test_plain_envelopes_are_unchanged() -> None:
    statement = _statement(TOY)
    data, opening = video_proof.create_envelope(TOY, statement, b"plain")
    assert len(data) == video_proof.envelope_size(TOY) and data[4] == video_proof.ENVELOPE_VERSION
    assert video_proof.verify_envelope(TOY, statement, data, allow_toy_parameters=True)
    assert video_proof.self_check_opening(TOY, data, opening)
