"""End-to-end robust mode: embed, re-compress, verify blind, reject tampering."""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path

import numpy as np
import pytest

from src.lattice_zk import bdlop, codec
from src.lattice_zk.params import BDLOP_OPEN_128, TOY
from src.lattice_zk.video_pipeline import Credential
from src.registry.lattice_pq import LatticeSigner
from src.registry.zkp_registry import SignedZkpRelationRegistry
from src.registry.zkp_sessions import SessionChallengeStore
from src.robust import decode as video_io
from src.robust import features
from src.robust import pipeline as robust

ROOT = Path(__file__).resolve().parents[2]
FOREMAN = "data/raw/foreman_cif_300f.y4m"
CONTAINER = "data/raw/container_cif.y4m"


def _ffmpeg(*arguments: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *arguments], check=True)


@pytest.fixture(scope="module")
def short_cover(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("robust") / "foreman30.y4m"
    _ffmpeg("-i", str(ROOT / FOREMAN), "-frames:v", "30", str(path))
    return path


@pytest.fixture(scope="module")
def issuer() -> tuple[bytes, bytes]:
    return LatticeSigner.generate_keypair()


def _pins(issuer, params, profile, credential=None):
    descriptor = robust.relation_descriptor(params, profile, credential)
    registry = SignedZkpRelationRegistry.create(epoch=2, relations=[descriptor]).sign(issuer[1], signer_id="t")
    return robust.pins_from_registry(
        registry, issuer[0], params, profile, minimum_epoch=2,
        allow_toy_parameters=params is TOY, credential=credential,
    )


def _credential(params) -> Credential:
    randomness = bdlop.sample_randomness(params)
    return Credential(bdlop.commit(params, codec.encode_payload(params, b"camera-7"), randomness), randomness)


def _fingerprint(path, spec):
    decoded = video_io.decode(path)
    return features.compute(decoded.y, spec, decoded.u, decoded.v)


@pytest.mark.needs_data(FOREMAN)
def test_fingerprint_is_stable_under_crf23(short_cover, tmp_path) -> None:
    transcoded = tmp_path / "crf23.mp4"
    _ffmpeg("-i", str(short_cover), "-c:v", "libx264", "-crf", "23", str(transcoded))
    spec = features.FingerprintSpec()
    result = features.compare(_fingerprint(short_cover, spec), _fingerprint(transcoded, spec), features.Tolerance())
    assert result.accepted, result.reason
    assert result.max_delta <= 1
    assert result.max_chroma_delta <= 1 and result.chroma_drift_fraction <= 0.05


def test_stream_info_validation() -> None:
    info = video_io.stream_info({"width": 352, "height": 288, "r_frame_rate": "30000/1001", "nb_frames": "12"})
    assert (info.width, info.height, info.frame_rate, info.frames) == (352, 288, "30000/1001", 12)
    estimated = video_io.stream_info({"width": 352, "height": 288, "r_frame_rate": "25/1",
                                      "nb_frames": "N/A", "duration": "2.0"})
    assert estimated.frames == 50
    assert video_io.stream_info({"width": 16, "height": 16}).frames is None
    for broken in (
        {"height": 288},                                   # no width
        {"width": 0, "height": 288},                       # zero width
        {"width": 352, "height": 287},                     # odd height
        {"width": "352x", "height": 288},                  # non-integer
        {"width": 352, "height": 288, "r_frame_rate": "abc"},
        {"width": 352, "height": 288, "r_frame_rate": "25/0"},
        {"width": 352, "height": 288, "duration": "-1"},
        {"width": video_io.MAX_DIMENSION + 2, "height": 288},
    ):
        with pytest.raises(ValueError):
            video_io.stream_info(broken)
    assert video_io.frame_limit(352, 288, 352 * 288 * 3) == 3
    assert video_io.file_url("clip.mp4").startswith("file:") and video_io.file_url("-x.mp4").endswith("-x.mp4")


@pytest.mark.needs_data(FOREMAN)
def test_decode_budget_and_output_hygiene(short_cover, tmp_path, issuer) -> None:
    prefix = video_io.decode(short_cover, max_frames=5)
    assert prefix.frames == 5 and prefix.u.shape == (5, 144, 176)
    budget = 352 * 288 * 10  # ten CIF frames; the clip has thirty
    with pytest.raises(ValueError, match="decode budget"):
        video_io.decode(short_cover, max_luma_samples=budget)
    with pytest.raises(ValueError, match="decode budget"):
        video_io.decode(short_cover, max_frames=11, max_luma_samples=budget)
    with pytest.raises(FileExistsError):  # never overwrite
        video_io.encode(prefix, short_cover, video_io.EncoderSettings(crf=12))
    with pytest.raises(FileNotFoundError):
        video_io.encode(prefix, tmp_path / "missing" / "out.mp4", video_io.EncoderSettings(crf=12))
    with pytest.raises(FileNotFoundError):
        video_io.decode(tmp_path / "absent.mp4")
    profile = robust.RobustProfile.recommended(registered=False)
    pins = _pins(issuer, TOY, profile)
    channel = {"params": TOY, "pins": pins, "profile": profile, "sync_key": robust.public_sync_key(TOY, profile)}
    common = {**channel, "expected_session": b"s" * 32, "allow_toy_parameters": True}
    with pytest.raises(FileExistsError):  # output must be fresh, checked before proving
        robust.embed_robust_proof(short_cover, short_cover, b"x", session_challenge=b"s" * 32, **channel)
    over_budget = robust.verify_robust_proof(short_cover, max_luma_samples=budget, **common)
    assert not over_budget.valid and "decode budget" in over_budget.reason
    garbage = tmp_path / "garbage.mp4"
    garbage.write_bytes(b"not a video" * 100)
    rejected = robust.verify_robust_proof(garbage, **common)
    assert not rejected.valid and rejected.reason.startswith("video rejected")
    dashed = tmp_path / "-starts-with-dash.y4m"
    dashed.write_bytes(short_cover.read_bytes())
    assert video_io.decode(dashed, max_frames=2).frames == 2


@pytest.mark.needs_data(FOREMAN)
def test_toy_in_band_round_trip_survives_recompression(short_cover, tmp_path, issuer) -> None:
    profile = robust.RobustProfile.recommended(registered=False)
    pins = _pins(issuer, TOY, profile)
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=600)
    grant = store.issue(context_binding=robust.session_binding(TOY, pins))
    key = robust.public_sync_key(TOY, profile)
    stego = tmp_path / "stego.mp4"
    result = robust.embed_robust_proof(
        short_cover, stego, b"hidden record", params=TOY, pins=pins, profile=profile,
        session_challenge=grant.challenge, sync_key=key,
    )
    assert result.coded_bits <= result.capacity_bits and result.watermark_psnr > 33
    transcoded = tmp_path / "x265.mkv"
    _ffmpeg("-i", str(stego), "-c:v", "libx265", "-crf", "23", "-x265-params", "log-level=error", str(transcoded))

    def verify(path, **options):
        options.setdefault("session_store", store)
        return robust.verify_robust_proof(
            path, params=TOY, pins=pins, profile=profile, sync_key=key, allow_toy_parameters=True, **options
        )

    accepted = verify(transcoded)
    assert accepted.valid, accepted.reason
    assert accepted.statement_id == result.statement_id
    replay = verify(transcoded)
    assert not replay.valid and "session" in replay.reason
    assert not verify(transcoded, session_store=None, expected_session=b"\x01" * 32).valid
    assert not verify(stego, session_store=None, expected_session=b"x" * 32).valid


