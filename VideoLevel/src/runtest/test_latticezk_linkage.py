"""Linkage proofs between commitments carried by verified videos."""

from __future__ import annotations

import pytest

from src.lattice_zk import bdlop, codec, linkage, video_proof
from src.lattice_zk.params import TOY

PINS = video_proof.VerifierPins(b"R" * 32, b"G" * 32, 1, b"C" * 32, b"P" * 32)


def _video(session: bytes, payload: bytes, digest: bytes):
    statement = video_proof.build_statement(
        TOY, PINS, session, carrier_count=10, positions_hash=b"H" * 32,
        canonical_video_sha256=digest,
    )
    envelope, opening = video_proof.create_envelope(TOY, statement, payload)
    assert video_proof.verify_envelope(TOY, statement, envelope, allow_toy_parameters=True)
    return statement, envelope, opening


def test_two_videos_with_one_payload_can_be_linked_without_revealing_it() -> None:
    first = _video(b"1" * 32, b"owner record", b"A" * 32)
    second = _video(b"2" * 32, b"owner record", b"B" * 32)
    context = (first[0].statement_id, second[0].statement_id)
    commitments = [linkage.envelope_commitment(TOY, video[1]) for video in (first, second)]
    proof = linkage.prove_linkage(
        TOY, context, commitments[0], first[2].randomness, commitments[1], second[2].randomness
    )
    assert linkage.verify_linkage(TOY, context, commitments[0], commitments[1], proof, allow_toy_parameters=True)
    assert b"owner record" not in proof


def test_videos_with_different_payloads_cannot_be_linked() -> None:
    first = _video(b"1" * 32, b"owner record", b"A" * 32)
    second = _video(b"2" * 32, b"other record", b"B" * 32)
    context = (first[0].statement_id, second[0].statement_id)
    commitments = [linkage.envelope_commitment(TOY, video[1]) for video in (first, second)]
    with pytest.raises(ValueError):
        linkage.prove_linkage(
            TOY, context, commitments[0], first[2].randomness,
            commitments[1], second[2].randomness,
        )


def test_linkage_does_not_transfer_to_other_videos_or_contexts() -> None:
    first = _video(b"1" * 32, b"owner record", b"A" * 32)
    second = _video(b"2" * 32, b"owner record", b"B" * 32)
    third = _video(b"3" * 32, b"owner record", b"C" * 32)
    context = (first[0].statement_id, second[0].statement_id)
    commitments = [linkage.envelope_commitment(TOY, video[1]) for video in (first, second, third)]
    proof = linkage.prove_linkage(
        TOY, context, commitments[0], first[2].randomness, commitments[1], second[2].randomness
    )
    assert not linkage.verify_linkage(TOY, context, commitments[0], commitments[2], proof, allow_toy_parameters=True)
    assert not linkage.verify_linkage(TOY, context[::-1], commitments[0], commitments[1], proof, allow_toy_parameters=True)
    other_context = (first[0].statement_id, third[0].statement_id)
    assert not linkage.verify_linkage(TOY, other_context, commitments[0], commitments[1], proof, allow_toy_parameters=True)
    assert not linkage.verify_linkage(TOY, ("text",), commitments[0], commitments[1], proof, allow_toy_parameters=True)  # type: ignore[arg-type]


def test_video_payload_can_be_linked_to_a_registered_credential() -> None:
    credential_randomness = bdlop.sample_randomness(TOY, b"c" * 32)
    credential = bdlop.commit(
        TOY, codec.encode_payload(TOY, b"device 42"), credential_randomness
    )
    statement, envelope, opening = _video(b"1" * 32, b"device 42", b"A" * 32)
    context = (statement.statement_id, credential.to_bytes(TOY))
    in_video = linkage.envelope_commitment(TOY, envelope)
    proof = linkage.prove_linkage(
        TOY, context, in_video, opening.randomness, credential, credential_randomness
    )
    assert linkage.verify_linkage(TOY, context, in_video, credential, proof, allow_toy_parameters=True)

    stranger = bdlop.commit(
        TOY, codec.encode_payload(TOY, b"device 42"), bdlop.sample_randomness(TOY, b"d" * 32)
    )
    assert not linkage.verify_linkage(TOY, context, in_video, stranger, proof, allow_toy_parameters=True)


def test_context_encoding_is_unambiguous() -> None:
    assert linkage.linkage_statement(TOY, (b"ab", b"c")) != linkage.linkage_statement(TOY, (b"a", b"bc"))
    assert linkage.linkage_statement(TOY, (b"abc",)) != linkage.linkage_statement(TOY, (b"abc", b""))
