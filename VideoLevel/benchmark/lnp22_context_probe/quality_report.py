"""Reproducible decoded-luma quality report for segmented H.264 carriers."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MODULE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = MODULE_DIR.parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from benchmark._common import QualityDecodeError, compute_quality_streaming

SEGMENT_PATTERN = re.compile(r"^segment_(\d{5})\.h264$")
STEGO_PATTERN = re.compile(r"^stego_(\d{5})\.h264$")
QUALITY_REPORT_SCHEMA = "lnp22-segmented-luma-quality/v1"


def _indexed_segments(directory: Path, pattern: re.Pattern[str]) -> dict[int, Path]:
    segments: dict[int, Path] = {}
    for path in directory.iterdir():
        if not path.is_file():
            continue
        match = pattern.fullmatch(path.name)
        if match is not None:
            segments[int(match.group(1))] = path
    return segments


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _psnr_json_value(value: float) -> tuple[float | None, bool]:
    if math.isinf(value) and value > 0:
        return None, True
    if not math.isfinite(value):
        raise ValueError("per-frame PSNR contains an invalid non-finite value")
    return float(value), False


def _aggregate_psnr(psnr_values: list[float]) -> float | None:
    mse_values = [
        0.0 if math.isinf(value) else 255.0**2 * 10.0 ** (-value / 10.0)
        for value in psnr_values
    ]
    mean_mse = sum(mse_values) / len(mse_values)
    if mean_mse == 0:
        return None
    return 20.0 * math.log10(255.0 / math.sqrt(mean_mse))


def _resolve_executable(command: str | None, default_name: str) -> Path:
    executable = command or default_name
    located = shutil.which(executable)
    if located:
        resolved = Path(located).expanduser().resolve()
    else:
        candidate = Path(executable).expanduser()
        resolved = candidate.resolve() if candidate.is_file() else None
    if resolved is None or not resolved.is_file():
        raise FileNotFoundError(f"could not resolve executable: {executable}")
    return resolved


def _probe_h264_video(
    path: Path,
    *,
    ffprobe_command: str | None = None,
) -> dict[str, int]:
    """Return encoded dimensions and exact decoded frame count via ffprobe."""
    ffprobe = _resolve_executable(ffprobe_command, "ffprobe")
    result = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,nb_read_frames",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    probe = json.loads(result.stdout)
    streams = probe.get("streams", [])
    if not streams:
        raise ValueError(f"no decodable video stream found in {path.name}")
    stream = streams[0]
    try:
        width = int(stream["width"])
        height = int(stream["height"])
        frame_count = int(stream["nb_read_frames"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"incomplete ffprobe metadata for {path.name}") from error
    if width <= 0 or height <= 0 or frame_count <= 0:
        raise ValueError(f"invalid ffprobe metadata for {path.name}")
    return {"width": width, "height": height, "decoded_frames": frame_count}


def build_quality_report(
    run_directory: str | Path,
    *,
    frames_per_segment: int,
    ffmpeg_version: str | None = None,
    ffprobe_command: str | None = None,
    ffmpeg_command: str | Path | None = None,
) -> dict[str, Any]:
    """Measure every available contiguous source/stego segment pair.

    Partial in-flight runs are allowed, but the report explicitly marks them
    incomplete. A missing or out-of-order stego segment is rejected so global
    frame indices cannot silently shift.
    """
    run_dir = Path(run_directory).expanduser().resolve(strict=True)
    if not run_dir.is_dir():
        raise ValueError("run_directory must be a directory")
    if (
        isinstance(frames_per_segment, bool)
        or not isinstance(frames_per_segment, int)
        or frames_per_segment <= 0
    ):
        raise ValueError("frames_per_segment must be a positive integer")

    source_segments = _indexed_segments(run_dir, SEGMENT_PATTERN)
    stego_segments = _indexed_segments(run_dir, STEGO_PATTERN)
    source_indices = sorted(source_segments)
    stego_indices = sorted(stego_segments)
    if not source_indices or source_indices != list(range(len(source_indices))):
        raise ValueError("source segment indexes must be contiguous from zero")
    if not stego_indices or stego_indices != list(range(len(stego_indices))):
        raise ValueError("stego segment indexes must be contiguous from zero")
    if any(index not in source_segments for index in stego_indices):
        raise ValueError("stego segment has no matching source segment")

    measured_frames = 0
    psnr_values: list[float] = []
    ssim_values: list[float] = []
    per_frame: list[dict[str, Any]] = []
    segment_rows: list[dict[str, Any]] = []
    for index in stego_indices:
        source_probe = _probe_h264_video(
            source_segments[index], ffprobe_command=ffprobe_command
        )
        stego_probe = _probe_h264_video(
            stego_segments[index], ffprobe_command=ffprobe_command
        )
        if (source_probe["width"], source_probe["height"]) != (
            stego_probe["width"],
            stego_probe["height"],
        ):
            raise ValueError(f"source/stego dimensions differ for segment {index:05d}")
        if source_probe["decoded_frames"] != stego_probe["decoded_frames"]:
            raise ValueError(
                f"source/stego decoded frame count mismatch for segment {index:05d}: "
                f"{source_probe['decoded_frames']} != {stego_probe['decoded_frames']}"
            )

        quality_kwargs: dict[str, Any] = {
            "max_frames": frames_per_segment + 1,
            "use_cache": False,
        }
        if ffmpeg_command is not None:
            quality_kwargs["ffmpeg_command"] = ffmpeg_command
        quality = compute_quality_streaming(
            source_segments[index], stego_segments[index], **quality_kwargs
        )
        frame_count = quality.get("n")
        frame_psnr = quality.get("psnr_per_frame")
        frame_ssim = quality.get("ssim_per_frame")
        if (
            isinstance(frame_count, bool)
            or not isinstance(frame_count, int)
            or frame_count <= 0
            or frame_count > frames_per_segment
            or frame_count != source_probe["decoded_frames"]
            or not isinstance(frame_psnr, list)
            or not isinstance(frame_ssim, list)
            or len(frame_psnr) != frame_count
            or len(frame_ssim) != frame_count
        ):
            raise ValueError(f"invalid frame metrics for segment {index:05d}")
        if index < len(source_indices) - 1 and frame_count != frames_per_segment:
            raise ValueError(
                f"non-final segment {index:05d} decoded {frame_count} frames; "
                f"expected {frames_per_segment}"
            )

        frame_start = index * frames_per_segment
        for local_index, (psnr, ssim) in enumerate(zip(frame_psnr, frame_ssim, strict=True)):
            psnr_value = float(psnr)
            ssim_value = float(ssim)
            psnr_json, identical = _psnr_json_value(psnr_value)
            if not math.isfinite(ssim_value):
                raise ValueError("per-frame SSIM contains a non-finite value")
            per_frame.append(
                {
                    "frame_index": frame_start + local_index,
                    "segment_index": index,
                    "frame_in_segment": local_index,
                    "psnr_y_db": psnr_json,
                    "identical_luma": identical,
                    "ssim_y": ssim_value,
                }
            )
            psnr_values.append(psnr_value)
            ssim_values.append(ssim_value)

        measured_frames += frame_count
        segment_rows.append(
            {
                "segment_index": index,
                "frame_start": frame_start,
                "frame_count": frame_count,
                "input_width": source_probe["width"],
                "input_height": source_probe["height"],
                "source_file": source_segments[index].name,
                "source_sha256": _sha256_file(source_segments[index]),
                "stego_file": stego_segments[index].name,
                "stego_sha256": _sha256_file(stego_segments[index]),
                "psnr_y_full_segment_db": (
                    None
                    if math.isinf(float(quality["psnr_full_video"]))
                    else float(quality["psnr_full_video"])
                ),
                "ssim_y_mean": sum(map(float, frame_ssim)) / frame_count,
            }
        )

    complete = stego_indices == source_indices
    return {
        "schema": QUALITY_REPORT_SCHEMA,
        "created_utc": datetime.now(UTC).isoformat(),
        "run_directory": str(run_dir),
        "comparison": "decoded source H.264 segment versus decoded stego H.264 segment",
        "metric_scope": (
            "Y/luma only; benchmark._common.decode_luma_frames forcibly rescales "
            "both decoded streams to 352x288 before per-frame PSNR/SSIM"
        ),
        "frames_per_segment": frames_per_segment,
        "source_segment_count": len(source_indices),
        "measured_segment_count": len(stego_indices),
        "measured_frame_count": measured_frames,
        "complete": complete,
        "coverage": "complete" if complete else "partial_in_flight_run",
        "unmeasured_segment_indices": [
            index for index in source_indices if index not in stego_segments
        ],
        "ffmpeg_version": ffmpeg_version,
        "summary": {
            "psnr_y_full_measured_frames_db": _aggregate_psnr(psnr_values),
            "psnr_y_infinite_frame_count": sum(math.isinf(value) for value in psnr_values),
            "ssim_y_mean_per_frame": sum(ssim_values) / len(ssim_values),
            "psnr_y_frame_min_db": min(
                (value for value in psnr_values if math.isfinite(value)),
                default=None,
            ),
        },
        "segments": segment_rows,
        "per_frame": per_frame,
        "limitations": [
            "luma-only metrics; chroma quality is not measured",
            "quality decoding rescales to 352x288 without preserving aspect ratio",
            "a partial report does not describe unmeasured source segments",
            "this compares the encoded source carrier with the stego carrier, not raw camera frames",
            "quality metrics do not prove cryptographic validity or steganographic undetectability",
        ],
    }


def _resolve_ffmpeg(command: str | None) -> Path:
    return _resolve_executable(command, "ffmpeg")


def write_quality_report(
    run_directory: str | Path,
    output_path: str | Path,
    *,
    frames_per_segment: int,
    ffmpeg_command: str | None = None,
    ffprobe_command: str | None = None,
) -> dict[str, Any]:
    """Build and exclusively create a reproducible JSON report."""
    output = Path(output_path).expanduser().resolve()
    if not output.parent.is_dir():
        raise FileNotFoundError("report output directory must already exist")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite quality report: {output}")
    ffmpeg = _resolve_ffmpeg(ffmpeg_command)
    result = subprocess.run(
        [str(ffmpeg), "-version"],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    version_line = result.stdout.splitlines()[0] if result.stdout else "unknown"
    report = build_quality_report(
        run_directory,
        frames_per_segment=frames_per_segment,
        ffmpeg_version=version_line,
        ffmpeg_command=ffmpeg,
        ffprobe_command=(
            ffprobe_command
            or (
                str(ffmpeg.with_name("ffprobe.exe"))
                if ffmpeg.with_name("ffprobe.exe").is_file()
                else None
            )
        ),
    )
    with output.open("x", encoding="utf-8", newline="\n") as destination:
        json.dump(report, destination, ensure_ascii=False, indent=2, allow_nan=False)
        destination.write("\n")
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frames-per-segment", type=int, default=100)
    parser.add_argument("--ffmpeg", help="ffmpeg executable path; defaults to PATH lookup")
    parser.add_argument("--ffprobe", help="ffprobe executable path; defaults to PATH lookup")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        report = write_quality_report(
            args.run_dir,
            args.output,
            frames_per_segment=args.frames_per_segment,
            ffmpeg_command=args.ffmpeg,
            ffprobe_command=args.ffprobe,
        )
    except (
        FileNotFoundError,
        FileExistsError,
        QualityDecodeError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        print(f"quality report failed: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "coverage": report["coverage"],
                "measured_segments": report["measured_segment_count"],
                "measured_frames": report["measured_frame_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
