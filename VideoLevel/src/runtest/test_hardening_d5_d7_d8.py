"""Code-check findings D5, D7, D8 and Q12 (docs/paper/sections/security_appendix.tex).

* D7: the hedged mask key is domain-separated per protocol and parameter set;
  ``bdlop-open-128-v1`` keeps the frozen untagged derivation (``kat_v1.json``);
  verification does not depend on which derivation the prover used.
* D8: ``Commitment`` rejects non-canonical coefficients at construction and
  holds read-only copies; verifiers still re-check objects built around it.
* Q12: every application-level verifier refuses a parameter set below
  production strength unless ``allow_toy_parameters=True``.
* D5: codec policy v2 (opt-in, new identifiers) tags raw-segment digests,
  hashes the full RBSP of carrier IDR NAL units and pins the segmentation;
  codec policy v1 stays byte-identical.  A zero bit appended after the RBSP
  stop bit of a carrier NAL unit is accepted under v1 and rejected under v2,
  on the digest and through the real H.264 transport.
"""

from __future__ import annotations

import dataclasses
import hashlib
import shutil
import struct
import tempfile
from pathlib import Path

import numpy as np
import pytest

from src.transport import blind_sync_streaming as transport
from src.transport import gop_policy
from src.transport.blind_payload_chunks import pack_payload_chunks
from src.transport.blind_sync import BlindOperatingContract
from src.core.analysis_cache import clear_video_analysis_cache
from src.registry.lattice_pq import LatticeSigner
from src.lattice_zk import binary_proof as bp
from src.lattice_zk import bdlop, codec, equality_proof, linkage, opening_proof, video_proof
from src.lattice_zk import video_pipeline as pipeline
from src.lattice_zk.params import BDLOP_OPEN_128, BDLOP_OPEN_128_V1, BDLOP_OPEN_128_V2, TOY
from src.runtest.test_latticezk_bdlop import forged_commitment
from src.transport.video_canonicalization import (
    DIGEST_V1,
    DIGEST_V2,
    canonical_video_sha256,
    raw_segment_sha256,
)
from src.registry.zkp_registry import SignedZkpRelationRegistry
from src.registry.zkp_sessions import SessionChallengeStore

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "data" / "external" / "trust_corpus" / "mdn_friday_cif_q22_g1_30f.h264"
KEY = bytes(range(32))
STATEMENT = b"hardening statement"
CONTRACT = BlindOperatingContract(
    version="stable-carriers-video-only-v1", require_bitstream_patchable=True,
    patchability_headroom=64, max_modifications_per_block=1, stable_carriers_only=True,
)
T1_CONTRACT = BlindOperatingContract(
    version="t1-sign-video-only-v2", signbit_only=True, require_bitstream_patchable=True,
    patchability_headroom=64, max_modifications_per_block=1, stable_carriers_only=True,
)

# Recorded with the code of commit 10bce11, before any change in this file's scope.
V1_CODEC_POLICY_ID = "5a9b4d07e349774ef1fa999e8ac0c06e1c59141511bb96928430d4bf7dc5b65b"
V1_IDENTIFIERS = {  # (parameter set, registered) -> (profile id, policy hash)
    ("V2", False): ("9f35b9e80d376184ba66839fc3fb5e1b7b794d2fc96469f566903c379e1c9532",
                    "3415b75925d011b76bbf94e231339d4fb8a6df4f90096cfa34ffd9b5663b69f0"),
    ("V2", True): ("93f63501a96424681ccb85c0c5c4ce221e5297f9baee9e6e1ed677b8a567734c",
                   "04a5054df944eb6be7271c82a621bb9ecd5e0cdfa8a07a410e2e0353b63a016d"),
    ("TOY", True): ("ec341daed1e9bcfeab58f0ef3e1cdce780ad6acd0963058159ef8503f708b28d",
                    "b9b4a0fbe16d76e35e045b92251c09ef14e01ec25922c9043afc6a36c3fb58d9"),
}
PARAMETER_SETS = {"TOY": TOY, "V1": BDLOP_OPEN_128_V1, "V2": BDLOP_OPEN_128_V2}
# One chunk in the first of three 10-frame segments; the other two are raw.
V1_RAW_TAIL = {
    "payload": b"d5 raw tail",
    "chunk_size": 64,
    "carriers": 384,
    "positions_hash": "fd2ef433b53cfbcc6a9743dca9bc50b833fd59cfe0a8599427b5549797b87a69",
    "canonical_video_sha256": "22e4db21a6375cc55f7960d1aef0664b99b20f064f78e02396c195a7f1fe44b2",
}

