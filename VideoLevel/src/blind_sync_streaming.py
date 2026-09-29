"""Bounded-memory blind payload transport over GOP-aligned H.264 segments.

Each selected segment contains one ordinary blind-channel envelope. A strict
outer chunk frame marks the payload pieces and makes their order and total
length verifiable after extraction. The complete user payload remains inside
video residual carriers; no proof sidecar is created.
"""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import struct
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .blind_payload_chunks import (
    assemble_payload_chunks,
    pack_payload_chunks,
    payload_chunk_count,
)
from .core.analysis_cache import (
    clear_video_analysis_cache,
    load_or_build_reconstruction_context,
    load_or_build_video_analysis,
)

DEFAULT_STREAM_SEGMENT_FRAMES = 100
DEFAULT_STREAM_CHUNK_BYTES = 1_250
ProgressCallback = Callable[[dict[str, str | int]], None]


def _emit_progress(
    callback: ProgressCallback | None,
    phase: str,
    event: str,
    **details: int,
) -> None:
    if callback is not None:
        callback({"phase": phase, "event": event, **details})


@dataclass(frozen=True)
class ChunkedVideoEmbedResult:
    output_path: str
    payload_bytes: int
    segments_used: int
    carriers_used: int


@dataclass(frozen=True)
class ChunkedVideoPayloadResult:
    payload: bytes
    segments_used: int
    carriers_used: int
    positions_hash: str
    canonical_video_sha256: str
    global_positions: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True)
class ChunkedVideoContext:
    positions_hash: str
    canonical_video_sha256: str
    global_positions: tuple[tuple[int, int, int], ...]
    segments_used: int
    frames_per_segment: int


def _positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _run(command: list[str], *, timeout_seconds: int = 1800) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as error:
        raise RuntimeError(f"required video tool not found: {command[0]}") from error
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"command failed ({completed.returncode}): {detail[-2000:]}")
    return completed


def _probe_frame_count(video_path: Path, ffprobe: str) -> int:
    result = _run(
        [
            ffprobe,
            "-v", "error",
            "-select_streams", "v:0",
            "-count_frames",
            "-show_entries", "stream=nb_read_frames",
            "-of", "default=nokey=1:noprint_wrappers=1",
            str(video_path),
        ]
    )
    try:
        return _positive_int("decoded frame count", int(result.stdout.strip()))
    except ValueError as error:
        raise ValueError(f"could not determine decoded frame count for {video_path}") from error


def _split_video_into_segments(
    video_path: str | Path,
    temp_dir: str | Path,
    frames_per_segment: int,
    *,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[Path], list[int]]:
    """Split at fixed frame intervals and reject cuts without exact boundaries."""
    source = Path(video_path).resolve(strict=True)
    directory = Path(temp_dir).resolve(strict=True)
    frames_per_segment = _positive_int("frames_per_segment", frames_per_segment)
    _emit_progress(progress_callback, "extract", "source_probe_started")
    total_frames = _probe_frame_count(source, ffprobe)
    _emit_progress(
        progress_callback,
        "extract",
        "source_frames_counted",
        frames_total=total_frames,
    )
    cuts = list(range(frames_per_segment, total_frames, frames_per_segment))
    if not cuts:
        segment = directory / "segment_00000.h264"
        shutil.copyfile(source, segment)
        _emit_progress(
            progress_callback,
            "extract",
            "single_segment_copied",
            segments_total=1,
            frames_total=total_frames,
        )
        return [segment], [total_frames]

    pattern = str(directory / "segment_%05d.h264")
    command = [
        ffmpeg,
        "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(source), "-map", "0:v:0", "-c:v", "copy",
    ]
    command.extend(["-f", "segment", "-segment_frames", ",".join(map(str, cuts))])
    command.extend(["-reset_timestamps", "0", pattern])
    _emit_progress(
        progress_callback,
        "extract",
        "segment_split_started",
        segments_total=math.ceil(total_frames / frames_per_segment),
    )
    _run(command)

    segments = sorted(directory.glob("segment_*.h264"))
    expected_count = math.ceil(total_frames / frames_per_segment)
    _emit_progress(
        progress_callback,
        "extract",
        "segment_split_completed",
        segments_total=len(segments),
    )
    if len(segments) != expected_count:
        raise ValueError(
            f"expected {expected_count} segments, got {len(segments)}; "
            "the requested boundaries may not be H.264 IDR frames"
        )
    frame_counts = []
    for index, segment in enumerate(segments):
        _emit_progress(
            progress_callback,
            "extract",
            "segment_probe_started",
            segment_index=index,
            segments_total=len(segments),
        )
        frame_count = _probe_frame_count(segment, ffprobe)
        frame_counts.append(frame_count)
        _emit_progress(
            progress_callback,
            "extract",
            "segment_probe_completed",
            segment_index=index,
            segments_total=len(segments),
            frames_total=frame_count,
        )
    expected_counts = [frames_per_segment] * expected_count
    remainder = total_frames % frames_per_segment
    if remainder:
        expected_counts[-1] = remainder
    if frame_counts != expected_counts:
        raise ValueError(
            "H.264 segment frame counts do not match requested cuts; "
            "choose boundaries aligned to IDR frames"
        )
    _emit_progress(
        progress_callback,
        "extract",
        "segments_validated",
        segments_total=len(segments),
        frames_total=sum(frame_counts),
    )
    return segments, frame_counts


