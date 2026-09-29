"""Tests for blind extraction of payloads split across H.264 segments."""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.blind_payload_chunks import pack_payload_chunks
from src.blind_sync import BlindOperatingContract
from src.blind_sync_streaming import (
    _split_video_into_segments,
    derive_chunked_video_context,
    embed_chunked_video_payload,
    extract_chunked_video_payload,
)


def test_segment_split_reports_probe_and_boundary_progress(monkeypatch, tmp_path):
    source = tmp_path / "source.h264"
    source.write_bytes(b"h264")
    segments_dir = tmp_path / "segments"
    segments_dir.mkdir()
    events = []

    probe_results = iter([6, 3, 3])
    monkeypatch.setattr(
        "src.blind_sync_streaming._probe_frame_count",
        lambda *_args: next(probe_results),
    )

    def fake_run(command):
        output_pattern = Path(command[-1])
        for index in range(2):
            output_pattern.with_name(f"segment_{index:05}.h264").write_bytes(b"segment")

    monkeypatch.setattr("src.blind_sync_streaming._run", fake_run)

    segments, frame_counts = _split_video_into_segments(
        source,
        segments_dir,
        frames_per_segment=3,
        progress_callback=events.append,
    )

    assert len(segments) == 2
    assert frame_counts == [3, 3]
    assert [(event["event"], event.get("segment_index")) for event in events] == [
        ("source_probe_started", None),
        ("source_frames_counted", None),
        ("segment_split_started", None),
        ("segment_split_completed", None),
        ("segment_probe_started", 0),
        ("segment_probe_completed", 0),
        ("segment_probe_started", 1),
        ("segment_probe_completed", 1),
        ("segments_validated", None),
    ]
    assert events[1]["frames_total"] == 6
    assert events[-1]["segments_total"] == 2


def test_streaming_extractor_reads_declared_chunks_from_video_segments(
    monkeypatch, tmp_path
):
    video = tmp_path / "stego.h264"
    video.write_bytes(b"segmented test video")
    expected = b"multi-segment proof envelope" * 5
    chunks = pack_payload_chunks(expected, chunk_size=19)
    segments = [
        tmp_path / f"segment_{index:05}.h264" for index in range(len(chunks) + 2)
    ]
    for segment in segments:
        segment.write_bytes(b"fake segment")
    seen = []
    progress_events = []
    split_options = {}

    def fake_split(*_args, **kwargs):
        split_options.update(kwargs)
        return segments, [100] * len(segments)

    monkeypatch.setattr(
        "src.blind_sync_streaming._split_video_into_segments",
        fake_split,
    )

    def fake_extract(path, *_args, **_kwargs):
        seen.append(Path(path))
        index = segments.index(Path(path))
        return SimpleNamespace(
            payload=chunks[index],
            carriers_used=8 * len(chunks[index]),
            carrier_positions=[(0, 0, index)],
        )

    monkeypatch.setattr("src.blind_sync.extract_blind_video_payload", fake_extract)
    monkeypatch.setattr("src.blind_sync_streaming.clear_video_analysis_cache", lambda: 1)
    monkeypatch.setattr(
        "src.blind_sync_streaming.load_or_build_reconstruction_context",
        lambda *_args, **_kwargs: {"mb_count_per_slice": 396, "parser": object()},
    )
    monkeypatch.setattr(
        "src.blind_sync_streaming.load_or_build_video_analysis",
        lambda *_args, **_kwargs: ([], {0: ({}, {}, b"rbsp")}, {}, {}, {}, []),
    )
    monkeypatch.setattr(
        "src.video_canonicalization.canonical_video_sha256",
        lambda *_args, **_kwargs: "ab" * 32,
    )

    result = extract_chunked_video_payload(
        video,
        b"secret sync",
        object(),
        progress_callback=progress_events.append,
        ffprobe="custom-ffprobe.exe",
    )

    assert result.payload == expected
    assert result.segments_used == len(chunks)
    assert result.carriers_used == sum(8 * len(chunk) for chunk in chunks)
    assert seen == segments[: len(chunks)]
    assert len(result.global_positions) == len(chunks)
    assert result.positions_hash
    assert result.canonical_video_sha256
    assert split_options["ffprobe"] == "custom-ffprobe.exe"
    assert [event["event"] for event in progress_events] == [
        "segments_ready",
        *[event for _ in chunks for event in ("segment_started", "segment_completed")],
        "segment_skipped",
        "segment_skipped",
    ]
    assert all(event["phase"] == "extract" for event in progress_events)
    assert [
        event["segment_index"]
        for event in progress_events
        if event["event"] == "segment_completed"
    ] == list(range(len(chunks)))
    assert [
        event["segment_index"]
        for event in progress_events
        if event["event"] == "segment_skipped"
    ] == [len(chunks), len(chunks) + 1]