needs_fixture = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None or not FIXTURE.is_file(),
    reason="ffmpeg, ffprobe and the checked-in CIF fixture are required",
)


def _legacy_mask_key(entropy: bytes, statement: bytes, *context: bytes | np.ndarray) -> bytes:
    """The pre-D7 derivation, written out independently of the library."""
    digest = hashlib.sha3_256(entropy + struct.pack(">Q", len(statement)) + statement)
    for item in context:
        encoded = item if isinstance(item, bytes) else item.astype(">i8").tobytes()
        digest.update(struct.pack(">Q", len(encoded)) + encoded)
    return digest.digest()


def _committed(params=TOY, payload: bytes = b"hardening", seed: bytes = b"r" * 32):
    randomness = bdlop.sample_randomness(params, seed)
    return randomness, bdlop.commit(params, codec.encode_payload(params, payload), randomness)


# =========================================================================== #
# D7: hedged mask key
# =========================================================================== #

def test_hedged_mask_key_is_domain_separated_by_protocol_and_parameter_set() -> None:
    randomness, _ = _committed()
    entropy = b"e" * 32
    keys = {
        opening_proof.hedged_mask_key(
            entropy, STATEMENT, b"c", randomness, protocol=protocol, parameter_id=parameter_id
        )
        for protocol in sorted(opening_proof.HEDGE_PROTOCOLS)
        for parameter_id in (TOY.parameter_id, BDLOP_OPEN_128_V2.parameter_id)
    }
    assert len(keys) == 2 * len(opening_proof.HEDGE_PROTOCOLS)
    assert _legacy_mask_key(entropy, STATEMENT, b"c", randomness) not in keys


def test_tagged_key_starts_with_the_domain_tag() -> None:
    randomness, _ = _committed()
    tagged = opening_proof.hedged_mask_key(
        b"e" * 32, STATEMENT, randomness,
        protocol=opening_proof.HEDGE_OPENING, parameter_id=TOY.parameter_id,
    )
    prefix = opening_proof._HEDGE_DOMAIN
    for label in (opening_proof.HEDGE_OPENING, TOY.parameter_id):
        prefix += struct.pack(">Q", len(label)) + label
    # Without the tag the input is the legacy one, i.e. it starts with the entropy.
    expected = hashlib.sha3_256(
        prefix + b"e" * 32 + struct.pack(">Q", len(STATEMENT)) + STATEMENT
        + struct.pack(">Q", randomness.size * 8) + randomness.astype(">i8").tobytes()
    ).digest()
    assert tagged == expected
    assert prefix.startswith(b"zkstego/lattice-zk/hedged-mask-key/v2\0")


def test_only_v1_opening_and_equality_keep_the_untagged_derivation() -> None:
    randomness, _ = _committed(BDLOP_OPEN_128_V1)
    legacy = _legacy_mask_key(b"e" * 32, STATEMENT, b"c", randomness)
    for protocol in (opening_proof.HEDGE_OPENING, opening_proof.HEDGE_EQUALITY):
        assert opening_proof.uses_untagged_hedge(BDLOP_OPEN_128_V1.parameter_id, protocol)
        assert opening_proof.hedged_mask_key(
            b"e" * 32, STATEMENT, b"c", randomness,
            protocol=protocol, parameter_id=BDLOP_OPEN_128_V1.parameter_id,
        ) == legacy
    assert not opening_proof.uses_untagged_hedge(
        BDLOP_OPEN_128_V1.parameter_id, opening_proof.HEDGE_BINARY
    )
    for params in (BDLOP_OPEN_128_V2, TOY):
        assert not opening_proof.uses_untagged_hedge(params.parameter_id, opening_proof.HEDGE_OPENING)


def test_hedged_mask_key_rejects_unknown_protocols_and_malformed_ids() -> None:
    randomness, _ = _committed()
    for protocol, parameter_id in (
        (b"bdlop-other", TOY.parameter_id), ("bdlop-open", TOY.parameter_id),
        (opening_proof.HEDGE_OPENING, TOY.parameter_id[:31]), (opening_proof.HEDGE_OPENING, None),
    ):
        with pytest.raises(ValueError):
            opening_proof.hedged_mask_key(
                b"e" * 32, STATEMENT, randomness, protocol=protocol, parameter_id=parameter_id
            )
    with pytest.raises(TypeError):  # the protocol label is mandatory
        opening_proof.hedged_mask_key(b"e" * 32, STATEMENT, randomness)  # type: ignore[call-arg]