def _concatenate_annexb_segments(segments: list[Path], candidate: Path) -> None:
    with candidate.open("xb") as output:
        for segment in segments:
            with segment.open("rb") as source:
                shutil.copyfileobj(source, output, length=1024 * 1024)


def _combine_segment_digests(
    segment_digests: list[tuple[int, str]], frames_per_segment: int
) -> str:
    digest = hashlib.sha256(b"zkstego/canonical-h264-segmented/v1\x00")
    digest.update(struct.pack(">II", frames_per_segment, len(segment_digests)))
    for index, (frame_count, segment_digest) in enumerate(segment_digests):
        digest.update(struct.pack(">II", index, frame_count))
        digest.update(bytes.fromhex(segment_digest))
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def derive_chunked_video_context(
    video_path: str | Path,
    chunks: list[bytes],
    sync_key: bytes,
    contract: Any,
    *,
    frames_per_segment: int = DEFAULT_STREAM_SEGMENT_FRAMES,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    progress_callback: ProgressCallback | None = None,
) -> ChunkedVideoContext:
    """Select chunk carriers and compute verifier-reproducible video context.

    Positions are globalized by adding each segment's preceding macroblock
    count. Modified-segment digests normalize the selected carriers; untouched
    segments are hashed byte-for-byte. The exact segmentation policy is part
    of the domain-separated combined digest.
    """
    source = Path(video_path).resolve(strict=True)
    if not source.is_file():
        raise ValueError("video_path must identify a regular file")
    if not isinstance(chunks, list) or not chunks:
        raise ValueError("at least one payload chunk is required")
    assemble_payload_chunks(chunks)
    if not getattr(contract, "stable_carriers_only", False):
        raise ValueError("segmented context requires stable carriers")
    if not getattr(contract, "require_bitstream_patchable", False):
        raise ValueError("segmented context requires patchability validation")
    if not isinstance(sync_key, bytes) or not sync_key:
        raise ValueError("sync_key must be non-empty bytes")

    from .blind_sync import (
        derive_blind_positions_operating_contract,
        pack_blind_payload,
    )
    from .manifest import hash_positions
    from .video_canonicalization import canonical_video_sha256

    _positive_int("frames_per_segment", frames_per_segment)
    with tempfile.TemporaryDirectory(prefix="zkstego-context-") as temp_name:
        segments, frame_counts = _split_video_into_segments(
            source,
            temp_name,
            frames_per_segment,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
        )
        _emit_progress(
            progress_callback,
            "carrier_context",
            "segments_ready",
            segments_total=len(segments),
            frames_total=sum(frame_counts),
        )
        if len(chunks) > len(segments):
            raise ValueError(
                f"payload requires {len(chunks)} segments, video has {len(segments)}"
            )

        global_positions: list[tuple[int, int, int]] = []
        segment_digests: list[tuple[int, str]] = []
        frame_offset = 0
        macroblocks_per_frame: int | None = None
        try:
            for index, (segment, frame_count) in enumerate(zip(segments, frame_counts, strict=True)):
                _emit_progress(
                    progress_callback,
                    "carrier_context",
                    "segment_started",
                    segment_index=index,
                    segments_total=len(segments),
                )
                carriers_used = 0
                if index < len(chunks):
                    required_bits = len(pack_blind_payload(chunks[index])) * 8
                    positions, _metadata = derive_blind_positions_operating_contract(
                        str(segment),
                        sync_key,
                        required_bits,
                        contract,
                        use_analysis_cache=True,
                    )
                    if len(positions) != required_bits:
                        raise ValueError(
                            f"segment {index} has insufficient patchable stable carriers: "
                            f"need {required_bits}, got {len(positions)}"
                        )
                    carriers_used = len(positions)
                    analysis = load_or_build_video_analysis(
                        segment,
                        use_cache=True,
                        stable_blind_only=True,
                    )
                    reconstruction_context = load_or_build_reconstruction_context(
                        segment, use_cache=True
                    )
                    current_mb_count = int(reconstruction_context["mb_count_per_slice"])
                    if macroblocks_per_frame is None:
                        macroblocks_per_frame = current_mb_count
                    elif current_mb_count != macroblocks_per_frame:
                        raise ValueError("video resolution changes between H.264 segments")

                    canonical_digest = canonical_video_sha256(
                        segment,
                        positions,
                        parser=reconstruction_context["parser"],
                        frame_verified_data=analysis[1],
                    )
                    global_positions.extend(
                        (mb + frame_offset * current_mb_count, block, coefficient)
                        for mb, block, coefficient in positions
                    )
                    segment_digests.append((frame_count, canonical_digest))
                else:
                    segment_digests.append((frame_count, _sha256_file(segment)))
                frame_offset += frame_count
                clear_video_analysis_cache()
                _emit_progress(
                    progress_callback,
                    "carrier_context",
                    "segment_completed",
                    segment_index=index,
                    segments_total=len(segments),
                    carriers_used=carriers_used,
                )
        finally:
            clear_video_analysis_cache()

    return ChunkedVideoContext(
        positions_hash=hash_positions(global_positions),
        canonical_video_sha256=_combine_segment_digests(
            segment_digests, frames_per_segment
        ),
        global_positions=tuple(global_positions),
        segments_used=len(chunks),
        frames_per_segment=frames_per_segment,
    )