def test_chunked_context_binds_global_positions_and_segment_hashes(
    monkeypatch, tmp_path
):
    video = tmp_path / "cover.h264"
    video.write_bytes(b"source")
    pieces = pack_payload_chunks(b"proof bytes split", chunk_size=12)
    segments = [tmp_path / f"segment_{index:05}.h264" for index in range(3)]
    for index, segment in enumerate(segments):
        segment.write_bytes(bytes([index + 1]) * (index + 5))
    local_positions = {}
    observed_hash_inputs = []
    monkeypatch.setattr(
        "src.blind_sync_streaming._split_video_into_segments",
        lambda *_args, **_kwargs: (segments, [2, 2, 2]),
    )
    monkeypatch.setattr(
        "src.blind_sync.derive_blind_positions_operating_contract",
        lambda path, _key, required_bits, _contract, **_kwargs: (
            local_positions.setdefault(
                segments.index(Path(path)),
                [
                    (index, segments.index(Path(path)), index % 16)
                    for index in range(required_bits)
                ],
            ),
            None,
        ),
    )
    monkeypatch.setattr(
        "src.blind_sync_streaming.load_or_build_reconstruction_context",
        lambda *_args, **_kwargs: {"mb_count_per_slice": 396, "parser": object()},
    )
    monkeypatch.setattr(
        "src.blind_sync_streaming.load_or_build_video_analysis",
        lambda *_args, **_kwargs: ([], {0: ({}, {}, b"rbsp")}, {}, {}, {}, []),
    )

    def fake_canonical(path, positions, **_kwargs):
        observed_hash_inputs.append((Path(path), positions))
        return "11" * 32 if Path(path) == segments[0] else "22" * 32

    monkeypatch.setattr("src.video_canonicalization.canonical_video_sha256", fake_canonical)
    monkeypatch.setattr("src.blind_sync_streaming.clear_video_analysis_cache", lambda: 1)
    progress_events = []

    result = derive_chunked_video_context(
        video,
        pieces,
        b"sync key",
        BlindOperatingContract(
            require_bitstream_patchable=True,
            stable_carriers_only=True,
        ),
        frames_per_segment=2,
        progress_callback=progress_events.append,
    )

    expected_global = local_positions[0] + [
        (mb + 2 * 396, block, coefficient)
        for mb, block, coefficient in local_positions[1]
    ]
    assert list(result.global_positions) == expected_global
    assert result.positions_hash
    assert result.canonical_video_sha256
    assert observed_hash_inputs == [
        (segments[0], local_positions[0]),
        (segments[1], local_positions[1]),
    ]
    assert [
        (event["event"], event.get("segment_index")) for event in progress_events
    ] == [
        ("segments_ready", None),
        ("segment_started", 0),
        ("segment_completed", 0),
        ("segment_started", 1),
        ("segment_completed", 1),
        ("segment_started", 2),
        ("segment_completed", 2),
    ]


def test_chunked_embed_reports_segment_progress(monkeypatch, tmp_path):
    source = tmp_path / "cover.h264"
    output = tmp_path / "stego.h264"
    source.write_bytes(b"source")
    segments = [tmp_path / f"segment_{index:05}.h264" for index in range(2)]
    for index, segment in enumerate(segments):
        segment.write_bytes(bytes([index + 1]))
    events = []

    monkeypatch.setattr(
        "src.blind_sync_streaming._split_video_into_segments",
        lambda *_args, **_kwargs: (segments, [2, 2]),
    )

    def fake_embed(segment, stego_segment, *_args, **_kwargs):
        shutil.copyfile(segment, stego_segment)
        return SimpleNamespace(carriers_used=8)

    monkeypatch.setattr("src.blind_sync.embed_blind_video_payload", fake_embed)
    monkeypatch.setattr("src.embedder._strict_validate_h264_decode", lambda *_args: None)

    result = embed_chunked_video_payload(
        source,
        output,
        b"proof chunk",
        b"sync key",
        BlindOperatingContract(),
        frames_per_segment=2,
        chunk_size=1024,
        progress_callback=events.append,
    )

    assert result.segments_used == 1
    assert output.read_bytes() == b"\x01\x02"
    assert [event["event"] for event in events] == [
        "segments_ready",
        "segment_started",
        "segment_completed",
        "segment_started",
        "segment_completed",
        "assembly_started",
        "decode_passed",
    ]


def test_chunked_blind_channel_round_trips_real_idr_video(tmp_path):
    source = Path("data/external/trust_corpus/mdn_friday_cif_q22_g1_30f.h264")
    if not source.is_file():
        pytest.skip("the checked-in 30-frame H.264 fixture is unavailable")
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg and ffprobe are required for this real-video integration test")
    payload = b"full-envelope-chunk-round-trip"
    key = bytes(range(32))
    contract = BlindOperatingContract(
        version="stable-carriers-stream-test-v1",
        require_bitstream_patchable=True,
        patchability_headroom=64,
        max_modifications_per_block=1,
        stable_carriers_only=True,
    )
    output = tmp_path / "chunked-stego.h264"

    embedded = embed_chunked_video_payload(
        source,
        output,
        payload,
        key,
        contract,
        frames_per_segment=10,
        chunk_size=10,
    )
    extracted = extract_chunked_video_payload(
        output,
        key,
        contract,
        frames_per_segment=10,
    )

    assert embedded.segments_used == 3
    assert extracted.segments_used == 3
    assert extracted.payload == payload