def test_explicit_mask_seeds_go_through_the_tagged_derivation(monkeypatch) -> None:
    """The KAT path is the production path: same seed, both derivations differ."""
    randomness, commitment = _committed()
    tagged = opening_proof.prove_with_stats(
        TOY, STATEMENT, commitment, randomness, mask_seed=b"m" * 32
    ).proof
    monkeypatch.setattr(opening_proof, "hedged_mask_key", _legacy_kw(opening_proof.hedged_mask_key))
    legacy = opening_proof.prove_with_stats(
        TOY, STATEMENT, commitment, randomness, mask_seed=b"m" * 32
    ).proof
    assert tagged != legacy
    assert opening_proof.verify(TOY, STATEMENT, commitment, tagged)
    assert opening_proof.verify(TOY, STATEMENT, commitment, legacy)


def _legacy_kw(_tagged):
    def legacy(entropy, statement, *context, protocol, parameter_id):
        assert protocol in opening_proof.HEDGE_PROTOCOLS and len(parameter_id) == 32
        return _legacy_mask_key(entropy, statement, *context)

    return legacy


def test_equality_and_binary_verification_are_prover_independent(monkeypatch) -> None:
    first_r, first = _committed(seed=b"a" * 32)
    second_r, second = _committed(seed=b"b" * 32)
    tagged = equality_proof.prove_with_stats(
        TOY, STATEMENT, first, first_r, second, second_r, mask_seed=b"m" * 32
    ).proof
    message = np.array([index & 1 for index in range(TOY.degree)], dtype=np.int64)
    binary_r = bp.sample_randomness(bp.BINARY_TOY, b"q" * 32)
    binary_c = bp.commit(bp.BINARY_TOY, message, binary_r)
    binary_tagged = bp.prove_with_stats(
        bp.BINARY_TOY, STATEMENT, binary_c, message, binary_r, mask_seed=b"m" * 32
    ).proof
    monkeypatch.setattr(equality_proof, "hedged_mask_key", _legacy_kw(None))
    monkeypatch.setattr(bp, "hedged_mask_key", _legacy_kw(None))
    legacy = equality_proof.prove_with_stats(
        TOY, STATEMENT, first, first_r, second, second_r, mask_seed=b"m" * 32
    ).proof
    binary_legacy = bp.prove_with_stats(
        bp.BINARY_TOY, STATEMENT, binary_c, message, binary_r, mask_seed=b"m" * 32
    ).proof
    assert tagged != legacy and binary_tagged != binary_legacy
    for proof in (tagged, legacy):
        assert equality_proof.verify(TOY, STATEMENT, first, second, proof)
        assert not equality_proof.verify(TOY, STATEMENT + b"!", first, second, proof)
    for proof in (binary_tagged, binary_legacy):
        assert bp.verify(bp.BINARY_TOY, STATEMENT, binary_c, proof)


def test_v1_known_answer_vectors_are_unchanged() -> None:
    import json

    from research.bdlop_params.kat import generate

    recorded = json.loads((ROOT / "research" / "bdlop_params" / "kat_v1.json").read_text("utf-8"))
    assert generate("BDLOP_OPEN_128_V1")["vectors"] == recorded["vectors"]


# =========================================================================== #
# D8: canonical commitments at construction
# =========================================================================== #

def test_commitment_with_unreduced_coefficients_cannot_be_built() -> None:
    _, commitment = _committed(BDLOP_OPEN_128_V2)
    q = BDLOP_OPEN_128_V2.modulus
    unreduced = commitment.t2.copy()
    unreduced[3] = q  # in [q, 2^30): the packer alone would accept it
    codec.pack_uints(unreduced, BDLOP_OPEN_128_V2.modulus_bits)
    for t1, t2 in (
        (commitment.t1, unreduced), (commitment.t1 - q, commitment.t2),
        (commitment.t1[:-1], commitment.t2), (commitment.t1.astype(np.float32), commitment.t2),
        (commitment.t1, commitment.t2.tolist()),
    ):
        with pytest.raises((TypeError, ValueError)):
            bdlop.Commitment(t1, t2, params=BDLOP_OPEN_128_V2)
    with pytest.raises(TypeError):
        bdlop.Commitment(commitment.t1, commitment.t2, params=None)  # type: ignore[arg-type]


