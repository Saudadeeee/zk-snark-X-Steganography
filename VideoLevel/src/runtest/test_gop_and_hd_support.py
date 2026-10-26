"""GOP > 1 (IDR + P slices) and HD (720p/1080p, multi-slice) support.

* slice-structure policies on hand-built NAL units (``src.transport.gop_policy``);
* carrier-profile identifiers: all-intra unchanged, GOP policy distinct;
* all-intra transport output byte-identical to commit dddb9d5;
* a GOP > 1 lattice-proof round trip on a short synthetic CIF clip: carriers
  recomputed from the stego equal the embedding ones, P slices stay
  byte-identical, a one-byte P-slice change is rejected, the all-intra profile
  refuses the stream and misaligned segment cuts fail closed;
* 720p four-slice and 1080p (cropped) parsing and carrier recomputation.
"""

from __future__ import annotations

import dataclasses
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from src.transport import gop_policy
from src.transport.blind_payload_chunks import pack_payload_chunks
from src.transport.blind_sync import BlindOperatingContract
from src.transport import blind_sync_streaming as transport
from src.core.analysis_cache import (
    clear_video_analysis_cache,
    load_or_build_reconstruction_context,
    load_or_build_video_analysis,
)
from src.registry.lattice_pq import LatticeSigner
from src.lattice_zk import bdlop, codec
from src.lattice_zk import video_pipeline as pipeline
from src.lattice_zk.params import BDLOP_OPEN_128_V1, TOY
from src.registry.zkp_registry import SignedZkpRelationRegistry

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "data" / "external" / "trust_corpus" / "mdn_friday_cif_q22_g1_30f.h264"
CONTRACT = BlindOperatingContract(
    version="stable-carriers-video-only-v1", require_bitstream_patchable=True,
    patchability_headroom=64, max_modifications_per_block=1, stable_carriers_only=True,
)
KEY = bytes(range(32))
GOP = gop_policy.IDR_CARRIERS_INTER_RAW

# Recorded with the code of commit dddb9d5 (before GOP/HD support) on FIXTURE.
BASELINE_PAYLOAD = b"all-intra regression payload for the GOP/HD stream B3 work."
BASELINE = {
    "segments": 3,
    "carriers": 1360,
    "positions_hash": "e7477c66277faef3844509ccf45af06af1d80bf8d22ff794e91040bf2bac0aa4",
    "canonical_video_sha256": "662e84c0a3be72c75001cd4a544a3d583ad6b8f1de382666df0ccb7770200bea",
    "stego_sha256": "96aa73eb9a47fe404dfc7eaa8ffe5064733437d2d6eac1970aa07b438e57ef79",
}
BASELINE_PROFILE_IDS = {
    ("TOY", False): "8b1c4db13725d727ca1cee509a5409b3cd4e9307a1d477374e63ef6d28a3e54d",
    ("TOY", True): "ec341daed1e9bcfeab58f0ef3e1cdce780ad6acd0963058159ef8503f708b28d",
    ("BDLOP_OPEN_128_V1", False): "21f602967f0cf15193353603e2ee7a593df7c37ef143e3a894caf9862c1cf397",
    ("BDLOP_OPEN_128_V1", True): "9735e0f9bb5a20f84d73865852c7d5878ddf129ddc6fd2703c1e1f3382ac2a82",
}
BASELINE_POLICY_HASHES = {
    ("TOY", False): "c758a839b49006f984a9f1d682e3f4872a6dbec94f90d59660532aaa19ee35ff",
    ("TOY", True): "b9b4a0fbe16d76e35e045b92251c09ef14e01ec25922c9043afc6a36c3fb58d9",
    ("BDLOP_OPEN_128_V1", False): "17950622611a7210721dad80568f4e86d3dd5f5a6e0bdf2e381b85612a75f2f8",
    ("BDLOP_OPEN_128_V1", True): "c9d6ec582d00c8873468c957ed9e0bcf6843e95780d0471b43fc239aafd95e12",
}
# Baselines were recorded with the v1 production set before the GOP policy existed.
PARAMETER_SETS = {"TOY": TOY, "BDLOP_OPEN_128_V1": BDLOP_OPEN_128_V1}

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are required",
)


# --------------------------------------------------------------------------- #
# Hand-built Annex B NAL units (header byte + RBSP; no emulation needed).
def _ue(value: int) -> str:
    code = bin(value + 1)[2:]
    return "0" * (len(code) - 1) + code