@pytest.mark.needs_data(FOREMAN)
def test_toy_registered_profile_rejects_tampering(short_cover, tmp_path, issuer) -> None:
    profile = robust.RobustProfile.recommended(registered=True)
    credential = _credential(TOY)
    pins = _pins(issuer, TOY, profile, credential.commitment)
    key = robust.public_sync_key(TOY, profile)
    session = b"s" * 32
    stego = tmp_path / "stego.mp4"
    robust.embed_robust_proof(
        short_cover, stego, None, params=TOY, pins=pins, profile=profile,
        session_challenge=session, sync_key=key, credential=credential,
    )

    def verify(path):
        return robust.verify_robust_proof(
            path, params=TOY, pins=pins, profile=profile, sync_key=key, expected_session=session,
            credential=credential.commitment, allow_toy_parameters=True,
        )

    assert verify(stego).valid
    decoded = video_io.decode(stego)
    edited_y = decoded.y.copy()
    edited_y[12, 100:164, 100:164] = 255 - edited_y[12, 100:164, 100:164]
    edited = tmp_path / "edited.mp4"
    video_io.encode(dataclasses.replace(decoded, y=edited_y), edited, video_io.EncoderSettings(crf=12))
    rejected = verify(edited)
    assert not rejected.valid
    assert any(cell[0] == 12 for cell in rejected.flagged_cells) or 12 in rejected.bad_frames
    swapped_y = decoded.y.copy()
    swapped_y[[3, 25]] = swapped_y[[25, 3]]
    swapped = tmp_path / "swapped.mp4"
    video_io.encode(dataclasses.replace(decoded, y=swapped_y), swapped, video_io.EncoderSettings(crf=12))
    result = verify(swapped)
    assert not result.valid and {3, 25} <= set(result.bad_frames)
    dropped = tmp_path / "dropped.mp4"
    keep = np.r_[0:10, 11:decoded.frames]
    video_io.encode(
        video_io.DecodedVideo(decoded.y[keep], decoded.u[keep], decoded.v[keep], decoded.frame_rate),
        dropped, video_io.EncoderSettings(crf=12),
    )
    assert not verify(dropped).valid
    # Recolouring: frame 12 is a sampled chroma frame; shift V by 16 over one
    # 128x128-luma cell (64x64 chroma), then shift U by 16 everywhere.
    recoloured_v = decoded.v.copy()
    recoloured_v[12, 0:64, 0:64] = np.clip(recoloured_v[12, 0:64, 0:64].astype(np.int64) + 16, 0, 255)
    regional = tmp_path / "recolour_region.mp4"
    video_io.encode(dataclasses.replace(decoded, v=recoloured_v), regional, video_io.EncoderSettings(crf=12))
    result = verify(regional)
    assert not result.valid and "colour" in result.reason
    assert result.max_chroma_delta >= 2 and (12, 1, 0, 0) in {cell[:4] for cell in result.flagged_chroma_cells}
    shifted_u = np.clip(decoded.u.astype(np.int64) + 16, 0, 255).astype(np.uint8)
    global_shift = tmp_path / "recolour_global.mp4"
    video_io.encode(dataclasses.replace(decoded, u=shifted_u), global_shift, video_io.EncoderSettings(crf=12))
    result = verify(global_shift)
    assert not result.valid and "colour" in result.reason
    assert {cell[1] for cell in result.flagged_chroma_cells} == {0}  # plane 0 is U