def test_every_construction_path_yields_frozen_canonical_commitments() -> None:
    _, commitment = _committed()
    decoded = bdlop.Commitment.from_bytes(TOY, commitment.to_bytes(TOY))
    copied = dataclasses.replace(commitment)
    for candidate in (commitment, decoded, copied, commitment.normalized(TOY)):
        assert candidate.is_canonical(TOY)
        for values in (candidate.t1, candidate.t2):
            assert values.dtype == np.int64 and not values.flags.writeable
        assert candidate.to_bytes(TOY) == commitment.to_bytes(TOY)
    assert commitment.normalized(TOY) is commitment
    assert not commitment.is_canonical(BDLOP_OPEN_128_V2)  # other shapes


def test_objects_built_around_the_constructor_are_still_refused() -> None:
    randomness, commitment = _committed()
    proof = opening_proof.prove(TOY, STATEMENT, commitment, randomness)
    writable = commitment.t2.copy()
    forged = forged_commitment(commitment.t1, writable)
    assert opening_proof.verify(TOY, STATEMENT, forged, proof)  # canonical values: rebuilt copy
    writable[0] = TOY.modulus + 1
    assert not forged.is_canonical(TOY)
    assert not opening_proof.verify(TOY, STATEMENT, forged, proof)
    with pytest.raises(ValueError):
        forged.to_bytes(TOY)
    assert not forged_commitment(commitment.t1, commitment.t2, params="TOY").is_canonical(TOY)


# =========================================================================== #
# Q12: production strength at every application-level verifier
# =========================================================================== #

def _toy_statement(params=TOY) -> video_proof.VideoStatement:
    pins = video_proof.VerifierPins(b"R" * 32, b"G" * 32, 1, b"C" * 32, b"P" * 32)
    return video_proof.build_statement(
        params, pins, b"S" * 32, carrier_count=8, positions_hash=b"H" * 32,
        canonical_video_sha256=b"V" * 32,
    )


def test_toy_parameters_are_refused_unless_explicitly_allowed() -> None:
    statement = _toy_statement()
    data, opening = video_proof.create_envelope(TOY, statement, b"payload")
    randomness, commitment = _committed()
    registered = video_proof.create_registered_envelope(TOY, statement, commitment, randomness)
    disclosure = video_proof.create_disclosure(
        TOY, data, opening, statement_id=statement.statement_id, nonce=b"N" * 32
    )
    pair = [_committed(seed=seed) for seed in (b"a" * 32, b"b" * 32)]
    link = linkage.prove_linkage(TOY, (b"ctx",), pair[0][1], pair[0][0], pair[1][1], pair[1][0])
    calls = {
        "verify_envelope": lambda **flag: video_proof.verify_envelope(TOY, statement, data, **flag),
        "verify_registered_envelope": lambda **flag: video_proof.verify_registered_envelope(
            TOY, statement, commitment, registered, **flag),
        "verify_disclosure_proof": lambda **flag: video_proof.verify_disclosure_proof(
            TOY, data, disclosure, statement_id=statement.statement_id, nonce=b"N" * 32, **flag),
        "verify_commitment_disclosure": lambda **flag: video_proof.verify_commitment_disclosure(
            TOY, video_proof.decode_envelope(TOY, data).commitment, disclosure,
            statement_id=statement.statement_id, nonce=b"N" * 32, **flag),
        "verify_linkage": lambda **flag: linkage.verify_linkage(
            TOY, (b"ctx",), pair[0][1], pair[1][1], link, **flag),
    }
    for name, call in calls.items():
        with pytest.raises(ValueError, match="production strength"):
            call()
        with pytest.raises(ValueError, match="production strength"):
            call(allow_toy_parameters=False)
        with pytest.raises(TypeError):
            call(allow_toy_parameters=1)
        assert call(allow_toy_parameters=True) is True, name


def test_production_parameters_verify_without_the_flag() -> None:
    statement = _toy_statement(BDLOP_OPEN_128)
    data, _ = video_proof.create_envelope(BDLOP_OPEN_128, statement, b"payload")
    assert video_proof.verify_envelope(BDLOP_OPEN_128, statement, data)
    video_proof.require_verifier_parameters(BDLOP_OPEN_128_V1)
    with pytest.raises(TypeError):
        video_proof.require_verifier_parameters("bdlop-open-128-v2")