def _nal(header: int, bits: str) -> bytes:
    bits += "1"  # rbsp_stop_one_bit
    bits += "0" * (-len(bits) % 8)
    return bytes([header]) + int(bits, 2).to_bytes(len(bits) // 8, "big")


def _slice(header: int, first_mb: int, slice_type: int) -> bytes:
    return _nal(header, _ue(first_mb) + _ue(slice_type))


def _sps(profile_idc: int = 66, frame_mbs_only: str = "1") -> bytes:
    """Baseline-shaped SPS for 22 x 18 macroblocks (CIF)."""
    fields = _ue(0) + _ue(0) + _ue(2) + _ue(1) + "0" + _ue(21) + _ue(17) + frame_mbs_only + "10"
    return bytes([0x67, profile_idc, 0xC0, 0x1E]) + _nal(0, fields)[1:]


SPS = _sps()
PPS = b"\x68\xce\x3c\x80"
IDR = b"\x65\x88\x80"  # first_mb 0, slice_type 7 (I)
IDR_MB1 = b"\x65\x42\x20"  # first_mb 1
IDR_MB2 = b"\x65\x62\x20"  # first_mb 2
P_SLICE = b"\x41\x9a"  # non-IDR, first_mb 0, slice_type 5 (P)
I_SLICE = b"\x41\x88\x80"  # non-IDR I slice
B_SLICE = b"\x41\x9e"  # slice_type 6 (B)


def _stream(*nals: bytes) -> bytes:
    return b"".join(b"\x00\x00\x00\x01" + nal for nal in nals)


def _inspect(tmp_path: Path, data: bytes, policy: str) -> gop_policy.SegmentStructure:
    path = tmp_path / "segment.h264"
    path.write_bytes(data)
    return gop_policy.inspect_segment(path, policy)


def test_all_intra_policy_accepts_idr_only_segments(tmp_path) -> None:
    structure = _inspect(tmp_path, _stream(SPS, PPS, IDR, SPS, PPS, IDR), gop_policy.ALL_INTRA)
    assert structure == gop_policy.SegmentStructure(2, 2, 2, 0, 0)


def test_all_intra_policy_rejects_p_slices(tmp_path) -> None:
    with pytest.raises(ValueError, match="non-IDR slice in an all-intra"):
        _inspect(tmp_path, _stream(SPS, PPS, IDR, P_SLICE), gop_policy.ALL_INTRA)


def test_gop_policy_accepts_p_and_non_idr_i_slices(tmp_path) -> None:
    structure = _inspect(tmp_path, _stream(SPS, PPS, IDR, P_SLICE, P_SLICE, I_SLICE), GOP)
    assert structure == gop_policy.SegmentStructure(4, 4, 1, 3, 2)


def test_slices_of_one_picture_share_a_picture(tmp_path) -> None:
    structure = _inspect(tmp_path, _stream(SPS, PPS, IDR, IDR_MB1, IDR_MB2), gop_policy.ALL_INTRA)
    assert (structure.coded_slices, structure.pictures) == (3, 1)


@pytest.mark.parametrize(
    ("nals", "message"),
    [
        ((SPS, PPS, P_SLICE, IDR), "does not start with an IDR"),
        ((SPS, PPS, IDR_MB1), "middle of a picture"),
        ((SPS, PPS, IDR, IDR_MB2, IDR_MB1), "arbitrary slice order"),
        ((SPS, PPS, IDR, B_SLICE), "only I and P slices"),
        ((SPS, PPS, IDR, b"\x42\x9a"), "data-partitioned"),
        ((SPS, PPS, IDR, b"\xc1\x9a"), "forbidden_zero_bit"),
        ((SPS, PPS, IDR, b"\x41\x9a\x00\x00\x03\x05\x80"), "non-canonical emulation"),
        ((SPS, b"\x68\xc5\x80", IDR), "slice groups"),
        ((SPS, b"\x68\xe0", IDR), "CABAC"),
        ((SPS, b"\x68\xce\x3d\x80", IDR), "redundant pictures"),
        ((SPS, PPS, IDR, b"\x68\xce\x3c\xc0", IDR), "parameter sets change"),
        ((IDR, SPS, PPS), "before the segment's SPS and PPS"),
        ((SPS, PPS), "no coded slices"),
        ((_sps(profile_idc=100), PPS, IDR), "not Baseline"),
        ((_sps(frame_mbs_only="0"), PPS, IDR), "interlaced"),
        ((SPS, PPS, _slice(0x65, 396, 7)), "outside the picture"),
        ((SPS, PPS, IDR, _slice(0x41, 1, 5)), "mixes IDR and non-IDR"),
    ],
)
def test_unsupported_slice_structures_are_rejected(tmp_path, nals, message) -> None:
    with pytest.raises(ValueError, match=message):
        _inspect(tmp_path, _stream(*nals), GOP)


def test_bytes_outside_nal_units_are_rejected(tmp_path) -> None:
    stream = _stream(SPS, PPS, IDR)
    with pytest.raises(ValueError, match="before the first start code"):
        _inspect(tmp_path, b"\x07" + stream, gop_policy.ALL_INTRA)
    with pytest.raises(ValueError, match="start code without a NAL unit"):
        _inspect(tmp_path, stream + b"\x00\x00\x01", gop_policy.ALL_INTRA)
    # The leading zeros of a long start code are fine.
    assert _inspect(tmp_path, b"\x00\x00" + stream, gop_policy.ALL_INTRA).pictures == 1


def test_unknown_gop_policy_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown GOP policy"):
        pipeline.CarrierProfile(CONTRACT, gop_policy="gop-8")


# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", sorted(PARAMETER_SETS))
@pytest.mark.parametrize("registered", [False, True])
def test_all_intra_profile_identifiers_are_unchanged(name, registered) -> None:
    params = PARAMETER_SETS[name]
    profile = pipeline.CarrierProfile(
        CONTRACT, registered=registered, codec_policy=pipeline.CODEC_POLICY_V1
    )
    assert profile.profile_id(params).hex() == BASELINE_PROFILE_IDS[(name, registered)]
    assert pipeline.policy_hash(params, profile) == BASELINE_POLICY_HASHES[(name, registered)]
    assert profile.options() == {"frames_per_segment": 100}


def test_gop_policy_gives_distinct_profile_policy_and_relation() -> None:
    intra = pipeline.CarrierProfile(CONTRACT, registered=True)
    inter = pipeline.CarrierProfile(CONTRACT, registered=True, gop_policy=GOP)
    commitment = bdlop.commit(TOY, codec.encode_payload(TOY, b"x"), bdlop.sample_randomness(TOY))
    assert inter.profile_id(TOY) != intra.profile_id(TOY)
    assert pipeline.policy_hash(TOY, inter) != pipeline.policy_hash(TOY, intra)
    assert pipeline.relation_id(TOY, inter, commitment) != pipeline.relation_id(TOY, intra, commitment)
    # codec policy v2 is the default, so the options also name its digest policy
    assert inter.options() == {"frames_per_segment": 100, "gop_policy": GOP, "digest_policy": inter.digest_policy}


# --------------------------------------------------------------------------- #
@needs_ffmpeg
@pytest.mark.skipif(not FIXTURE.is_file(), reason="checked-in all-intra fixture missing")
def test_all_intra_transport_is_byte_identical_to_dddb9d5(tmp_path) -> None:
    chunks = pack_payload_chunks(BASELINE_PAYLOAD, chunk_size=24)
    context = transport.derive_chunked_video_context(
        FIXTURE, chunks, KEY, CONTRACT, frames_per_segment=10
    )
    assert context.segments_used == BASELINE["segments"]
    assert len(context.global_positions) == BASELINE["carriers"]
    assert context.positions_hash == BASELINE["positions_hash"]
    assert context.canonical_video_sha256 == BASELINE["canonical_video_sha256"]
    stego = tmp_path / "stego.h264"
    transport.embed_chunked_video_payload(
        FIXTURE, stego, BASELINE_PAYLOAD, KEY, CONTRACT, frames_per_segment=10, chunk_size=24
    )
    assert hashlib.sha256(stego.read_bytes()).hexdigest() == BASELINE["stego_sha256"]
    extracted = transport.extract_chunked_video_payload(stego, KEY, CONTRACT, frames_per_segment=10)
    assert extracted.payload == BASELINE_PAYLOAD
    assert extracted.positions_hash == BASELINE["positions_hash"]
    assert extracted.canonical_video_sha256 == BASELINE["canonical_video_sha256"]


# --------------------------------------------------------------------------- #
def _encode(path: Path, size: str, frames: int, gop: int, *, noise: int, slices: int = 1) -> Path:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi",
        "-i", f"testsrc2=size={size}:rate=25,noise=alls={noise}:allf=t",
        "-frames:v", str(frames), "-pix_fmt", "yuv420p", "-c:v", "libx264",
        "-profile:v", "baseline", "-coder", "0", "-bf", "0", "-g", str(gop),
        "-keyint_min", str(gop), "-sc_threshold", "0", "-qp", "22", "-threads", "1",
    ]
    if slices > 1:
        command += ["-x264-params", f"slices={slices}"]
    subprocess.run(command + ["-f", "h264", str(path)], check=True, timeout=300)
    return path


