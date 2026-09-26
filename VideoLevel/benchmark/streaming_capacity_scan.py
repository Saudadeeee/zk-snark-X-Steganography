"""Bounded-memory scan of raw CAVLC-safe positions in GOP-aligned H.264.

This tool deliberately reports only a raw candidate upper bound. It does not
prove that candidates survive bitstream patching, blind extraction, or visual
quality validation, so a raw ``fits`` result must never be treated as an
embedding success.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import subprocess
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from benchmark.lattice_in_video_feasibility import assess_capacity


def _positive_integer(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def frame_cut_points(total_frames: int, frames_per_segment: int) -> list[int]:
    """Return ffmpeg segment-frame cut positions, excluding the final boundary."""
    total_frames = _positive_integer("total_frames", total_frames)
    frames_per_segment = _positive_integer("frames_per_segment", frames_per_segment)
    return list(range(frames_per_segment, total_frames, frames_per_segment))


def validate_segment_partition(
    total_frames: int,
    frames_per_segment: int,
    observed_frame_counts: Sequence[int],
) -> int:
    """Require exact chunk lengths; this rejects cuts missed by non-IDR GOPs."""
    total_frames = _positive_integer("total_frames", total_frames)
    frames_per_segment = _positive_integer("frames_per_segment", frames_per_segment)
    if not observed_frame_counts:
        raise ValueError("no video segments were produced")
    expected_count = (total_frames + frames_per_segment - 1) // frames_per_segment
    if len(observed_frame_counts) != expected_count:
        raise ValueError(
            f"expected {expected_count} segments, got {len(observed_frame_counts)}"
        )
    expected_frames = [frames_per_segment] * expected_count
    remainder = total_frames % frames_per_segment
    if remainder:
        expected_frames[-1] = remainder
    for index, (actual, expected) in enumerate(
        zip(observed_frame_counts, expected_frames, strict=True)
    ):
        if isinstance(actual, bool) or not isinstance(actual, int) or actual != expected:
            raise ValueError(
                f"segment {index} has {actual} frames; expected {expected}; "
                "input must have IDR boundaries at requested cuts"
            )
    if sum(observed_frame_counts) != total_frames:
        raise ValueError("segment frame counts do not preserve the source frame count")
    return total_frames


def summarize_raw_capacity(
    *,
    asset: str,
    frame_count: int,
    frames_per_segment: int,
    segment_frame_counts: Sequence[int],
    raw_safe_bits_by_segment: Sequence[int],
    proof_bytes: int,
    framing_bytes: int = 16,
) -> dict[str, Any]:
    """Create an explicitly non-acceptance raw-capacity report."""
    validate_segment_partition(frame_count, frames_per_segment, segment_frame_counts)
    if len(raw_safe_bits_by_segment) != len(segment_frame_counts):
        raise ValueError("raw-capacity results must match the segment count")
    for index, capacity in enumerate(raw_safe_bits_by_segment):
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 0:
            raise ValueError(f"raw-safe bit count for segment {index} is invalid")
    raw_capacity = sum(raw_safe_bits_by_segment)
    assessment = assess_capacity(
        proof_bytes=proof_bytes,
        capacity_bits=raw_capacity,
        framing_bytes=framing_bytes,
    )
    return {
        "measurement": "raw_safe_cavlc_candidates_only",
        "asset": Path(asset).name,
        "frame_count": frame_count,
        "frames_per_segment": frames_per_segment,
        "segment_count": len(segment_frame_counts),
        "segment_frame_counts": list(segment_frame_counts),
        "raw_safe_bits_by_segment": list(raw_safe_bits_by_segment),
        "raw_safe_carrier_bits": raw_capacity,
        "proof_bytes": proof_bytes,
        "framing_bytes": framing_bytes,
        "raw_capacity_assessment": assessment.to_dict(),
        "patchability_validated": False,
        "quality_validated": False,
        "blind_extraction_validated": False,
        "raw_fit_is_sufficient_for_embedding": False,
    }


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(command), capture_output=True, text=True, check=False, timeout=1800
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"command failed ({completed.returncode}): {detail}")
    return completed


def _probe_frame_count(video_path: str | Path, ffprobe: str = "ffprobe") -> int:
    result = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(video_path),
        ]
    )
    try:
        return _positive_integer("frame_count", int(result.stdout.strip()))
    except ValueError as error:
        raise ValueError(f"could not determine decoded frame count for {video_path}") from error


def _ffmpeg_version(ffmpeg: str = "ffmpeg") -> str:
    result = _run([ffmpeg, "-version"])
    return result.stdout.splitlines()[0] if result.stdout.splitlines() else "unknown"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _scan_segments(
    video_path: str | Path,
    frames_per_segment: int,
    total_frames: int,
    *,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> tuple[list[int], list[int]]:
    """Segment at requested IDRs and analyze one chunk at a time."""
    video_path = Path(video_path).resolve(strict=True)
    cuts = frame_cut_points(total_frames, frames_per_segment)
    if not cuts:
        raise ValueError("video is shorter than one requested segment")

    os.environ["BENCHMARK_DISABLE_ANALYSIS_CACHE"] = "1"
    from benchmark._common import load_or_build_benchmark_analysis

    with tempfile.TemporaryDirectory(prefix="zkstego-capacity-") as temp_dir:
        pattern = str(Path(temp_dir) / "segment_%05d.h264")
        cut_argument = ",".join(str(cut) for cut in cuts)
        _run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(video_path),
                "-map",
                "0:v:0",
                "-c:v",
                "copy",
                "-f",
                "segment",
                "-segment_frames",
                cut_argument,
                "-reset_timestamps",
                "0",
                pattern,
            ]
        )
        segments = sorted(Path(temp_dir).glob("segment_*.h264"))
        if not segments:
            raise RuntimeError("ffmpeg produced no H.264 segments")
        frame_counts = [_probe_frame_count(path, ffprobe) for path in segments]
        validate_segment_partition(total_frames, frames_per_segment, frame_counts)

        raw_bits: list[int] = []
        for segment in segments:
            analysis = load_or_build_benchmark_analysis(segment, force=True)
            raw_bits.append(len(analysis[-1]))
            del analysis
            gc.collect()
        return frame_counts, raw_bits


def scan_video(
    *,
    video_path: Path,
    proof_path: Path,
    frames_per_segment: int = 100,
    framing_bytes: int = 16,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> dict[str, Any]:
    """Measure raw candidates for a real Annex-B H.264 video and proof file."""
    video_path = video_path.resolve(strict=True)
    proof_path = proof_path.resolve(strict=True)
    _positive_integer("frames_per_segment", frames_per_segment)
    if isinstance(framing_bytes, bool) or not isinstance(framing_bytes, int) or framing_bytes < 0:
        raise ValueError("framing_bytes must be a non-negative integer")
    started = time.perf_counter()
    frame_count = _probe_frame_count(video_path, ffprobe)
    segment_counts, raw_bits = _scan_segments(
        video_path,
        frames_per_segment,
        frame_count,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
    )
    report = summarize_raw_capacity(
        asset=str(video_path),
        frame_count=frame_count,
        frames_per_segment=frames_per_segment,
        segment_frame_counts=segment_counts,
        raw_safe_bits_by_segment=raw_bits,
        proof_bytes=proof_path.stat().st_size,
        framing_bytes=framing_bytes,
    )
    report.update(
        {
            "video_bytes": video_path.stat().st_size,
            "video_sha256": _sha256_file(video_path),
            "proof_artifact": proof_path.name,
            "proof_sha256": _sha256_file(proof_path),
            "ffmpeg_version": _ffmpeg_version(ffmpeg),
            "elapsed_sec": round(time.perf_counter() - started, 3),
        }
    )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Measure raw CAVLC-safe candidate capacity for a GOP-aligned H.264 "
            "video in bounded-size chunks. This is not quality-validated capacity."
        )
    )
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--proof-artifact", required=True, type=Path)
    parser.add_argument("--frames-per-segment", type=int, default=100)
    parser.add_argument("--framing-bytes", type=int, default=16)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        report = scan_video(
            video_path=args.video,
            proof_path=args.proof_artifact,
            frames_per_segment=args.frames_per_segment,
            framing_bytes=args.framing_bytes,
            ffmpeg=args.ffmpeg,
            ffprobe=args.ffprobe,
        )
        encoded = json.dumps(report, sort_keys=True, indent=2)
        if args.output is not None:
            if args.output.exists():
                parser.error(f"refusing to overwrite existing report: {args.output}")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded + "\n", encoding="utf-8")
        print(encoded)
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