def test_hand_built_toy_pins_are_refused_by_verify_video_proof(tmp_path) -> None:
    """Q12: the bypass was VerifierPins built by hand, skipping pins_from_registry."""
    profile = pipeline.CarrierProfile(CONTRACT)
    pins = video_proof.VerifierPins(
        relation_id=pipeline.relation_id(TOY, profile), registry_root=b"G" * 32,
        registry_epoch=1, codec_policy_id=pipeline.codec_policy_id(),
        carrier_profile_id=profile.profile_id(TOY),
    )
    missing = tmp_path / "never-read.h264"
    with pytest.raises(ValueError, match="production strength"):
        pipeline.verify_video_proof(
            missing, params=TOY, pins=pins, profile=profile, sync_key=KEY,
            expected_session=b"S" * 32,
        )
    with pytest.raises(ValueError, match="production strength"):
        pipeline.pins_from_registry(
            SignedZkpRelationRegistry.create(
                epoch=1, relations=[pipeline.relation_descriptor(TOY, profile)]
            ), b"", TOY, profile, minimum_epoch=1,
        )


# =========================================================================== #
# D5: codec policy v2; v1 byte-identical
# =========================================================================== #

def test_v1_codec_policy_identifiers_are_byte_identical() -> None:
    assert pipeline.codec_policy_id(pipeline.CODEC_POLICY_V1).hex() == V1_CODEC_POLICY_ID
    # v2 is the default for new profiles; v1 stays selectable with its old identifiers.
    assert pipeline.CODEC_POLICY == pipeline.CODEC_POLICY_V2
    assert pipeline.codec_policy_id() == pipeline.codec_policy_id(pipeline.CODEC_POLICY_V2)
    assert pipeline.CarrierProfile(CONTRACT).codec_policy == pipeline.CODEC_POLICY_V2
    for (name, registered), (profile_id, policy) in V1_IDENTIFIERS.items():
        params = PARAMETER_SETS[name]
        profile = pipeline.CarrierProfile(
            CONTRACT, registered=registered, codec_policy=pipeline.CODEC_POLICY_V1
        )
        assert profile.profile_id(params).hex() == profile_id
        assert pipeline.policy_hash(params, profile) == policy
        assert profile.options() == {"frames_per_segment": 100}


def test_v2_codec_policy_gives_new_identifiers_everywhere() -> None:
    _, commitment = _committed()
    old = pipeline.CarrierProfile(CONTRACT, registered=True, codec_policy=pipeline.CODEC_POLICY_V1)
    new = pipeline.CarrierProfile(CONTRACT, registered=True, codec_policy=pipeline.CODEC_POLICY_V2)
    assert new == pipeline.CarrierProfile(CONTRACT, registered=True)  # the default
    assert pipeline.codec_policy_id(pipeline.CODEC_POLICY_V2) != pipeline.codec_policy_id(pipeline.CODEC_POLICY_V1)
    assert new.profile_id(TOY) != old.profile_id(TOY)
    assert pipeline.policy_hash(TOY, new) != pipeline.policy_hash(TOY, old)
    assert pipeline.relation_id(TOY, new, commitment) != pipeline.relation_id(TOY, old, commitment)
    assert new.options() == {"frames_per_segment": 100, "digest_policy": DIGEST_V2}
    assert new.digest_policy == DIGEST_V2 and old.digest_policy == DIGEST_V1
    with pytest.raises(ValueError, match="codec policy"):
        pipeline.CarrierProfile(CONTRACT, codec_policy="h264-baseline-cavlc/whatever")
    with pytest.raises(ValueError, match="codec policy"):
        pipeline.codec_policy_id("v3")


def test_pins_with_another_codec_policy_are_refused(tmp_path) -> None:
    _, commitment = _committed()
    new = pipeline.CarrierProfile(CONTRACT, registered=True, codec_policy=pipeline.CODEC_POLICY_V2)
    pins = video_proof.VerifierPins(
        relation_id=pipeline.relation_id(TOY, new, commitment), registry_root=b"G" * 32,
        registry_epoch=1,
        codec_policy_id=pipeline.codec_policy_id(pipeline.CODEC_POLICY_V1),  # v1 id, v2 profile
        carrier_profile_id=new.profile_id(TOY),
    )
    with pytest.raises(ValueError, match="codec policy"):
        pipeline.verify_video_proof(
            tmp_path / "never-read.h264", params=TOY, pins=pins, profile=new, sync_key=KEY,
            expected_session=b"S" * 32, credential=commitment, allow_toy_parameters=True,
        )


def test_raw_segment_digest_is_tagged_only_under_v2(tmp_path) -> None:
    segment = tmp_path / "raw.h264"
    data = b"\x00\x00\x00\x01\x09\xf0" * 7
    segment.write_bytes(data)
    assert raw_segment_sha256(segment) == hashlib.sha256(data).hexdigest()
    tagged = hashlib.sha256(
        b"zkstego/canonical-h264-raw-segment/v2\0" + struct.pack(">Q", len(data)) + data
    ).hexdigest()
    assert raw_segment_sha256(segment, DIGEST_V2) == tagged != hashlib.sha256(data).hexdigest()
    with pytest.raises(ValueError):
        raw_segment_sha256(segment, "v3")


