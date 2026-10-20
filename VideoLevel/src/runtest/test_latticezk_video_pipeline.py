"""Orchestration of the BDLOP video proof over a stand-in carrier channel.

The real H.264 channel is exercised by ``test_latticezk_video_e2e.py``.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.blind_payload_chunks import assemble_payload_chunks
from src.blind_sync import BlindOperatingContract
from src.lattice_pq import LatticeSigner
from src.lattice_zk import video_pipeline as pipeline
from src.lattice_zk.params import TOY
from src.zkp_registry import SignedZkpRelationRegistry
from src.zkp_sessions import SessionChallengeStore

SYNC_KEY = b"k" * 32
MARKER = b"\x00CARRIERS\x00"
PROFILE = pipeline.CarrierProfile(
    BlindOperatingContract(
        version="stable-carriers-video-only-v1", require_bitstream_patchable=True,
        patchability_headroom=64, stable_carriers_only=True,
    )
)


class FakeTransport:
    """Stores the payload after the 'non-carrier' bytes of a fake video."""

    @staticmethod
    def _context(body: bytes, payload_bytes: int) -> SimpleNamespace:
        positions = tuple((index, 0, 1) for index in range(payload_bytes * 8))
        return SimpleNamespace(
            positions_hash=hashlib.sha256(repr(positions).encode()).hexdigest(),
            canonical_video_sha256=hashlib.sha256(body).hexdigest(),
            global_positions=positions,
        )

    def derive_chunked_video_context(self, video_path, chunks, sync_key, contract, **_options):
        payload_bytes = len(assemble_payload_chunks(chunks))
        return self._context(Path(video_path).read_bytes(), payload_bytes)

    def embed_chunked_video_payload(self, cover, output, payload, sync_key, contract, **_options):
        Path(output).write_bytes(Path(cover).read_bytes() + MARKER + payload)
        return SimpleNamespace(carriers_used=len(payload) * 8, segments_used=1)

    def extract_chunked_video_payload(self, video_path, sync_key, contract, **_options):
        body, found, payload = Path(video_path).read_bytes().partition(MARKER)
        if not found:
            raise ValueError("no carriers found")
        context = self._context(body, len(payload))
        return SimpleNamespace(payload=payload, carriers_used=len(payload) * 8, **vars(context))


@pytest.fixture(scope="module")
def issuer() -> tuple[bytes, bytes]:
    return LatticeSigner.generate_keypair()


@pytest.fixture(scope="module")
def registry(issuer) -> SignedZkpRelationRegistry:
    descriptor = pipeline.relation_descriptor(TOY, PROFILE)
    unsigned = SignedZkpRelationRegistry.create(epoch=3, relations=[descriptor])
    return unsigned.sign(issuer[1], signer_id="test-issuer")


@pytest.fixture()
def pins(registry, issuer):
    return pipeline.pins_from_registry(
        registry, issuer[0], TOY, PROFILE, minimum_epoch=3, allow_toy_parameters=True
    )


def _embed(tmp_path: Path, pins, session: bytes, payload: bytes = b"hidden record") -> Path:
    cover = tmp_path / "cover.h264"
    cover.write_bytes(b"non-carrier syntax" * 50)
    stego = tmp_path / "stego.h264"
    result = pipeline.embed_video_proof(
        cover, stego, payload, params=TOY, pins=pins, profile=PROFILE,
        session_challenge=session, sync_key=SYNC_KEY, transport=FakeTransport(),
    )
    assert result.envelope_bytes * 8 == result.carriers_used
    assert payload not in stego.read_bytes()
    return stego


def _verify(stego: Path, pins, **options) -> pipeline.VerifyResult:
    return pipeline.verify_video_proof(
        stego, params=TOY, pins=pins, profile=PROFILE, sync_key=SYNC_KEY,
        transport=FakeTransport(), **options,
    )


def test_registry_pins_resolve_only_for_the_registered_configuration(registry, issuer, pins) -> None:
    assert pins.registry_epoch == 3 and len(pins.relation_id) == 32
    other_key, _ = LatticeSigner.generate_keypair()
    resolve = functools.partial(
        pipeline.pins_from_registry, minimum_epoch=3, allow_toy_parameters=True
    )
    with pytest.raises(ValueError):
        resolve(registry, other_key, TOY, PROFILE)
    with pytest.raises(ValueError):
        pipeline.pins_from_registry(
            registry, issuer[0], TOY, PROFILE, minimum_epoch=4, allow_toy_parameters=True
        )
    with pytest.raises(ValueError):  # toy challenge space is refused by default
        pipeline.pins_from_registry(registry, issuer[0], TOY, PROFILE, minimum_epoch=3)
    with pytest.raises(ValueError):
        resolve(registry, issuer[0], TOY, dataclasses.replace(PROFILE, chunk_bytes=999))
    with pytest.raises(ValueError):
        resolve(registry, issuer[0], dataclasses.replace(TOY, name="unregistered"), PROFILE)


def test_video_round_trip_with_a_one_use_session(tmp_path, pins) -> None:
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=60)
    grant = store.issue(context_binding=pipeline.session_binding(TOY, pins))
    stego = _embed(tmp_path, pins, grant.challenge)

    first = _verify(stego, pins, session_store=store)
    assert first.valid and first.statement_id is not None
    replay = _verify(stego, pins, session_store=store)
    assert not replay.valid


def test_unissued_or_differently_bound_session_is_rejected(tmp_path, pins) -> None:
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=60)
    stego = _embed(tmp_path, pins, b"\x07" * 32)
    assert not _verify(stego, pins, session_store=store).valid

    other = tmp_path / "other"
    other.mkdir()
    grant = store.issue(context_binding=b"\x01" * 32)
    assert not _verify(_embed(other, pins, grant.challenge), pins, session_store=store).valid


def test_stateless_verification_requires_the_expected_challenge(tmp_path, pins) -> None:
    stego = _embed(tmp_path, pins, b"\x07" * 32)
    assert _verify(stego, pins, expected_session=b"\x07" * 32).valid
    assert not _verify(stego, pins, expected_session=b"\x08" * 32).valid
    with pytest.raises(ValueError):
        _verify(stego, pins)


def test_non_carrier_video_change_invalidates_the_proof(tmp_path, pins) -> None:
    stego = _embed(tmp_path, pins, b"\x07" * 32)
    mutated = bytearray(stego.read_bytes())
    mutated[10] ^= 0x01
    stego.write_bytes(bytes(mutated))
    assert not _verify(stego, pins, expected_session=b"\x07" * 32).valid


def test_carrier_change_or_missing_envelope_is_rejected(tmp_path, pins) -> None:
    stego = _embed(tmp_path, pins, b"\x07" * 32)
    original = stego.read_bytes()
    mutated = bytearray(original)
    mutated[-100] ^= 0x01
    stego.write_bytes(bytes(mutated))
    assert not _verify(stego, pins, expected_session=b"\x07" * 32).valid
    stego.write_bytes(original[:-1])
    assert not _verify(stego, pins, expected_session=b"\x07" * 32).valid
    stego.write_bytes(original.partition(MARKER)[0])
    assert not _verify(stego, pins, expected_session=b"\x07" * 32).valid


def test_verifier_with_other_pins_rejects(tmp_path, pins) -> None:
    stego = _embed(tmp_path, pins, b"\x07" * 32)
    for field, value in (
        ("relation_id", b"\x02" * 32), ("registry_root", b"\x02" * 32),
        ("registry_epoch", 4), ("carrier_profile_id", b"\x02" * 32),
    ):
        changed = dataclasses.replace(pins, **{field: value})
        assert not _verify(stego, changed, expected_session=b"\x07" * 32).valid


def test_transport_failures_are_reported_as_rejection(tmp_path, pins) -> None:
    class BrokenTransport(FakeTransport):
        def extract_chunked_video_payload(self, *_arguments, **_options):
            raise RuntimeError("ffmpeg failed")

    stego = _embed(tmp_path, pins, b"\x07" * 32)
    result = pipeline.verify_video_proof(
        stego, params=TOY, pins=pins, profile=PROFILE, sync_key=SYNC_KEY,
        transport=BrokenTransport(), expected_session=b"\x07" * 32,
    )
    assert not result.valid and "RuntimeError" in result.reason


def test_expired_session_is_rejected(tmp_path, pins) -> None:
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=1)
    grant = store.issue(context_binding=pipeline.session_binding(TOY, pins), now=1)
    stego = _embed(tmp_path, pins, grant.challenge)
    assert not _verify(stego, pins, session_store=store).valid


# -- registered credential: proof-only envelope --------------------------- #

REGISTERED_PROFILE = dataclasses.replace(PROFILE, registered=True)


def _registered_setup(issuer, seed: bytes = b"c" * 32):
    from src.lattice_zk import bdlop, codec

    randomness = bdlop.sample_randomness(TOY, seed)
    commitment = bdlop.commit(TOY, codec.encode_payload(TOY, b"device 42"), randomness)
    descriptor = pipeline.relation_descriptor(TOY, REGISTERED_PROFILE, commitment)
    registry = SignedZkpRelationRegistry.create(epoch=5, relations=[descriptor]).sign(
        issuer[1], signer_id="test-issuer"
    )
    pins = pipeline.pins_from_registry(
        registry, issuer[0], TOY, REGISTERED_PROFILE, minimum_epoch=5,
        allow_toy_parameters=True, credential=commitment,
    )
    return registry, pins, pipeline.Credential(commitment, randomness)


def _embed_registered(tmp_path: Path, pins, credential, session: bytes) -> Path:
    cover = tmp_path / "cover.h264"
    cover.write_bytes(b"non-carrier syntax" * 50)
    stego = tmp_path / "stego.h264"
    result = pipeline.embed_video_proof(
        cover, stego, None, params=TOY, pins=pins, profile=REGISTERED_PROFILE,
        session_challenge=session, sync_key=SYNC_KEY, credential=credential,
        transport=FakeTransport(),
    )
    assert result.opening is None and result.envelope_bytes == 69 + TOY.proof_bytes
    return stego


def test_registered_credential_round_trip_authenticates_the_holder(tmp_path, issuer) -> None:
    registry, pins, credential = _registered_setup(issuer)
    stego = _embed_registered(tmp_path, pins, credential, b"\x07" * 32)
    verify = functools.partial(
        pipeline.verify_video_proof, stego, params=TOY, pins=pins, profile=REGISTERED_PROFILE,
        sync_key=SYNC_KEY, transport=FakeTransport(), expected_session=b"\x07" * 32,
    )
    assert verify(credential=credential.commitment).valid

    _, _, stranger = _registered_setup(issuer, b"d" * 32)
    assert not verify(credential=stranger.commitment).valid
    with pytest.raises(ValueError):
        verify()  # a registered profile always needs the pinned commitment


def test_unregistered_credential_cannot_resolve_pins(issuer) -> None:
    registry, _, _ = _registered_setup(issuer)
    _, _, stranger = _registered_setup(issuer, b"d" * 32)
    with pytest.raises(ValueError):
        pipeline.pins_from_registry(
            registry, issuer[0], TOY, REGISTERED_PROFILE, minimum_epoch=5,
            allow_toy_parameters=True, credential=stranger.commitment,
        )
    with pytest.raises(ValueError):
        pipeline.relation_descriptor(TOY, REGISTERED_PROFILE)
    with pytest.raises(ValueError):
        pipeline.relation_descriptor(TOY, PROFILE, stranger.commitment)


def test_holder_without_the_opening_cannot_embed(tmp_path, issuer) -> None:
    from src.lattice_zk import bdlop

    _, pins, credential = _registered_setup(issuer)
    thief = pipeline.Credential(credential.commitment, bdlop.sample_randomness(TOY, b"t" * 32))
    with pytest.raises(ValueError):
        _embed_registered(tmp_path, pins, thief, b"\x07" * 32)


def test_verified_envelope_supports_later_linkage_and_disclosure(tmp_path, pins) -> None:
    from src.lattice_zk import bdlop, codec, linkage, video_proof

    cover = tmp_path / "cover.h264"
    cover.write_bytes(b"non-carrier syntax" * 50)
    stego = tmp_path / "stego.h264"
    embedded = pipeline.embed_video_proof(
        cover, stego, b"device 42", params=TOY, pins=pins, profile=PROFILE,
        session_challenge=b"\x07" * 32, sync_key=SYNC_KEY, transport=FakeTransport(),
    )
    verified = _verify(stego, pins, expected_session=b"\x07" * 32)
    assert verified.valid and verified.envelope is not None
    assert video_proof.verify_disclosure(TOY, verified.envelope, embedded.opening)

    randomness = bdlop.sample_randomness(TOY, b"c" * 32)
    credential = bdlop.commit(TOY, codec.encode_payload(TOY, b"device 42"), randomness)
    in_video = linkage.envelope_commitment(TOY, verified.envelope)
    context = (verified.statement_id, credential.to_bytes(TOY))
    proof = linkage.prove_linkage(
        TOY, context, in_video, embedded.opening.randomness, credential, randomness
    )
    assert linkage.verify_linkage(TOY, context, in_video, credential, proof)
    rejected = _verify(stego, pins, expected_session=b"\x08" * 32)
    assert rejected.envelope is None


# -- verifier configuration and exception safety -------------------------- #

def test_embed_requires_exactly_the_input_its_profile_proves(tmp_path, pins, issuer) -> None:
    _, registered_pins, credential = _registered_setup(issuer)
    cover = tmp_path / "cover.h264"
    cover.write_bytes(b"non-carrier syntax" * 50)
    for profile, payload, held, chosen_pins in (
        (PROFILE, None, None, pins),  # in-band without a payload
        (PROFILE, b"p", credential, pins),  # in-band with a credential
        (REGISTERED_PROFILE, b"p", credential, registered_pins),  # registered with a payload
        (REGISTERED_PROFILE, None, None, registered_pins),  # registered without a credential
    ):
        with pytest.raises(ValueError):
            pipeline.embed_video_proof(
                cover, tmp_path / "stego.h264", payload, params=TOY, pins=chosen_pins,
                profile=profile, session_challenge=b"\x07" * 32, sync_key=SYNC_KEY,
                credential=held, transport=FakeTransport(),
            )
    assert not (tmp_path / "stego.h264").exists()


def test_malformed_verifier_configuration_is_refused_loudly(tmp_path, pins, issuer) -> None:
    stego = _embed(tmp_path, pins, b"\x07" * 32)
    for session in (b"\x07" * 31, "07" * 32, bytearray(32)):
        with pytest.raises(ValueError):
            _verify(stego, pins, expected_session=session)
    _, registered_pins, credential = _registered_setup(issuer)
    malformed = dataclasses.replace(credential.commitment, t2=credential.commitment.t2 + TOY.modulus)
    for pinned in (malformed, credential.commitment.to_bytes(TOY)):
        with pytest.raises(ValueError):
            pipeline.verify_video_proof(
                stego, params=TOY, pins=registered_pins, profile=REGISTERED_PROFILE,
                sync_key=SYNC_KEY, transport=FakeTransport(), expected_session=b"\x07" * 32,
                credential=pinned,
            )


@pytest.mark.parametrize("field", ["positions_hash", "canonical_video_sha256"])
def test_malformed_transport_digests_reject_instead_of_raising(tmp_path, pins, field) -> None:
    class GarblingTransport(FakeTransport):
        def extract_chunked_video_payload(self, *arguments, **options):
            extracted = super().extract_chunked_video_payload(*arguments, **options)
            setattr(extracted, field, "not hex")
            return extracted

    stego = _embed(tmp_path, pins, b"\x07" * 32)
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=60)
    for options in ({"expected_session": b"\x07" * 32}, {"session_store": store}):
        result = pipeline.verify_video_proof(
            stego, params=TOY, pins=pins, profile=PROFILE, sync_key=SYNC_KEY,
            transport=GarblingTransport(), **options,
        )
        assert not result.valid and result.reason.startswith("statement rejected")


def test_registry_epoch_outside_the_statement_field_is_refused(issuer) -> None:
    descriptor = pipeline.relation_descriptor(TOY, PROFILE)
    record = SignedZkpRelationRegistry.create(epoch=0, relations=[descriptor]).relations
    # An issuer-signed epoch that cannot be encoded as u64 must not yield pins.
    oversized = SignedZkpRelationRegistry(1 << 64, record).sign(issuer[1], signer_id="test-issuer")
    with pytest.raises(ValueError):
        pipeline.pins_from_registry(
            oversized, issuer[0], TOY, PROFILE, minimum_epoch=0, allow_toy_parameters=True
        )


def test_random_carrier_corruptions_never_verify(tmp_path, pins) -> None:
    import random

    rng = random.Random(0x5EED0031)
    stego = _embed(tmp_path, pins, b"\x07" * 32)
    body, marker, envelope = stego.read_bytes().partition(MARKER)
    for index in range(40):
        bit = rng.randrange(len(envelope) * 8)
        mutated = bytearray(envelope)
        mutated[bit // 8] ^= 0x80 >> (bit % 8)
        stego.write_bytes(body + marker + bytes(mutated))
        assert not _verify(stego, pins, expected_session=b"\x07" * 32).valid, index
