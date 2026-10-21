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

from src.blind_payload_chunks import CHUNK_HEADER, assemble_payload_chunks, pack_payload_chunks
from src.blind_sync import BlindOperatingContract
from src.lattice_pq import LatticeSigner
from src.lattice_zk import video_pipeline as pipeline
from src.lattice_zk.params import TOY
from src.runtest.test_latticezk_bdlop import forged_commitment
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

    def embed_chunked_video_payload(self, cover, output, payload, sync_key, contract, *, chunk_size,
                                    **_options):
        chunks = pack_payload_chunks(payload, chunk_size=chunk_size)
        Path(output).write_bytes(Path(cover).read_bytes() + MARKER + b"".join(chunks))
        return SimpleNamespace(carriers_used=len(payload) * 8, segments_used=len(chunks))

    def extract_chunked_video_payload(self, video_path, sync_key, contract, **_options):
        body, found, framed = Path(video_path).read_bytes().partition(MARKER)
        if not found:
            raise ValueError("no carriers found")
        chunks = []
        while framed:  # chunk boundaries come from the (carrier-borne) headers
            if len(framed) < CHUNK_HEADER.size:
                raise ValueError("truncated chunk header")
            _, _, index, count, total, size, _, _ = CHUNK_HEADER.unpack_from(framed)
            length = CHUNK_HEADER.size + (size if index < count - 1 else total - size * index)
            if length <= CHUNK_HEADER.size or length > len(framed):
                raise ValueError("chunk header declares an impossible length")
            chunks.append(framed[:length])
            framed = framed[length:]
        payload = assemble_payload_chunks(chunks)
        context = self._context(body, len(payload))
        return SimpleNamespace(
            payload=payload, carriers_used=len(payload) * 8, chunks=tuple(chunks), **vars(context)
        )


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
        transport=FakeTransport(), allow_toy_parameters=True, **options,
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
        ("registry_root", b"\x02" * 32), ("registry_epoch", 4), ("carrier_profile_id", b"\x02" * 32),
    ):
        changed = dataclasses.replace(pins, **{field: value})
        assert not _verify(stego, changed, expected_session=b"\x07" * 32).valid
    # A relation id that is not this configuration's is verifier misconfiguration.
    with pytest.raises(ValueError, match="relation id"):
        _verify(stego, dataclasses.replace(pins, relation_id=b"\x02" * 32),
                expected_session=b"\x07" * 32)


def _embed_with_profile(tmp_path: Path, issuer, profile: pipeline.CarrierProfile):
    """Embed under ``profile``; return the stego path and a verifier for it."""
    signed = SignedZkpRelationRegistry.create(
        epoch=3, relations=[pipeline.relation_descriptor(TOY, profile)]
    ).sign(issuer[1], signer_id="test-issuer")
    profile_pins = pipeline.pins_from_registry(
        signed, issuer[0], TOY, profile, minimum_epoch=3, allow_toy_parameters=True
    )
    cover, stego = tmp_path / "cover.h264", tmp_path / "stego.h264"
    cover.write_bytes(b"non-carrier syntax" * 50)
    pipeline.embed_video_proof(
        cover, stego, b"hidden record", params=TOY, pins=profile_pins, profile=profile,
        session_challenge=b"\x07" * 32, sync_key=SYNC_KEY, transport=FakeTransport(),
    )

    def verify(video: Path) -> pipeline.VerifyResult:
        return pipeline.verify_video_proof(
            video, params=TOY, pins=profile_pins, profile=profile, sync_key=SYNC_KEY,
            transport=FakeTransport(), expected_session=b"\x07" * 32, allow_toy_parameters=True,
        )

    return stego, verify


def test_rewritten_single_chunk_header_is_rejected(tmp_path, issuer) -> None:
    """D1: with one chunk, the chunk_size field is free unless the verifier pins it."""
    stego, verify = _embed_with_profile(
        tmp_path, issuer, dataclasses.replace(PROFILE, chunk_bytes=65_535)
    )
    assert verify(stego).valid
    body, _, chunk = stego.read_bytes().partition(MARKER)
    fields = list(CHUNK_HEADER.unpack_from(chunk))
    assert fields[3] == 1 and fields[5] == 65_535
    fields[5] = fields[4] + 7  # still one chunk, still a well-formed frame
    rewritten = CHUNK_HEADER.pack(*fields) + chunk[CHUNK_HEADER.size :]
    assert assemble_payload_chunks([rewritten]) == assemble_payload_chunks([chunk])
    stego.write_bytes(body + MARKER + rewritten)
    result = verify(stego)
    assert not result.valid and "canonical chunking" in result.reason


def test_rechunked_multi_chunk_envelope_is_rejected(tmp_path, issuer) -> None:
    profile = dataclasses.replace(PROFILE, chunk_bytes=256)
    stego, verify = _embed_with_profile(tmp_path, issuer, profile)
    assert verify(stego).valid
    body, _, _ = stego.read_bytes().partition(MARKER)
    honest = FakeTransport().extract_chunked_video_payload(stego, SYNC_KEY, profile.contract)
    assert len(honest.chunks) > 1
    # A different, self-consistent chunking of the same envelope still assembles.
    rechunked = pack_payload_chunks(honest.payload, chunk_size=profile.chunk_bytes + 1)
    assert assemble_payload_chunks(rechunked) == honest.payload
    stego.write_bytes(body + MARKER + b"".join(rechunked))
    result = verify(stego)
    assert not result.valid and "canonical chunking" in result.reason