def test_combined_digest_v1_is_unchanged_and_v2_types_segments() -> None:
    digests = [(10, "11" * 32), (10, "22" * 32)]
    legacy = hashlib.sha256(b"zkstego/canonical-h264-segmented/v1\x00")
    legacy.update(struct.pack(">II", 10, 2))
    for index, (frames, value) in enumerate(digests):
        legacy.update(struct.pack(">II", index, frames) + bytes.fromhex(value))
    assert transport._combine_segment_digests(digests, 10) == legacy.hexdigest()
    one = transport._combine_segment_digests(digests, 10, DIGEST_V2, carrier_segments=1)
    two = transport._combine_segment_digests(digests, 10, DIGEST_V2, carrier_segments=2)
    assert len({legacy.hexdigest(), one, two}) == 3
    for bad in (None, 3, -1, True):
        with pytest.raises(ValueError):
            transport._combine_segment_digests(digests, 10, DIGEST_V2, carrier_segments=bad)


# -- real H.264 ---------------------------------------------------------------- #

def _cut(target: Path, frames: int) -> Path:
    data = FIXTURE.read_bytes()
    starts = transport.access_unit_offsets(data)
    target.write_bytes(data[: starts[frames]] if frames < len(starts) else data)
    return target


def _carrier_cut(directory: Path) -> tuple[Path, list[tuple[int, int, int]]]:
    from src.transport.blind_sync import derive_blind_positions_operating_contract

    cover = _cut(directory / "cover_10f.h264", 10)
    positions, _ = derive_blind_positions_operating_contract(
        str(cover), KEY, 256, CONTRACT, use_analysis_cache=False
    )
    clear_video_analysis_cache()
    return cover, list(positions)


def _zero_extend_carrier_nal(source: Path, target: Path, positions) -> int:
    """Append one zero byte (eight zero bits after the RBSP stop bit) to a carrier IDR NAL."""
    data = source.read_bytes()
    spans = gop_policy.nal_unit_spans(data)
    idr = [span for span in spans if data[span[0]] & 0x1F == gop_policy.NAL_SLICE_IDR]
    frame = max(position[0] for position in positions) // 396  # CIF: 396 MBs per picture
    start, end = idr[frame]
    # A three-byte next start code would become a four-byte one, which v1 hashes.
    assert end == len(data) or data[end:end + 4] == b"\x00\x00\x00\x01"
    assert data[end - 1] != 0  # the RBSP ends with its stop bit
    target.write_bytes(data[:end] + b"\x00" + data[end:])
    return end


@needs_fixture
def test_v1_and_v2_digests_on_a_carrier_cut(tmp_path) -> None:
    cover, positions = _carrier_cut(tmp_path)
    tampered = tmp_path / "zero_extended.h264"
    offset = _zero_extend_carrier_nal(cover, tampered, positions)
    v1 = canonical_video_sha256(cover, positions)
    v2 = canonical_video_sha256(cover, positions, digest_policy=DIGEST_V2)
    assert v1 != v2
    assert canonical_video_sha256(cover, positions, digest_policy=DIGEST_V1) == v1
    # Zero bits after the stop bit: invisible to v1, bound by v2.
    assert canonical_video_sha256(tampered, positions) == v1
    assert canonical_video_sha256(tampered, positions, digest_policy=DIGEST_V2) != v2
    # Turning an alignment zero into a one moves the stop bit; both policies see it.
    data = bytearray(cover.read_bytes())
    last = data[offset - 1]
    if last & 1 == 0:
        data[offset - 1] = last | 1
        flipped = tmp_path / "flipped.h264"
        flipped.write_bytes(bytes(data))
        assert canonical_video_sha256(flipped, positions) != v1
        assert canonical_video_sha256(flipped, positions, digest_policy=DIGEST_V2) != v2
    # Leading zero bytes before the first start code are counted by v2 only.
    padded = tmp_path / "padded.h264"
    padded.write_bytes(b"\x00" + cover.read_bytes())
    assert canonical_video_sha256(padded, positions) == v1
    assert canonical_video_sha256(padded, positions, digest_policy=DIGEST_V2) != v2
    clear_video_analysis_cache()


