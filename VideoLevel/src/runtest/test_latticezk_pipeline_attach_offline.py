"""Pipeline-level checks: payload range attachment profiles and offline epoch verification."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from src.lattice_zk import video_pipeline as pipeline
from src.lattice_zk import video_proof
from src.lattice_zk.params import TOY
from src.registry.epoch_challenges import EpochChallenge, OfflineReplayLedger
from src.registry.lattice_pq import LatticeSigner
from src.registry.zkp_registry import SignedZkpRelationRegistry
from src.runtest.test_latticezk_video_pipeline import MARKER, PROFILE, SYNC_KEY, FakeTransport

LENGTH = 20
ATTACHED = dataclasses.replace(PROFILE, payload_range_length=LENGTH)
NOW = 1_800_000_000
WINDOW = 3600


@pytest.fixture(scope="module")
def issuer() -> tuple[bytes, bytes]:
    return LatticeSigner.generate_keypair()


def _pins(issuer, profile: pipeline.CarrierProfile):
    registry = SignedZkpRelationRegistry.create(
        epoch=3, relations=[pipeline.relation_descriptor(TOY, profile)]
    ).sign(issuer[1], signer_id="test-issuer")
    return pipeline.pins_from_registry(
        registry, issuer[0], TOY, profile, minimum_epoch=3, allow_toy_parameters=True
    )


def _embed(tmp_path: Path, pins, profile, session: bytes, payload: bytes) -> tuple[Path, pipeline.EmbedResult]:
    cover, stego = tmp_path / "cover.h264", tmp_path / "stego.h264"
    cover.write_bytes(b"non-carrier syntax" * 50)
    result = pipeline.embed_video_proof(
        cover, stego, payload, params=TOY, pins=pins, profile=profile,
        session_challenge=session, sync_key=SYNC_KEY, transport=FakeTransport(),
    )
    return stego, result


def _verify(stego: Path, pins, profile, **options) -> pipeline.VerifyResult:
    return pipeline.verify_video_proof(
        stego, params=TOY, pins=pins, profile=profile, sync_key=SYNC_KEY,
        transport=FakeTransport(), allow_toy_parameters=True, **options,
    )


# ------------------------------------------------------------- attachments


def test_attachment_profile_has_its_own_identifiers() -> None:
    assert ATTACHED.attachment(TOY) == video_proof.payload_range_attachment(TOY, LENGTH)
    assert PROFILE.attachment(TOY) is None
    assert ATTACHED.profile_id(TOY) != PROFILE.profile_id(TOY)
    assert pipeline.policy_hash(TOY, ATTACHED) != pipeline.policy_hash(TOY, PROFILE)
    other = dataclasses.replace(PROFILE, payload_range_length=LENGTH + 1)
    assert other.profile_id(TOY) != ATTACHED.profile_id(TOY)
    with pytest.raises(ValueError, match="in-band"):
        dataclasses.replace(PROFILE, registered=True, payload_range_length=LENGTH)
    with pytest.raises(ValueError):
        dataclasses.replace(PROFILE, payload_range_length=-1)


def test_attached_envelope_round_trips_and_is_pinned(tmp_path, issuer) -> None:
    pins = _pins(issuer, ATTACHED)
    payload = video_proof.pad_payload(b"hidden record", LENGTH)
    stego, embedded = _embed(tmp_path, pins, ATTACHED, b"\x07" * 32, payload)
    expected = video_proof.envelope_size(TOY, attachment=ATTACHED.attachment(TOY))
    assert embedded.envelope_bytes == expected and embedded.carriers_used == expected * 8
    result = _verify(stego, pins, ATTACHED, expected_session=b"\x07" * 32)
    assert result.valid and result.envelope is not None
    # The verified envelope discloses the (padded) payload; the recipient unpads.
    disclosure = video_proof.create_disclosure(
        TOY, result.envelope, embedded.opening, statement_id=result.statement_id, nonce=b"N" * 32,
        attachment=ATTACHED.attachment(TOY),
    )
    assert video_proof.verify_disclosure_proof(
        TOY, result.envelope, disclosure, statement_id=result.statement_id, nonce=b"N" * 32,
        allow_toy_parameters=True, attachment=ATTACHED.attachment(TOY),
    )
    assert video_proof.unpad_payload(video_proof.decode_disclosure(TOY, disclosure).payload) == b"hidden record"
    # A verifier pinned to another length, or to no attachment, rejects the same video.
    for profile in (PROFILE, dataclasses.replace(PROFILE, payload_range_length=LENGTH + 1)):
        assert not _verify(stego, _pins(issuer, profile), profile, expected_session=b"\x07" * 32).valid


def test_attached_range_proof_tamper_is_rejected(tmp_path, issuer) -> None:
    pins = _pins(issuer, ATTACHED)
    payload = video_proof.pad_payload(b"x", LENGTH)
    stego, _ = _embed(tmp_path, pins, ATTACHED, b"\x07" * 32, payload)
    original = stego.read_bytes()
    body, _, framed = original.partition(MARKER)
    mutated = bytearray(original)
    mutated[-1] ^= 0x01  # last byte of the carried envelope: inside the range proof
    stego.write_bytes(bytes(mutated))
    assert not _verify(stego, pins, ATTACHED, expected_session=b"\x07" * 32).valid
    stego.write_bytes(original)
    assert _verify(stego, pins, ATTACHED, expected_session=b"\x07" * 32).valid


def test_prover_refuses_a_wrong_length_under_an_attachment_profile(tmp_path, issuer) -> None:
    pins = _pins(issuer, ATTACHED)
    with pytest.raises(ValueError, match="length"):
        _embed(tmp_path, pins, ATTACHED, b"\x07" * 32, b"too short")


# ---------------------------------------------------------- offline epochs


def _beacon(issuer, now: int = NOW) -> EpochChallenge:
    return EpochChallenge.issue_now(issuer[1], window_seconds=WINDOW, signer_id="issuer", now=now)


def test_offline_verification_accepts_once_per_verifier(tmp_path, issuer) -> None:
    pins = _pins(issuer, PROFILE)
    beacon = _beacon(issuer)
    stego, embedded = _embed(tmp_path, pins, PROFILE, beacon.challenge, b"hidden record")
    ledger = OfflineReplayLedger(tmp_path / "ledger.sqlite", window_seconds=WINDOW, max_age_epochs=24)
    common = dict(params=TOY, pins=pins, profile=PROFILE, sync_key=SYNC_KEY,
                  transport=FakeTransport(), allow_toy_parameters=True)
    first = pipeline.verify_video_proof_offline(
        stego, beacon=beacon, issuer_public_key=issuer[0], ledger=ledger, now=NOW, **common
    )
    assert first.valid and first.statement_id == embedded.statement_id
    replay = pipeline.verify_video_proof_offline(
        stego, beacon=beacon, issuer_public_key=issuer[0], ledger=ledger, now=NOW + 60, **common
    )
    assert not replay.valid and "replay" in replay.reason
    # Another verifier (its own ledger) accepts the same video within the window.
    other = OfflineReplayLedger(tmp_path / "other.sqlite", window_seconds=WINDOW, max_age_epochs=24)
    assert pipeline.verify_video_proof_offline(
        stego, beacon=beacon, issuer_public_key=issuer[0], ledger=other, now=NOW + WINDOW, **common
    ).valid
    # Expired beacon, wrong issuer key, or a beacon the video was not bound to: rejected.
    late = OfflineReplayLedger(tmp_path / "late.sqlite", window_seconds=WINDOW, max_age_epochs=24)
    expired = pipeline.verify_video_proof_offline(
        stego, beacon=beacon, issuer_public_key=issuer[0], ledger=late, now=NOW + 30 * WINDOW, **common
    )
    assert not expired.valid and "expired" in expired.reason
    wrong_key = pipeline.verify_video_proof_offline(
        stego, beacon=beacon, issuer_public_key=LatticeSigner.generate_keypair()[0], ledger=late,
        now=NOW, **common,
    )
    assert not wrong_key.valid and "signature" in wrong_key.reason
    other_beacon = _beacon(issuer, NOW + WINDOW)
    unbound = pipeline.verify_video_proof_offline(
        stego, beacon=other_beacon, issuer_public_key=issuer[0], ledger=late, now=NOW + WINDOW, **common
    )
    assert not unbound.valid and unbound.reason.startswith("proof")


def test_offline_verification_refuses_misuse(tmp_path, issuer) -> None:
    pins = _pins(issuer, PROFILE)
    beacon = _beacon(issuer)
    stego, _ = _embed(tmp_path, pins, PROFILE, beacon.challenge, b"hidden record")
    ledger = OfflineReplayLedger(tmp_path / "ledger.sqlite", window_seconds=WINDOW, max_age_epochs=24)
    common = dict(params=TOY, pins=pins, profile=PROFILE, sync_key=SYNC_KEY,
                  transport=FakeTransport(), allow_toy_parameters=True)
    with pytest.raises(TypeError):
        pipeline.verify_video_proof_offline(
            stego, beacon=beacon.to_dict(), issuer_public_key=issuer[0], ledger=ledger, **common
        )
    with pytest.raises(TypeError):
        pipeline.verify_video_proof_offline(
            stego, beacon=beacon, issuer_public_key=issuer[0], ledger=object(), **common
        )
    with pytest.raises(ValueError, match="session"):
        pipeline.verify_video_proof_offline(
            stego, beacon=beacon, issuer_public_key=issuer[0], ledger=ledger,
            expected_session=beacon.challenge, **common,
        )
    # Misconfigured pins still raise, before the ledger records anything.
    with pytest.raises(ValueError, match="relation id"):
        pipeline.verify_video_proof_offline(
            stego, beacon=beacon, issuer_public_key=issuer[0], ledger=ledger, now=NOW,
            **{**common, "pins": dataclasses.replace(pins, relation_id=b"\x02" * 32)},
        )
    assert pipeline.verify_video_proof_offline(
        stego, beacon=beacon, issuer_public_key=issuer[0], ledger=ledger, now=NOW, **common
    ).valid
