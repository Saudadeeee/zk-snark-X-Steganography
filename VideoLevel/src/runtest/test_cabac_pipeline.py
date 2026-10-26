"""Lattice video proof over native CABAC streams, end to end through ``video_pipeline``.

* TOY registered proof, fixed ZKBC v1 chunks, Main profile all-intra;
* TOY in-band proof, adaptive ZKBC v2 chunks, High profile (8x8 transform);
* TOY registered proof, GOP 8 High profile with B frames (IDR carriers, inter slices raw);
* production parameters (``BDLOP_OPEN_128``), registered and in-band, on 300 frames.

Each run verifies blind from the stego alone; the carriers the verifier
recomputes equal the embedder's; a P-slice bit flip, a changed non-carrier
coefficient, a non-canonical slice encoding and a replayed session are rejected.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.bitstream.cabac import AnnexBUnit, collect_parameter_sets, decode_slice, encode_slice, join_annexb, split_annexb
from src.lattice_zk import bdlop, codec, video_proof
from src.lattice_zk import video_pipeline as pipeline
from src.lattice_zk.params import BDLOP_OPEN_128, TOY
from src.registry.lattice_pq import LatticeSigner
from src.registry.zkp_registry import SignedZkpRelationRegistry
from src.registry.zkp_sessions import SessionChallengeStore
from src.runtest.cabac_media import cabac_clip, psnr_y, strict_decode_errors
from src.transport import cabac_sync
from src.transport.adaptive_chunks import AdaptiveChunkPlan
from src.transport.gop_policy import IDR_CARRIERS_INTER_RAW

KEY = bytes(range(32))
SESSION = bytes(range(32, 64))
CONTRACT = cabac_sync.CabacMagnitudeContract()


def _run(directory: Path, clip: str, params, *, registered: bool, frames_per_segment: int,
         plan: AdaptiveChunkPlan | None = None, chunk_bytes: int | None = None,
         gop_policy: str = "all-intra") -> dict:
    cover = cabac_clip(clip)
    options = {} if chunk_bytes is None else {"chunk_bytes": chunk_bytes}
    profile = pipeline.CarrierProfile(
        CONTRACT, frames_per_segment=frames_per_segment, registered=registered,
        gop_policy=gop_policy, codec_policy=pipeline.CODEC_POLICY_CABAC_V1, chunk_plan=plan, **options,
    )
    toy = params is TOY
    credential = randomness = None
    if registered:
        randomness = bdlop.sample_randomness(params)
        credential = bdlop.commit(params, codec.encode_payload(params, b"cabac credential"), randomness)
    public, private = LatticeSigner.generate_keypair()
    registry = SignedZkpRelationRegistry.create(
        epoch=1, relations=[pipeline.relation_descriptor(params, profile, credential)]
    ).sign(private, signer_id="cabac-test")
    pins = pipeline.pins_from_registry(registry, public, params, profile, minimum_epoch=1,
                                       allow_toy_parameters=toy, credential=credential)
    stego = directory / f"stego_{clip}"
    payload = None if registered else b"hidden CABAC payload"
    start = time.perf_counter()
    embedded = pipeline.embed_video_proof(
        cover, stego, payload, params=params, pins=pins, profile=profile, session_challenge=SESSION,
        sync_key=KEY, credential=None if credential is None else pipeline.Credential(credential, randomness),
    )
    embed_seconds = time.perf_counter() - start

    def verify(path: Path, **overrides):
        options = {"expected_session": SESSION, **overrides}
        return pipeline.verify_video_proof(
            path, params=params, pins=pins, profile=profile, sync_key=KEY, credential=credential,
            allow_toy_parameters=toy, **options,
        )

    return {"cover": cover, "stego": stego, "profile": profile, "pins": pins, "params": params,
            "embedded": embedded, "verify": verify, "embed_seconds": embed_seconds,
            "directory": directory}


@pytest.fixture(scope="module")
def registered_chunked(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("cabac-reg"), "foreman_cif_cabac_main_g1_30f.h264", TOY,
                registered=True, frames_per_segment=10, chunk_bytes=300)


@pytest.fixture(scope="module")
def inband_adaptive(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("cabac-inband"), "foreman_cif_cabac_high_g1_30f.h264", TOY,
                registered=False, frames_per_segment=10, plan=AdaptiveChunkPlan())


@pytest.fixture(scope="module")
def gop8(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("cabac-gop"), "foreman_cif_cabac_high_g8_48f.h264", TOY,
                registered=True, frames_per_segment=16, plan=AdaptiveChunkPlan(min_chunk_bytes=32),
                gop_policy=IDR_CARRIERS_INTER_RAW)


def _tampered(run: dict, name: str, edit) -> Path:
    """Apply ``edit(units, sps, pps)`` to the stego's units and write the result."""
    units = split_annexb(run["stego"].read_bytes())
    sps, pps = collect_parameter_sets(units)
    edit(units, sps, pps)
    path = run["directory"] / name
    path.write_bytes(join_annexb(units))
    return path