def _nal_units(path: Path) -> list[bytes]:
    data = path.read_bytes()
    return [data[start:end] for start, end in gop_policy.nal_unit_spans(data)]


GOP_FRAMES_PER_SEGMENT = 10
GOP_CHUNK_BYTES = 140


@pytest.fixture(scope="module")
def gop_run(tmp_path_factory):
    """Registered TOY proof embedded in a 30-frame CIF clip with GOP 5 (6 IDR, 24 P)."""
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg and ffprobe are required")
    directory = tmp_path_factory.mktemp("gop")
    cover = _encode(directory / "cover_g5.h264", "352x288", 30, 5, noise=30)
    profile = pipeline.CarrierProfile(
        CONTRACT, frames_per_segment=GOP_FRAMES_PER_SEGMENT, chunk_bytes=GOP_CHUNK_BYTES,
        registered=True, gop_policy=GOP,
    )
    randomness = bdlop.sample_randomness(TOY)
    commitment = bdlop.commit(TOY, codec.encode_payload(TOY, b"gop credential"), randomness)
    public, private = LatticeSigner.generate_keypair()
    registry = SignedZkpRelationRegistry.create(
        epoch=1, relations=[pipeline.relation_descriptor(TOY, profile, commitment)]
    ).sign(private, signer_id="gop-test")
    pins = pipeline.pins_from_registry(
        registry, public, TOY, profile, minimum_epoch=1, allow_toy_parameters=True,
        credential=commitment,
    )
    session = bytes(range(32, 64))
    stego = directory / "stego_g5.h264"
    embedded = pipeline.embed_video_proof(
        cover, stego, None, params=TOY, pins=pins, profile=profile, session_challenge=session,
        sync_key=KEY, credential=pipeline.Credential(commitment, randomness),
    )
    clear_video_analysis_cache()

    def verify(path: Path, verifier_profile=profile, verifier_pins=pins):
        return pipeline.verify_video_proof(
            path, params=TOY, pins=verifier_pins, profile=verifier_profile, sync_key=KEY,
            expected_session=session, credential=commitment, allow_toy_parameters=True,
        )

    return {"cover": cover, "stego": stego, "profile": profile, "embedded": embedded,
            "verify": verify, "commitment": commitment, "directory": directory}


