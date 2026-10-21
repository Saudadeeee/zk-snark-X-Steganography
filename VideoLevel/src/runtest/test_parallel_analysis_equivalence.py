"""Equivalence of the accelerated analysis/transport path with the reference.

The serial analysis (``ZKSTEGO_ANALYSIS_WORKERS=1``) is the reference
implementation. Every accelerated result must match it bit for bit, including
dictionary insertion order, and the blind transport must reproduce golden
values recorded from commit ea96d60 (before any acceleration) on the
checked-in 30-frame fixture.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.transport import blind_sync_streaming as streaming
from src.transport.blind_payload_chunks import pack_payload_chunks
from src.transport.blind_sync import BlindOperatingContract
from src.core import analysis_cache, parallel_analysis

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "data" / "external" / "trust_corpus" / "mdn_friday_cif_q22_g1_30f.h264"
ENCODED_SOURCES = (
    ROOT / "data" / "encoded" / "container_cif_q22_g1.h264",
    ROOT / "data" / "encoded" / "foreman_cif_q22_g1.h264",
)
PROFILES = {
    "stable": {"stable_blind_only": True},
    "signbit": {"signbit_only": True},
    "full": {},
}
MAGNITUDE = BlindOperatingContract(
    version="stable-carriers-video-only-v1",
    require_bitstream_patchable=True,
    patchability_headroom=64,
    max_modifications_per_block=1,
    stable_carriers_only=True,
)
T1_SIGN = BlindOperatingContract(
    version="t1-sign-video-only-v2",
    signbit_only=True,
    require_bitstream_patchable=True,
    patchability_headroom=64,
    max_modifications_per_block=1,
    stable_carriers_only=True,
)
GOLDEN_KEY = hashlib.sha256(b"golden-key").digest()
GOLDEN_PAYLOAD = hashlib.shake_256(b"golden-payload").digest(30)
# Recorded with the unmodified transport at ea96d60 on FIXTURE,
# frames_per_segment=10, chunk_size=12 (three chunks in three segments).
GOLDEN_FIXTURE = {
    "magnitude": {
        "positions_sha": "ce2369d0a837944e5a4d7941a750edc1797243079c3e867ea5b443eb81dad2e6",
        "positions_count": 1128,
        "positions_hash": "7f111b51547471b925281a2c279de031827ffe31833f401e49de18543a3129fb",
        "canonical": "11734a844bd122c5020e8ae25a13baf20ba49e43a1711bc0cb4693299e4a587e",
        "output_sha256": "a2864902f30d3ff04095acca78b03c1e7feee1f3ec63581f295d4775d3166702",
    },
    "t1": {
        "positions_sha": "3c8e0e2acf192afa335ec805529db89951bf6772d85d6cda661b6d687b77402d",
        "positions_count": 1128,
        "positions_hash": "e7bee418ab3a73eaf118507cb4e76464120be871397e6bbf4961107216938014",
        "canonical": "7fe0939220237716774121046c57d9001062382156470d7279e89e4e2b7f62a7",
        "output_sha256": "f3db627d1527e61c3eb7c91b1bd8a842e70c0546fcdc496da84ae4fa58a31a67",
    },
}
CONTRACTS = {"magnitude": MAGNITUDE, "t1": T1_SIGN}

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are required",
)


def _ordered(value):
    """Structure-preserving form that also compares dict insertion order."""
    if isinstance(value, dict):
        return ("dict", [(_ordered(key), _ordered(item)) for key, item in value.items()])
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, [_ordered(item) for item in value])
    if isinstance(value, (bytes, bytearray)):
        return ("bytes", bytes(value))
    return (type(value).__name__, value)


def _ffmpeg(*arguments: str) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *arguments],
        check=True,
        capture_output=True,
    )


def _synthetic_clip(path: Path, frames: int, size: str = "176x144") -> Path:
    _ffmpeg(
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25,noise=alls=30:allf=t",
        "-frames:v", str(frames), "-c:v", "libx264", "-profile:v", "baseline",
        "-coder", "0", "-g", "1", "-qp", "22", "-pix_fmt", "yuv420p", "-f", "h264", str(path),
    )
    return path


def _cut(source: Path, path: Path, frames: int) -> Path:
    _ffmpeg("-i", str(source), "-c:v", "copy", "-frames:v", str(frames), "-f", "h264", str(path))
    return path


def _analyse(video: Path, profile: str, workers: str, monkeypatch) -> tuple:
    monkeypatch.setenv(parallel_analysis.WORKERS_ENV, workers)
    analysis_cache.clear_video_analysis_cache()
    try:
        data = analysis_cache.load_or_build_video_analysis(video, **PROFILES[profile])
        context = analysis_cache.load_or_build_reconstruction_context(video)
    finally:
        analysis_cache.clear_video_analysis_cache()
    return data, context


def _assert_same_analysis(video: Path, profile: str, monkeypatch) -> None:
    serial, serial_context = _analyse(video, profile, "1", monkeypatch)
    parallel, parallel_context = _analyse(video, profile, "4", monkeypatch)
    assert _ordered(parallel) == _ordered(serial)
    assert parallel_context["mb_count_per_slice"] == serial_context["mb_count_per_slice"]
    # Coefficient vectors stay shared with frame_verified_data, and each frame
    # keeps the parser's own RBSP object, exactly as in the serial build.
    for analysis, context in ((serial, serial_context), (parallel, parallel_context)):
        coefficients, frame_data = analysis[0], analysis[1]
        offsets = sorted(frame_data)
        for mb, block, levels in coefficients[:: max(1, len(coefficients) // 50)]:
            frame = max(offset for offset in offsets if offset <= mb)
            assert frame_data[frame][1][(mb, block)] is levels
        idr_rbsp = [nal.rbsp_byte for nal in context["nal_units"] if int(nal.nal_unit_type) == 5]
        assert [frame_data[offset][2] for offset in offsets] == idr_rbsp
        assert all(
            frame_data[offset][2] is rbsp for offset, rbsp in zip(offsets, idr_rbsp)
        )


@requires_ffmpeg
@pytest.mark.parametrize("profile", ["stable", "signbit", "full"])
def test_parallel_analysis_matches_serial_on_synthetic_clip(tmp_path, monkeypatch, profile):
    video = _synthetic_clip(tmp_path / "synthetic.h264", frames=6)
    _assert_same_analysis(video, profile, monkeypatch)


@requires_ffmpeg
@pytest.mark.parametrize("profile", ["stable", "signbit"])
def test_parallel_analysis_matches_serial_on_real_clip(tmp_path, monkeypatch, profile):
    sources = [path for path in (*ENCODED_SOURCES, FIXTURE) if path.is_file()]
    if not sources:
        pytest.skip("no real H.264 clip is available")
    video = _cut(sources[0], tmp_path / "real.h264", frames=8)
    _assert_same_analysis(video, profile, monkeypatch)


@requires_ffmpeg
def test_parallel_analysis_defers_non_self_contained_frames(tmp_path, monkeypatch):
    video = _synthetic_clip(tmp_path / "small.h264", frames=4, size="64x64")
    parser = analysis_cache.H264BitstreamParser(str(video))
    parser.parse()
    context = analysis_cache._build_reconstruction_context(video, parser=parser)
    assert parallel_analysis.build_parallel_analysis(
        video, parser, context, stable_blind_only=True, signbit_only=False, workers=2
    ) is not None
    # A smaller picture size would map blocks of one IDR onto another frame's
    # offset; that case must be left to the serial reference.
    shrunk = {**context, "mb_count_per_slice": int(context["mb_count_per_slice"]) // 2}
    assert parallel_analysis.build_parallel_analysis(
        video, parser, shrunk, stable_blind_only=True, signbit_only=False, workers=2
    ) is None


@requires_ffmpeg
def test_worker_failure_falls_back_to_serial(tmp_path, monkeypatch):
    video = _synthetic_clip(tmp_path / "small.h264", frames=4, size="64x64")
    reference, _ = _analyse(video, "stable", "1", monkeypatch)
    monkeypatch.setattr(
        parallel_analysis,
        "_worker_command",
        lambda: [sys.executable, "-c", "import sys; sys.exit(3)"],
    )
    fallback, _ = _analyse(video, "stable", "4", monkeypatch)
    assert _ordered(fallback) == _ordered(reference)


@requires_ffmpeg
def test_parked_analysis_is_reused_only_for_identical_content(tmp_path, monkeypatch):
    monkeypatch.setenv(parallel_analysis.WORKERS_ENV, "1")
    first = _synthetic_clip(tmp_path / "first.h264", frames=2, size="64x64")
    copy = tmp_path / "copy.h264"
    shutil.copyfile(first, copy)
    other = _synthetic_clip(tmp_path / "other.h264", frames=3, size="64x64")
    analysis_cache.clear_video_analysis_cache()
    try:
        built = analysis_cache.load_or_build_video_analysis(first, stable_blind_only=True)
        assert analysis_cache.park_video_analysis_for_content_reuse()
        assert analysis_cache.load_or_build_video_analysis(copy, stable_blind_only=True) is built
        assert list(analysis_cache._VIDEO_ANALYSIS_CACHE) == [str(copy.resolve())]
        # Parking is single use; a different profile or content rebuilds.
        assert analysis_cache.park_video_analysis_for_content_reuse()
        assert analysis_cache.load_or_build_video_analysis(first, signbit_only=True) is not built
        analysis_cache.load_or_build_video_analysis(first, stable_blind_only=True)
        assert analysis_cache.park_video_analysis_for_content_reuse()
        rebuilt = analysis_cache.load_or_build_video_analysis(other, stable_blind_only=True)
        assert rebuilt is not built
        assert list(analysis_cache._VIDEO_ANALYSIS_CACHE) == [str(other.resolve())]
    finally:
        analysis_cache.clear_video_analysis_cache()


def _transport_record(video: Path, contract, output: Path, *, payload: bytes,
                      frames_per_segment: int, chunk_size: int) -> dict:
    chunks = pack_payload_chunks(payload, chunk_size=chunk_size)
    context = streaming.derive_chunked_video_context(
        video, chunks, GOLDEN_KEY, contract, frames_per_segment=frames_per_segment
    )
    streaming.embed_chunked_video_payload(
        video, output, payload, GOLDEN_KEY, contract,
        frames_per_segment=frames_per_segment, chunk_size=chunk_size,
    )
    extracted = streaming.extract_chunked_video_payload(
        output, GOLDEN_KEY, contract, frames_per_segment=frames_per_segment
    )
    assert extracted.payload == payload
    assert extracted.global_positions == context.global_positions
    assert extracted.positions_hash == context.positions_hash
    assert extracted.canonical_video_sha256 == context.canonical_video_sha256
    return {
        "positions": context.global_positions,
        "positions_sha": hashlib.sha256(
            json.dumps(context.global_positions).encode()
        ).hexdigest(),
        "positions_count": len(context.global_positions),
        "positions_hash": context.positions_hash,
        "canonical": context.canonical_video_sha256,
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }


@requires_ffmpeg
@pytest.mark.parametrize("carrier", ["magnitude", "t1"])
def test_transport_reproduces_pre_acceleration_golden_values(tmp_path, carrier):
    if not FIXTURE.is_file():
        pytest.skip("the checked-in 30-frame H.264 fixture is unavailable")
    record = _transport_record(
        FIXTURE, CONTRACTS[carrier], tmp_path / "stego.h264",
        payload=GOLDEN_PAYLOAD, frames_per_segment=10, chunk_size=12,
    )
    record.pop("positions")
    assert record == GOLDEN_FIXTURE[carrier]


@requires_ffmpeg
@pytest.mark.parametrize("carrier", ["magnitude", "t1"])
def test_accelerated_transport_matches_serial_reference(tmp_path, monkeypatch, carrier):
    video = _synthetic_clip(tmp_path / "synthetic.h264", frames=6)
    records = {}
    for mode, workers in (("serial", "1"), ("accelerated", "4")):
        monkeypatch.setenv(parallel_analysis.WORKERS_ENV, workers)
        analysis_cache.clear_video_analysis_cache()
        if mode == "serial":
            # Reference: no analysis may survive from the context step.
            monkeypatch.setattr(
                streaming, "park_video_analysis_for_content_reuse",
                analysis_cache.clear_video_analysis_cache,
            )
        else:
            monkeypatch.undo()
            monkeypatch.setenv(parallel_analysis.WORKERS_ENV, workers)
            adopt = analysis_cache._adopt_parked_analysis

            def record_adoption(*args, **kwargs):
                adopted = adopt(*args, **kwargs)
                adoptions.append(adopted is not None)
                return adopted

            adoptions: list[bool] = []
            monkeypatch.setattr(analysis_cache, "_adopt_parked_analysis", record_adoption)
        # One chunk per run so the embedder can adopt the parked analysis.
        records[mode] = _transport_record(
            video, CONTRACTS[carrier], tmp_path / f"{mode}.h264",
            payload=GOLDEN_PAYLOAD, frames_per_segment=6, chunk_size=1_250,
        )
    analysis_cache.clear_video_analysis_cache()
    # The embedder reused the context step's analysis instead of rebuilding.
    assert True in adoptions
    assert records["accelerated"] == records["serial"]
    assert (tmp_path / "accelerated.h264").read_bytes() == (tmp_path / "serial.h264").read_bytes()