def _change_non_carrier_coefficient(units, sps, pps) -> None:
    for index, unit in enumerate(units):
        if unit.nal_type != 5:
            continue
        decoded = decode_slice(unit.nal, sps, pps)
        for mb in decoded.macroblocks:
            for block in [b for b in (mb.luma or []) if b]:
                ones = [i for i, value in enumerate(block) if abs(value) == 1]
                if ones:
                    block[ones[0]] = -block[ones[0]]  # sign of a level-1 (never a carrier)
                    units[index] = AnnexBUnit(unit.prefix, encode_slice(decoded))
                    return
    raise AssertionError("no level-1 coefficient found")


def _make_first_idr_non_canonical(units, sps, pps) -> None:
    for index, unit in enumerate(units):
        if unit.nal_type == 5 and not unit.nal[-1] & 1:
            # Set an rbsp_alignment_zero_bit, as libx264's flush does: decodable, not canonical.
            units[index] = AnnexBUnit(unit.prefix, unit.nal[:-1] + bytes([unit.nal[-1] | 1]))
            return
    raise AssertionError("no IDR slice with alignment bits found")


def _flip_p_slice_bit(units, sps, pps) -> None:
    for index, unit in enumerate(units):
        if unit.nal_type == 1 and len(unit.nal) > 16:
            data = bytearray(unit.nal)
            data[len(data) // 2] ^= 0x10
            units[index] = AnnexBUnit(unit.prefix, bytes(data))
            return
    raise AssertionError("no inter slice found")


# --- TOY runs ----------------------------------------------------------------------

def test_registered_chunked_round_trip_verifies_blind(registered_chunked) -> None:
    run = registered_chunked
    result = run["verify"](run["stego"])
    assert result.valid, result.reason
    assert result.statement_id == run["embedded"].statement_id
    assert strict_decode_errors(run["stego"]) == ""
    average, worst = psnr_y(run["cover"], run["stego"])
    print(f"registered/chunked: {run['embedded'].carriers_used} carriers in "
          f"{run['embedded'].segments_used} segments, PSNR-Y {average:.2f} dB (worst {worst:.2f}), "
          f"embed {run['embed_seconds']:.1f} s")
    assert worst >= 35.0


def test_carriers_recomputed_from_the_stego_equal_the_embedder_ones(registered_chunked) -> None:
    run = registered_chunked
    profile = run["profile"]
    extracted = cabac_sync.extract_chunked_video_payload(run["stego"], KEY, CONTRACT, **profile.options())
    derived = cabac_sync.derive_chunked_video_context(
        run["cover"], list(extracted.chunks), KEY, CONTRACT, **profile.options()
    )
    assert extracted.global_positions == derived.global_positions
    assert extracted.positions_hash == derived.positions_hash
    assert extracted.canonical_video_sha256 == derived.canonical_video_sha256
    assert len(extracted.payload) == video_proof.envelope_size(TOY, registered=True)


def test_changed_non_carrier_coefficient_is_rejected(registered_chunked) -> None:
    run = registered_chunked
    path = _tampered(run, "tamper_coefficient.h264", _change_non_carrier_coefficient)
    assert strict_decode_errors(path) == ""  # still a valid, canonical H.264 stream
    assert not run["verify"](path).valid


def test_non_canonical_slice_encoding_is_rejected(registered_chunked) -> None:
    run = registered_chunked
    path = _tampered(run, "tamper_noncanonical.h264", _make_first_idr_non_canonical)
    result = run["verify"](path)
    assert not result.valid and "canonical" in result.reason


def test_replayed_session_is_rejected(registered_chunked, tmp_path) -> None:
    run = registered_chunked
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=600)
    stego = run["directory"] / "replay_stego.h264"
    profile = run["profile"]
    randomness = bdlop.sample_randomness(TOY)
    commitment = bdlop.commit(TOY, codec.encode_payload(TOY, b"replay credential"), randomness)
    public, private = LatticeSigner.generate_keypair()
    registry = SignedZkpRelationRegistry.create(
        epoch=1, relations=[pipeline.relation_descriptor(TOY, profile, commitment)]
    ).sign(private, signer_id="cabac-replay")
    pins = pipeline.pins_from_registry(registry, public, TOY, profile, minimum_epoch=1,
                                       allow_toy_parameters=True, credential=commitment)
    grant = store.issue(context_binding=pipeline.session_binding(TOY, pins))
    pipeline.embed_video_proof(
        run["cover"], stego, None, params=TOY, pins=pins, profile=profile,
        session_challenge=grant.challenge, sync_key=KEY,
        credential=pipeline.Credential(commitment, randomness),
    )

    def verify():
        return pipeline.verify_video_proof(
            stego, params=TOY, pins=pins, profile=profile, sync_key=KEY, session_store=store,
            credential=commitment, allow_toy_parameters=True,
        )

    first = verify()
    assert first.valid, first.reason
    assert not verify().valid