def embed_chunked_video_payload(
    cover_video_path: str | Path,
    output_video_path: str | Path,
    payload: bytes,
    sync_key: bytes,
    contract: Any,
    *,
    frames_per_segment: int = DEFAULT_STREAM_SEGMENT_FRAMES,
    chunk_size: int = DEFAULT_STREAM_CHUNK_BYTES,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    progress_callback: ProgressCallback | None = None,
) -> ChunkedVideoEmbedResult:
    """Embed ordered payload chunks while analyzing only one segment at a time."""
    source = Path(cover_video_path).resolve(strict=True)
    output = Path(output_video_path).resolve()
    if not source.is_file():
        raise ValueError("cover_video_path must identify a regular file")
    if source == output:
        raise ValueError("output video must differ from input video")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"output video already exists: {output}")
    if not output.parent.is_dir():
        raise FileNotFoundError("output video directory does not exist")

    chunks = pack_payload_chunks(payload, chunk_size=chunk_size)
    _positive_int("frames_per_segment", frames_per_segment)
    with tempfile.TemporaryDirectory(prefix="zkstego-stream-", dir=output.parent) as temp_name:
        temp_dir = Path(temp_name)
        source_segments, _ = _split_video_into_segments(
            source,
            temp_dir,
            frames_per_segment,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
        )
        _emit_progress(
            progress_callback,
            "embed",
            "segments_ready",
            segments_total=len(source_segments),
            payload_segments=len(chunks),
        )
        if len(chunks) > len(source_segments):
            raise ValueError(
                f"payload requires {len(chunks)} segments, video has {len(source_segments)}"
            )

        from .blind_sync import embed_blind_video_payload
        from .embedder import _strict_validate_h264_decode

        output_segments: list[Path] = []
        carriers_used = 0
        try:
            for index, segment in enumerate(source_segments):
                _emit_progress(
                    progress_callback,
                    "embed",
                    "segment_started",
                    segment_index=index,
                    segments_total=len(source_segments),
                )
                segment_carriers = 0
                if index < len(chunks):
                    stego_segment = temp_dir / f"stego_{index:05}.h264"
                    result = embed_blind_video_payload(
                        str(segment),
                        str(stego_segment),
                        chunks[index],
                        sync_key,
                        contract,
                    )
                    segment_carriers = result.carriers_used
                    carriers_used += segment_carriers
                    output_segments.append(stego_segment)
                    clear_video_analysis_cache()
                else:
                    output_segments.append(segment)
                _emit_progress(
                    progress_callback,
                    "embed",
                    "segment_completed",
                    segment_index=index,
                    segments_total=len(source_segments),
                    carriers_used=segment_carriers,
                )

            candidate = temp_dir / "candidate.h264"
            _emit_progress(
                progress_callback,
                "embed",
                "assembly_started",
                segments_total=len(output_segments),
            )
            _concatenate_annexb_segments(output_segments, candidate)
            _strict_validate_h264_decode(str(candidate))
            _emit_progress(
                progress_callback,
                "embed",
                "decode_passed",
                segments_total=len(output_segments),
            )
            try:
                os.link(candidate, output)
            except FileExistsError:
                raise FileExistsError(f"output video appeared during embedding: {output}") from None
        finally:
            clear_video_analysis_cache()

    return ChunkedVideoEmbedResult(
        output_path=str(output),
        payload_bytes=len(payload),
        segments_used=len(chunks),
        carriers_used=carriers_used,
    )