def test_transport_without_framed_chunks_is_rejected(tmp_path, pins) -> None:
    class ChunklessTransport(FakeTransport):
        def extract_chunked_video_payload(self, *arguments, **options):
            extracted = super().extract_chunked_video_payload(*arguments, **options)
            del extracted.chunks
            return extracted

    stego = _embed(tmp_path, pins, b"\x07" * 32)
    result = pipeline.verify_video_proof(
        stego, params=TOY, pins=pins, profile=PROFILE, sync_key=SYNC_KEY,
        transport=ChunklessTransport(), expected_session=b"\x07" * 32, allow_toy_parameters=True,
    )
    assert not result.valid and "canonical chunking" in result.reason


def test_transport_failures_are_reported_as_rejection(tmp_path, pins) -> None:
    class BrokenTransport(FakeTransport):
        def extract_chunked_video_payload(self, *_arguments, **_options):
            raise RuntimeError("ffmpeg failed")

    stego = _embed(tmp_path, pins, b"\x07" * 32)
    result = pipeline.verify_video_proof(
        stego, params=TOY, pins=pins, profile=PROFILE, sync_key=SYNC_KEY,
        transport=BrokenTransport(), expected_session=b"\x07" * 32, allow_toy_parameters=True,
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
        allow_toy_parameters=True,
        sync_key=SYNC_KEY, transport=FakeTransport(), expected_session=b"\x07" * 32,
    )
    assert verify(credential=credential.commitment).valid

    _, stranger_pins, stranger = _registered_setup(issuer, b"d" * 32)
    # Under the stranger's own registered relation, this holder's proof fails.
    assert not verify(credential=stranger.commitment, pins=stranger_pins).valid
    with pytest.raises(ValueError, match="relation id"):
        verify(credential=stranger.commitment)  # pins of one credential, another passed
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
    assert video_proof.self_check_opening(TOY, verified.envelope, embedded.opening)
    nonce = b"\x5a" * 32  # chosen by the recipient
    disclosure = video_proof.create_disclosure(
        TOY, verified.envelope, embedded.opening, statement_id=verified.statement_id, nonce=nonce
    )
    assert video_proof.verify_disclosure_proof(
        TOY, verified.envelope, disclosure, statement_id=verified.statement_id, nonce=nonce, allow_toy_parameters=True
    )
    assert video_proof.decode_disclosure(TOY, disclosure).payload == b"device 42"

    randomness = bdlop.sample_randomness(TOY, b"c" * 32)
    credential = bdlop.commit(TOY, codec.encode_payload(TOY, b"device 42"), randomness)
    in_video = linkage.envelope_commitment(TOY, verified.envelope)
    context = (verified.statement_id, credential.to_bytes(TOY))
    proof = linkage.prove_linkage(
        TOY, context, in_video, embedded.opening.randomness, credential, randomness
    )
    assert linkage.verify_linkage(TOY, context, in_video, credential, proof, allow_toy_parameters=True)
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
    with pytest.raises(ValueError):  # D8: an unreduced commitment cannot be constructed
        dataclasses.replace(credential.commitment, t2=credential.commitment.t2 + TOY.modulus)
    malformed = forged_commitment(credential.commitment.t1, credential.commitment.t2 + TOY.modulus)
    for pinned in (malformed, credential.commitment.to_bytes(TOY)):
        with pytest.raises(ValueError):
            pipeline.verify_video_proof(
                stego, params=TOY, pins=registered_pins, profile=REGISTERED_PROFILE,
                sync_key=SYNC_KEY, transport=FakeTransport(), expected_session=b"\x07" * 32,
                credential=pinned, allow_toy_parameters=True,
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
            transport=GarblingTransport(), allow_toy_parameters=True, **options,
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


# -- pins must match the credential (D6) ---------------------------------- #

def test_in_band_and_registered_pins_are_not_interchangeable(tmp_path, pins, issuer) -> None:
    _, registered_pins, credential = _registered_setup(issuer)
    in_band = _embed(tmp_path, pins, b"\x07" * 32)
    other = tmp_path / "registered"
    other.mkdir()
    registered = _embed_registered(other, registered_pins, credential, b"\x07" * 32)
    with pytest.raises(ValueError, match="relation id"):
        _verify(in_band, registered_pins, expected_session=b"\x07" * 32)
    with pytest.raises(ValueError, match="relation id"):
        pipeline.verify_video_proof(
            registered, params=TOY, pins=pins, profile=REGISTERED_PROFILE, sync_key=SYNC_KEY,
            transport=FakeTransport(), expected_session=b"\x07" * 32,
            credential=credential.commitment, allow_toy_parameters=True,
        )
    with pytest.raises(ValueError):
        _verify(in_band, (pins.relation_id, pins.registry_root), expected_session=b"\x07" * 32)


# -- holder identity in the registered descriptor (D2) -------------------- #

def _holder_setup(issuer, holder_id, seed: bytes = b"h" * 32):
    from src.lattice_zk import bdlop, codec

    randomness = bdlop.sample_randomness(TOY, seed)
    commitment = bdlop.commit(TOY, codec.encode_payload(TOY, b"device 7"), randomness)
    descriptor = pipeline.relation_descriptor(
        TOY, REGISTERED_PROFILE, commitment, holder_id=holder_id
    )
    registry = SignedZkpRelationRegistry.create(epoch=6, relations=[descriptor]).sign(
        issuer[1], signer_id="test-issuer"
    )
    return registry, pipeline.Credential(commitment, randomness)


def _resolve_holder(registry, issuer, commitment, holder_id):
    return pipeline.pins_from_registry(
        registry, issuer[0], TOY, REGISTERED_PROFILE, minimum_epoch=6,
        allow_toy_parameters=True, credential=commitment, holder_id=holder_id,
    )


def test_holder_id_is_covered_by_the_issuer_signature(issuer) -> None:
    registry, credential = _holder_setup(issuer, "alice@example.org")
    pins = _resolve_holder(registry, issuer, credential.commitment, "alice@example.org")
    assert pins.relation_id == pipeline.relation_id(
        TOY, REGISTERED_PROFILE, credential.commitment, holder_id="alice@example.org"
    )
    for wrong in (None, "mallory@example.org", "alice@example.org "):
        with pytest.raises(ValueError, match="not registered"):
            _resolve_holder(registry, issuer, credential.commitment, wrong)
    plain_registry, _ = _holder_setup(issuer, None)
    with pytest.raises(ValueError, match="not registered"):
        _resolve_holder(plain_registry, issuer, credential.commitment, "alice@example.org")


def test_holder_id_default_keeps_the_previous_descriptor() -> None:
    from src.lattice_zk import bdlop, codec

    randomness = bdlop.sample_randomness(TOY, b"h" * 32)
    commitment = bdlop.commit(TOY, codec.encode_payload(TOY, b"device 7"), randomness)
    key = bdlop.derive_key(TOY)
    key_bytes = key.b1_tail.astype(">u8").tobytes() + key.b2_tail.astype(">u8").tobytes()
    plain = pipeline.relation_descriptor(TOY, REGISTERED_PROFILE, commitment)
    assert plain["verifier_key_hash"] == hashlib.sha256(
        key_bytes + commitment.to_bytes(TOY)
    ).hexdigest()
    bound = pipeline.relation_descriptor(TOY, REGISTERED_PROFILE, commitment, holder_id="alice")
    assert bound["verifier_key_hash"] == hashlib.sha256(
        key_bytes + commitment.to_bytes(TOY) + pipeline.holder_id_digest("alice")
    ).hexdigest()
    assert {k: v for k, v in bound.items() if k != "verifier_key_hash"} == {
        k: v for k, v in plain.items() if k != "verifier_key_hash"
    }


@pytest.mark.parametrize(
    "holder_id",
    ["", b"alice", 7, "e\u0301", "x" * (pipeline.MAX_HOLDER_ID_BYTES + 1), "\ud800",
     "\u00e9" * (pipeline.MAX_HOLDER_ID_BYTES // 2 + 1)],
)
def test_malformed_holder_ids_are_refused(holder_id) -> None:
    from src.lattice_zk import bdlop, codec

    randomness = bdlop.sample_randomness(TOY, b"h" * 32)
    commitment = bdlop.commit(TOY, codec.encode_payload(TOY, b"device 7"), randomness)
    with pytest.raises(ValueError):
        pipeline.relation_descriptor(TOY, REGISTERED_PROFILE, commitment, holder_id=holder_id)


def test_holder_id_needs_a_registered_credential() -> None:
    with pytest.raises(ValueError, match="holder id"):
        pipeline.relation_descriptor(TOY, PROFILE, holder_id="alice")
    assert len(pipeline.holder_id_digest("x" * pipeline.MAX_HOLDER_ID_BYTES)) == 32
    assert pipeline.holder_id_digest("alice") != pipeline.holder_id_digest("alicf")


def test_holder_bound_video_verifies_only_with_its_holder_id(tmp_path, issuer) -> None:
    registry, credential = _holder_setup(issuer, "alice")
    pins = _resolve_holder(registry, issuer, credential.commitment, "alice")
    stego = _embed_registered(tmp_path, pins, credential, b"\x07" * 32)
    verify = functools.partial(
        pipeline.verify_video_proof, stego, params=TOY, pins=pins, profile=REGISTERED_PROFILE,
        allow_toy_parameters=True,
        sync_key=SYNC_KEY, transport=FakeTransport(), expected_session=b"\x07" * 32,
        credential=credential.commitment,
    )
    assert verify(holder_id="alice").valid
    for wrong in (None, "bob"):
        with pytest.raises(ValueError, match="relation id"):
            verify(holder_id=wrong)