@needs_fixture
def test_v2_refuses_non_canonical_escaping_and_unmodeled_nal_types(tmp_path) -> None:
    cover, positions = _carrier_cut(tmp_path)
    data = cover.read_bytes()
    unknown = tmp_path / "unknown_nal.h264"
    unknown.write_bytes(data + b"\x00\x00\x00\x01\x0d\x80")  # type 13, not modeled
    canonical_video_sha256(unknown, positions)  # v1 hashes it as "UNKNOWN"
    with pytest.raises(ValueError, match="not modeled"):
        canonical_video_sha256(unknown, positions, digest_policy=DIGEST_V2)
    escaped = tmp_path / "superfluous_escape.h264"
    escaped.write_bytes(data + b"\x00\x00\x00\x01\x06\x05\x00\x00\x03\x05\x80")
    with pytest.raises(ValueError, match="emulation prevention"):
        canonical_video_sha256(escaped, positions, digest_policy=DIGEST_V2)
    clear_video_analysis_cache()


@needs_fixture
def test_pinned_partition_matches_the_segmenter_and_detects_deviations(tmp_path) -> None:
    data = FIXTURE.read_bytes()
    starts = transport.access_unit_offsets(data)
    assert len(starts) == 30 and starts[0] == 0
    with tempfile.TemporaryDirectory() as directory:
        segments, counts = transport._split_video_into_segments(
            FIXTURE, directory, 10, digest_policy=DIGEST_V2
        )
        assert counts == [10, 10, 10]
        assert b"".join(segment.read_bytes() for segment in segments) == data
        transport.require_pinned_partition(FIXTURE, segments, 10)
        first, second = segments[0].read_bytes(), segments[1].read_bytes()
        # Move the boundary by one NAL unit: still decodable pieces, but not the rule.
        spans = gop_policy.nal_unit_spans(second)
        cut = spans[1][0] - 4
        segments[0].write_bytes(first + second[:cut])
        segments[1].write_bytes(second[cut:])
        with pytest.raises(ValueError, match="annexb-access-unit-exact-partition-v1"):
            transport.require_pinned_partition(FIXTURE, segments, 10)
        with pytest.raises(ValueError, match="segments for"):
            transport.require_pinned_partition(FIXTURE, segments[:2], 10)


@needs_fixture
def test_v1_transport_digest_is_byte_identical_and_v2_differs() -> None:
    chunks = pack_payload_chunks(V1_RAW_TAIL["payload"], chunk_size=V1_RAW_TAIL["chunk_size"])
    contexts = {
        policy: transport.derive_chunked_video_context(
            FIXTURE, chunks, KEY, CONTRACT, frames_per_segment=10, digest_policy=policy
        )
        for policy in (DIGEST_V1, DIGEST_V2)
    }
    clear_video_analysis_cache()
    v1, v2 = contexts[DIGEST_V1], contexts[DIGEST_V2]
    assert len(v1.global_positions) == V1_RAW_TAIL["carriers"]
    assert v1.positions_hash == V1_RAW_TAIL["positions_hash"]
    assert v1.canonical_video_sha256 == V1_RAW_TAIL["canonical_video_sha256"]
    assert v2.global_positions == v1.global_positions  # carrier placement is unchanged
    assert v2.canonical_video_sha256 != v1.canonical_video_sha256


# -- full pipeline: TOY registered proof, real transport ----------------------- #

FRAMES_PER_SEGMENT = 10
CHUNK_BYTES = 600  # the TOY registered envelope (413 B) fits one chunk


@pytest.fixture(scope="module")
def stego_runs(tmp_path_factory):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None or not FIXTURE.is_file():
        pytest.skip("ffmpeg, ffprobe and the checked-in CIF fixture are required")
    directory = tmp_path_factory.mktemp("hardening")
    randomness = bdlop.sample_randomness(TOY, b"h" * 32)
    commitment = bdlop.commit(TOY, codec.encode_payload(TOY, b"hardening credential"), randomness)
    public, private = LatticeSigner.generate_keypair()
    runs = {}
    for policy in (pipeline.CODEC_POLICY_V1, pipeline.CODEC_POLICY_V2):
        profile = pipeline.CarrierProfile(
            T1_CONTRACT, frames_per_segment=FRAMES_PER_SEGMENT, chunk_bytes=CHUNK_BYTES,
            registered=True, codec_policy=policy,
        )
        registry = SignedZkpRelationRegistry.create(
            epoch=1, relations=[pipeline.relation_descriptor(TOY, profile, commitment)]
        ).sign(private, signer_id="hardening-test")
        pins = pipeline.pins_from_registry(
            registry, public, TOY, profile, minimum_epoch=1, allow_toy_parameters=True,
            credential=commitment,
        )
        session = hashlib.sha256(policy.encode()).digest()
        tag = "v2" if policy == pipeline.CODEC_POLICY_V2 else "v1"
        stego = directory / f"stego_{tag}.h264"
        embedded = pipeline.embed_video_proof(
            FIXTURE, stego, None, params=TOY, pins=pins, profile=profile,
            session_challenge=session, sync_key=KEY,
            credential=pipeline.Credential(commitment, randomness),
        )
        clear_video_analysis_cache()

        def verify(path: Path, *, profile=profile, pins=pins, session=session, **options):
            arguments = {"expected_session": session} if not options else options
            return pipeline.verify_video_proof(
                path, params=TOY, pins=pins, profile=profile, sync_key=KEY,
                credential=commitment, allow_toy_parameters=True, **arguments,
            )

        runs[tag] = {"stego": stego, "embedded": embedded, "verify": verify, "pins": pins,
                     "profile": profile, "session": session}
    return runs