def test_gop_stream_round_trip_verifies_blind(gop_run) -> None:
    result = gop_run["verify"](gop_run["stego"])
    assert result.valid, result.reason
    assert result.statement_id == gop_run["embedded"].statement_id
    assert gop_run["embedded"].segments_used == 3


def test_carriers_recomputed_from_the_stego_equal_the_embedding_ones(gop_run) -> None:
    extracted = transport.extract_chunked_video_payload(
        gop_run["stego"], KEY, CONTRACT, frames_per_segment=GOP_FRAMES_PER_SEGMENT, gop_policy=GOP
    )
    embedding = transport.derive_chunked_video_context(
        gop_run["cover"], list(extracted.chunks), KEY, CONTRACT,
        frames_per_segment=GOP_FRAMES_PER_SEGMENT, gop_policy=GOP,
    )
    assert extracted.global_positions == embedding.global_positions
    assert extracted.positions_hash == embedding.positions_hash
    assert extracted.canonical_video_sha256 == embedding.canonical_video_sha256
    # Carriers lie only in IDR pictures (every fifth frame).
    assert {mb // 396 % 5 for mb, _block, _coefficient in extracted.global_positions} == {0}


def test_p_slices_stay_byte_identical(gop_run) -> None:
    cover, stego = _nal_units(gop_run["cover"]), _nal_units(gop_run["stego"])
    assert len(cover) == len(stego)
    p_slices = [(a, b) for a, b in zip(cover, stego) if a[0] & 0x1F == gop_policy.NAL_SLICE_NON_IDR]
    idr = [(a, b) for a, b in zip(cover, stego) if a[0] & 0x1F == gop_policy.NAL_SLICE_IDR]
    assert len(p_slices) == 24 and len(idr) == 6
    assert all(a == b for a, b in p_slices)
    assert any(a != b for a, b in idr)
    assert all(a == b for a, b in zip(cover, stego) if a[0] & 0x1F not in (1, 5))


def test_one_changed_p_slice_byte_rejects_the_proof(gop_run) -> None:
    data = bytearray(gop_run["stego"].read_bytes())
    spans = [span for span in gop_policy.nal_unit_spans(bytes(data))
             if data[span[0]] & 0x1F == gop_policy.NAL_SLICE_NON_IDR]
    start, end = spans[0]  # a P slice of the first (carrier-bearing) segment
    data[(start + end) // 2] ^= 0x10
    tampered = gop_run["directory"] / "tampered_p.h264"
    tampered.write_bytes(bytes(data))
    assert not gop_run["verify"](tampered).valid


def test_canonical_digest_binds_every_p_slice_byte(gop_run) -> None:
    """Digest-level check independent of whether the tampered stream still decodes."""
    from src.transport.video_canonicalization import canonical_h264_digest

    with tempfile.TemporaryDirectory() as directory:
        segments, _counts = transport._split_video_into_segments(
            gop_run["stego"], directory, GOP_FRAMES_PER_SEGMENT
        )
        extracted = transport.extract_chunked_video_payload(
            gop_run["stego"], KEY, CONTRACT, frames_per_segment=GOP_FRAMES_PER_SEGMENT,
            gop_policy=GOP,
        )
        segment = segments[0]
        analysis = load_or_build_video_analysis(segment, use_cache=False, stable_blind_only=True)
        context = load_or_build_reconstruction_context(segment, use_cache=False)
        nal_units = list(context["parser"].nal_units)
        mb_count = context["mb_count_per_slice"]
        positions = [p for p in extracted.global_positions if p[0] < 10 * mb_count]
        reference = canonical_h264_digest(nal_units, analysis[1], positions)
        p_indexes = [i for i, nal in enumerate(nal_units) if int(nal.nal_unit_type) == 1]
        for index in (p_indexes[0], p_indexes[-1]):
            original = nal_units[index]
            rbsp = bytearray(original.rbsp_byte)
            rbsp[len(rbsp) // 2] ^= 0x01
            nal_units[index] = dataclasses.replace(original, rbsp_byte=bytes(rbsp))
            assert canonical_h264_digest(nal_units, analysis[1], positions) != reference
            nal_units[index] = original
        assert canonical_h264_digest(nal_units, analysis[1], positions) == reference
    clear_video_analysis_cache()


def test_all_intra_profile_refuses_a_gop_stream(gop_run, tmp_path) -> None:
    intra = pipeline.CarrierProfile(
        CONTRACT, frames_per_segment=GOP_FRAMES_PER_SEGMENT, chunk_bytes=GOP_CHUNK_BYTES,
        registered=True,
    )
    with pytest.raises(ValueError, match="non-IDR slice in an all-intra"):
        transport.derive_chunked_video_context(
            gop_run["cover"], pack_payload_chunks(b"x" * 40, chunk_size=20), KEY, CONTRACT,
            frames_per_segment=GOP_FRAMES_PER_SEGMENT,
        )
    # Under the all-intra profile, verification of the GOP stego rejects (no exception).
    public, private = LatticeSigner.generate_keypair()
    registry = SignedZkpRelationRegistry.create(
        epoch=1, relations=[pipeline.relation_descriptor(TOY, intra, gop_run["commitment"])]
    ).sign(private, signer_id="gop-test")
    pins = pipeline.pins_from_registry(
        registry, public, TOY, intra, minimum_epoch=1, allow_toy_parameters=True,
        credential=gop_run["commitment"],
    )
    result = gop_run["verify"](gop_run["stego"], verifier_profile=intra, verifier_pins=pins)
    assert not result.valid and "all-intra" in result.reason


def test_segment_cuts_off_idr_boundaries_fail_closed(gop_run) -> None:
    with pytest.raises(ValueError, match="IDR"):
        transport.extract_chunked_video_payload(
            gop_run["stego"], KEY, CONTRACT, frames_per_segment=7, gop_policy=GOP
        )


def test_gop_aligned_segments_each_start_with_an_idr(gop_run) -> None:
    with tempfile.TemporaryDirectory() as directory:
        segments, counts = transport._split_video_into_segments(
            gop_run["stego"], directory, GOP_FRAMES_PER_SEGMENT
        )
        structures = transport._inspect_segments(segments, counts, GOP)
    assert counts == [10, 10, 10]
    assert [(s.pictures, s.idr_slices, s.p_slices) for s in structures] == [(10, 2, 8)] * 3


# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def hd_clips(tmp_path_factory):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg and ffprobe are required")
    directory = tmp_path_factory.mktemp("hd")
    return {
        "720p_4slices": _encode(directory / "hd720_s4.h264", "1280x720", 2, 1, noise=6, slices=4),
        "1080p": _encode(directory / "hd1080.h264", "1920x1080", 1, 1, noise=6),
    }


def test_720p_multi_slice_pictures_parse_with_one_slot_per_slice(hd_clips) -> None:
    clip = hd_clips["720p_4slices"]
    structure = gop_policy.inspect_segment(clip, gop_policy.ALL_INTRA)
    assert (structure.pictures, structure.coded_slices) == (2, 8)
    clear_video_analysis_cache()
    coefficients, frame_data, *_rest, safe = load_or_build_video_analysis(
        clip, use_cache=False, stable_blind_only=True
    )
    context = load_or_build_reconstruction_context(clip, use_cache=False)
    assert context["mb_count_per_slice"] == 80 * 45
    assert sorted(frame_data) == [slot * 3600 for slot in range(8)]
    assert safe and {mb // 3600 for mb, _b, _c in safe} == set(range(8))
    rows = {(mb % 3600) // 80 for mb, _b, _c in safe}
    assert min(rows) < 12 and max(rows) > 33  # carriers span the slices' rows
    clear_video_analysis_cache()


def test_720p_multi_slice_segments_get_disjoint_global_positions(hd_clips, tmp_path) -> None:
    clip = hd_clips["720p_4slices"]
    payload = b"multi-slice 720p two-segment payload"
    stego = tmp_path / "stego720.h264"
    transport.embed_chunked_video_payload(
        clip, stego, payload, KEY, CONTRACT, frames_per_segment=1, chunk_size=20
    )
    extracted = transport.extract_chunked_video_payload(stego, KEY, CONTRACT, frames_per_segment=1)
    assert extracted.payload == payload and extracted.segments_used == 2
    positions = extracted.global_positions
    assert len(set(positions)) == len(positions)
    # The second segment starts after the first segment's four slice slots.
    first_segment = [p for p in positions if p[0] < 4 * 3600]
    assert 0 < len(first_segment) < len(positions)
    assert min(p[0] for p in positions[len(first_segment):]) >= 4 * 3600
    recomputed = transport.derive_chunked_video_context(
        clip, list(extracted.chunks), KEY, CONTRACT, frames_per_segment=1
    )
    assert recomputed.global_positions == positions
    assert recomputed.canonical_video_sha256 == extracted.canonical_video_sha256


def test_1080p_cropped_stream_parses_and_recomputes_carriers(hd_clips, tmp_path) -> None:
    clip = hd_clips["1080p"]
    clear_video_analysis_cache()
    context = load_or_build_reconstruction_context(clip, use_cache=False)
    sps = context["sps"]
    assert (sps.pic_width_in_mbs_minus1 + 1, sps.pic_height_in_map_units_minus1 + 1) == (120, 68)
    payload = b"1080p payload"
    stego = tmp_path / "stego1080.h264"
    transport.embed_chunked_video_payload(
        clip, stego, payload, KEY, CONTRACT, frames_per_segment=1, chunk_size=64
    )
    extracted = transport.extract_chunked_video_payload(stego, KEY, CONTRACT, frames_per_segment=1)
    assert extracted.payload == payload
    recomputed = transport.derive_chunked_video_context(
        clip, list(extracted.chunks), KEY, CONTRACT, frames_per_segment=1
    )
    assert recomputed.global_positions == extracted.global_positions
    assert max(mb for mb, _b, _c in extracted.global_positions) >= 396
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", str(stego)],
        capture_output=True, text=True, check=True,
    )
    assert probe.stdout.strip() == "1920,1080"
    clear_video_analysis_cache()