def test_verifier_misconfiguration_raises(issuer) -> None:
    profile = robust.RobustProfile.recommended(registered=False)
    pins = _pins(issuer, TOY, profile)
    key = robust.public_sync_key(TOY, profile)
    common = {"params": TOY, "sync_key": key, "expected_session": b"s" * 32}
    with pytest.raises(ValueError):  # toy parameters need an explicit opt-in
        robust.verify_robust_proof("missing.mp4", pins=pins, profile=profile, **common)
    with pytest.raises(ValueError):  # pins resolved for another profile
        robust.verify_robust_proof(
            "missing.mp4", pins=pins, profile=dataclasses.replace(profile, step=48.0),
            allow_toy_parameters=True, **common,
        )
    with pytest.raises(ValueError):  # registered profile without a credential
        robust.verify_robust_proof(
            "missing.mp4", pins=pins, profile=dataclasses.replace(profile, registered=True),
            allow_toy_parameters=True, **common,
        )
    missing = robust.verify_robust_proof(
        "missing.mp4", pins=pins, profile=profile, allow_toy_parameters=True, **common
    )
    assert not missing.valid


def test_too_short_clip_is_refused() -> None:
    with pytest.raises(ValueError):
        robust.channel_plan(BDLOP_OPEN_128, robust.RobustProfile.recommended(registered=False), 30, 288, 352)


@pytest.mark.needs_data(CONTAINER)
def test_production_registered_envelope_survives_x264_crf23(tmp_path, issuer) -> None:
    """300-frame CIF, current production parameters, Main/High CABAC re-encode."""
    profile = robust.RobustProfile.recommended(registered=True)
    credential = _credential(BDLOP_OPEN_128)
    pins = _pins(issuer, BDLOP_OPEN_128, profile, credential.commitment)
    key = robust.public_sync_key(BDLOP_OPEN_128, profile)
    session = b"p" * 32
    stego = tmp_path / "stego.mp4"
    embedded = robust.embed_robust_proof(
        ROOT / CONTAINER, stego, None, params=BDLOP_OPEN_128, pins=pins, profile=profile,
        session_challenge=session, sync_key=key, credential=credential,
    )
    assert embedded.rate == 3
    transcoded = tmp_path / "crf23.mp4"
    _ffmpeg("-i", str(stego), "-c:v", "libx264", "-crf", "23", str(transcoded))
    result = robust.verify_robust_proof(
        transcoded, params=BDLOP_OPEN_128, pins=pins, profile=profile, sync_key=key,
        expected_session=session, credential=credential.commitment,
    )
    assert result.valid, result.reason
    assert result.statement_id == embedded.statement_id