def _carrier_frames(run) -> list[int]:
    extracted = transport.extract_chunked_video_payload(
        run["stego"], KEY, T1_CONTRACT, **run["profile"].options()
    )
    clear_video_analysis_cache()
    return sorted({mb // 396 for mb, _block, _coefficient in extracted.global_positions})


def _zero_extend(run, directory: Path) -> Path:
    frame = _carrier_frames(run)[-1]
    data = run["stego"].read_bytes()
    idr = [s for s in gop_policy.nal_unit_spans(data) if data[s[0]] & 0x1F == gop_policy.NAL_SLICE_IDR]
    _start, end = idr[frame]
    assert data[end:end + 4] == b"\x00\x00\x00\x01"
    tampered = directory / f"{run['stego'].stem}_zero_extended.h264"
    tampered.write_bytes(data[:end] + b"\x00" + data[end:])
    return tampered


def test_both_codec_policies_verify_blind(stego_runs) -> None:
    for tag, run in stego_runs.items():
        result = run["verify"](run["stego"])
        assert result.valid, (tag, result.reason)
        assert result.statement_id == run["embedded"].statement_id
        assert run["embedded"].segments_used == 1
    assert (stego_runs["v1"]["embedded"].statement_id
            != stego_runs["v2"]["embedded"].statement_id)


def test_zero_bits_after_the_stop_bit_are_accepted_by_v1_and_rejected_by_v2(stego_runs, tmp_path) -> None:
    """D5(b) through the real transport: the documented v1 gap, closed by v2."""
    v1 = stego_runs["v1"]
    accepted = v1["verify"](_zero_extend(v1, tmp_path))
    assert accepted.valid, accepted.reason
    v2 = stego_runs["v2"]
    rejected = v2["verify"](_zero_extend(v2, tmp_path))
    assert not rejected.valid
    assert "rejected" in rejected.reason


def test_v2_raw_segment_tamper_and_replay_are_rejected(stego_runs, tmp_path) -> None:
    run = stego_runs["v2"]
    data = bytearray(run["stego"].read_bytes())
    spans = [s for s in gop_policy.nal_unit_spans(bytes(data)) if data[s[0]] & 0x1F == 5]
    start, end = spans[-1]  # last picture: a carrier-free raw segment
    data[(start + end) // 2] ^= 0x01
    tampered = tmp_path / "raw_segment_flip.h264"
    tampered.write_bytes(bytes(data))
    assert not run["verify"](tampered).valid
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=3600)
    binding = pipeline.session_binding(TOY, run["pins"])
    profile = run["profile"]
    randomness = bdlop.sample_randomness(TOY, b"h" * 32)
    commitment = bdlop.commit(TOY, codec.encode_payload(TOY, b"hardening credential"), randomness)
    grant = store.issue(context_binding=binding)
    fresh = tmp_path / "fresh_v2.h264"
    pipeline.embed_video_proof(
        FIXTURE, fresh, None, params=TOY, pins=run["pins"], profile=profile,
        session_challenge=grant.challenge, sync_key=KEY,
        credential=pipeline.Credential(commitment, randomness),
    )
    clear_video_analysis_cache()
    assert run["verify"](fresh, session_store=store).valid
    assert not run["verify"](fresh, session_store=store).valid  # one-use challenge


def test_a_v1_video_does_not_verify_under_the_v2_profile(stego_runs) -> None:
    v1, v2 = stego_runs["v1"], stego_runs["v2"]
    assert not v2["verify"](v1["stego"]).valid
    assert not v1["verify"](v2["stego"]).valid