def extract_chunked_video_payload(
    video_path: str | Path,
    sync_key: bytes,
    contract: Any,
    *,
    frames_per_segment: int = DEFAULT_STREAM_SEGMENT_FRAMES,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    progress_callback: ProgressCallback | None = None,
) -> ChunkedVideoPayloadResult:
    """Blind-extract ordered pieces from video segments and validate reassembly."""
    source = Path(video_path).resolve(strict=True)
    if not source.is_file():
        raise ValueError("video_path must identify a regular file")

    from .blind_sync import extract_blind_video_payload

    with tempfile.TemporaryDirectory(prefix="zkstego-extract-") as temp_name:
        segments, frame_counts = _split_video_into_segments(
            source,
            temp_name,
            frames_per_segment,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            progress_callback=progress_callback,
        )
        _emit_progress(
            progress_callback,
            "extract",
            "segments_ready",
            segments_total=len(segments),
        )
        pieces: list[bytes] = []
        carriers_used = 0
        expected_count: int | None = None
        global_positions: list[tuple[int, int, int]] = []
        segment_digests: list[tuple[int, str]] = []
        frame_offset = 0
        macroblocks_per_frame: int | None = None
        try:
            for index, (segment, frame_count) in enumerate(zip(segments, frame_counts, strict=True)):
                if expected_count is not None and len(pieces) >= expected_count:
                    _emit_progress(
                        progress_callback,
                        "extract",
                        "segment_skipped",
                        segment_index=index,
                        segments_total=len(segments),
                    )
                    segment_digests.append((frame_count, _sha256_file(segment)))
                    frame_offset += frame_count
                    continue
                _emit_progress(
                    progress_callback,
                    "extract",
                    "segment_started",
                    segment_index=index,
                    segments_total=len(segments),
                )
                result = extract_blind_video_payload(str(segment), sync_key, contract)
                pieces.append(result.payload)
                carriers_used += result.carriers_used
                count = payload_chunk_count(result.payload)
                if expected_count is None:
                    expected_count = count
                    if count > len(segments):
                        raise ValueError("payload declares more chunks than the video has segments")
                elif count != expected_count:
                    raise ValueError("chunk count changes between video segments")

                analysis = load_or_build_video_analysis(
                    segment,
                    use_cache=True,
                    stable_blind_only=True,
                )
                reconstruction_context = load_or_build_reconstruction_context(
                    segment, use_cache=True
                )
                current_mb_count = int(reconstruction_context["mb_count_per_slice"])
                if macroblocks_per_frame is None:
                    macroblocks_per_frame = current_mb_count
                elif current_mb_count != macroblocks_per_frame:
                    raise ValueError("video resolution changes between H.264 segments")
                global_positions.extend(
                    (mb + frame_offset * current_mb_count, block, coefficient)
                    for mb, block, coefficient in result.carrier_positions
                )
                from .video_canonicalization import canonical_video_sha256

                segment_digests.append(
                    (
                        frame_count,
                        canonical_video_sha256(
                            segment,
                            result.carrier_positions,
                            parser=reconstruction_context["parser"],
                            frame_verified_data=analysis[1],
                        ),
                    )
                )
                frame_offset += frame_count
                clear_video_analysis_cache()
                _emit_progress(
                    progress_callback,
                    "extract",
                    "segment_completed",
                    segment_index=index,
                    segments_total=len(segments),
                    carriers_used=result.carriers_used,
                )
        finally:
            clear_video_analysis_cache()

    if expected_count is None or len(pieces) != expected_count:
        raise ValueError("video ended before all declared payload chunks were extracted")
    from .manifest import hash_positions

    return ChunkedVideoPayloadResult(
        payload=assemble_payload_chunks(pieces),
        segments_used=len(pieces),
        carriers_used=carriers_used,
        positions_hash=hash_positions(global_positions),
        canonical_video_sha256=_combine_segment_digests(
            segment_digests, frames_per_segment
        ),
        global_positions=tuple(global_positions),
    )