def test_inband_adaptive_round_trip(inband_adaptive) -> None:
    run = inband_adaptive
    result = run["verify"](run["stego"])
    assert result.valid, result.reason
    assert result.envelope is not None and run["embedded"].opening is not None
    assert run["embedded"].chunk_layout and run["embedded"].segment_capacity_bits
    assert strict_decode_errors(run["stego"]) == ""
    average, worst = psnr_y(run["cover"], run["stego"])
    print(f"in-band/adaptive: layout {run['embedded'].chunk_layout}, PSNR-Y {average:.2f} dB "
          f"(worst {worst:.2f})")
    assert worst >= 35.0
    assert not run["verify"](_tampered(run, "inband_tamper.h264", _change_non_carrier_coefficient)).valid


def test_gop8_round_trip_with_b_frames_and_raw_inter_slices(gop8) -> None:
    run = gop8
    result = run["verify"](run["stego"])
    assert result.valid, result.reason
    cover_units = split_annexb(run["cover"].read_bytes())
    stego_units = split_annexb(run["stego"].read_bytes())
    assert len(cover_units) == len(stego_units)
    inter = [(a, b) for a, b in zip(cover_units, stego_units) if a.nal_type == 1]
    assert len(inter) == 42 and all(a == b for a, b in inter)
    assert all(a == b for a, b in zip(cover_units, stego_units) if a.nal_type not in (1, 5))
    extracted = cabac_sync.extract_adaptive_video_payload(
        run["stego"], KEY, CONTRACT, plan=run["profile"].chunk_plan, **run["profile"].options()
    )
    assert {mb // 396 % 8 for mb, _block, _coefficient in extracted.global_positions} == {0}
    assert strict_decode_errors(run["stego"]) == ""


def test_gop8_p_slice_bit_flip_is_rejected(gop8) -> None:
    run = gop8
    assert not run["verify"](_tampered(run, "gop_tamper_p.h264", _flip_p_slice_bit)).valid


def test_all_intra_profile_refuses_the_gop_stream(gop8) -> None:
    run = gop8
    profile = pipeline.CarrierProfile(
        CONTRACT, frames_per_segment=16, registered=True, codec_policy=pipeline.CODEC_POLICY_CABAC_V1,
        chunk_plan=AdaptiveChunkPlan(min_chunk_bytes=32),
    )
    with pytest.raises(ValueError, match="non-IDR slice in an all-intra"):
        cabac_sync.extract_adaptive_video_payload(
            run["stego"], KEY, CONTRACT, plan=profile.chunk_plan, **profile.options()
        )


def test_cabac_profile_identifiers_differ_from_cavlc_ones() -> None:
    cabac = pipeline.CarrierProfile(CONTRACT, codec_policy=pipeline.CODEC_POLICY_CABAC_V1)
    assert pipeline.codec_policy_id(pipeline.CODEC_POLICY_CABAC_V1) not in {
        pipeline.codec_policy_id(pipeline.CODEC_POLICY_V1), pipeline.codec_policy_id(pipeline.CODEC_POLICY_V2)
    }
    assert pipeline._default_transport(cabac) is cabac_sync
    assert pipeline._default_adaptive_transport(cabac) is cabac_sync
    with pytest.raises(ValueError, match="CABAC transport only implements"):
        cabac_sync.extract_chunked_video_payload(
            cabac_clip("foreman_cif_cabac_main_g1_30f.h264"), KEY, CONTRACT, digest_policy="carrier-normalized-v1"
        )


# --- production parameters -----------------------------------------------------------

@pytest.mark.parametrize("registered", [True, False], ids=["registered", "in-band"])
def test_production_parameters_end_to_end(tmp_path, registered) -> None:
    run = _run(tmp_path, "foreman_cif_cabac_high_g1_300f.h264", BDLOP_OPEN_128, registered=registered,
               frames_per_segment=100, plan=AdaptiveChunkPlan())
    start = time.perf_counter()
    result = run["verify"](run["stego"])
    verify_seconds = time.perf_counter() - start
    assert result.valid, result.reason
    assert strict_decode_errors(run["stego"]) == ""
    average, worst = psnr_y(run["cover"], run["stego"])
    embedded = run["embedded"]
    print(f"{BDLOP_OPEN_128.name} {'registered' if registered else 'in-band'}: envelope "
          f"{embedded.envelope_bytes} B, {embedded.carriers_used} carriers, layout {embedded.chunk_layout}, "
          f"PSNR-Y {average:.2f} dB (worst {worst:.2f}), embed {run['embed_seconds']:.1f} s, "
          f"verify {verify_seconds:.1f} s")
    assert worst >= 35.0
    assert not run["verify"](_tampered(run, "prod_tamper.h264", _change_non_carrier_coefficient)).valid
