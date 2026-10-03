"""Run the physical-camera E2E and append successful metrics to its JSON artifact."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import psutil

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "benchmark" / "results"
# Fixed overhead (proof generation, ffmpeg startup, verification) for the camera E2E child.
CAMERA_TEST_TIMEOUT_BASE_SECONDS = 900.0
REQUIRED_TRUE_FIELDS = (
    "correct_key_payload_match",
    "wrong_key_rejected",
    "groth16_proof_verified",
    "groth16_wrong_key_rejected",
    "groth16_changed_message_rejected",
    "first_output_before_camera_eof",
)
REQUIRED_ENCODER_FIELDS = (
    "codec", "preset", "profile", "coder", "entropy_coding", "pixel_format",
    "resolution", "requested_fps", "qp", "gop", "x264_params", "fps_mode",
)
REQUIRED_ENVIRONMENT_FIELDS = (
    "hostname", "os", "architecture", "cpu_model", "logical_cpu_count",
    "ram_total_bytes", "python_version", "ffmpeg_path", "ffmpeg_version",
    "native_cli_path", "native_cli_sha256",
)


def build_camera_capture_command(
    *,
    camera_device_name: str,
    duration_seconds: float,
    camera_input_buffer_bytes: int,
    encoder: dict[str, Any],
) -> list[str]:
    """Build the pinned camera capture command without CFR frame duplication."""
    if not camera_device_name.strip():
        raise ValueError("camera_device_name must be non-empty")
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError("duration_seconds must be finite and positive")
    if type(camera_input_buffer_bytes) is not int or camera_input_buffer_bytes <= 0:
        raise ValueError("camera_input_buffer_bytes must be a positive integer")
    if camera_input_buffer_bytes % 1024:
        raise ValueError("camera_input_buffer_bytes must be divisible by 1024")
    if encoder.get("fps_mode") != "passthrough":
        raise ValueError("camera capture fps_mode must be passthrough")

    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "dshow", "-rtbufsize", f"{camera_input_buffer_bytes // 1024}K",
        "-video_size", str(encoder["resolution"]),
        "-framerate", str(encoder["requested_fps"]), "-i", f"video={camera_device_name}",
        "-t", f"{duration_seconds:g}", "-an", "-fps_mode", "passthrough",
        "-c:v", str(encoder["codec"]), "-preset", str(encoder["preset"]),
        "-profile:v", str(encoder["profile"]), "-coder", str(encoder["coder"]),
        "-pix_fmt", str(encoder["pixel_format"]), "-x264-params", str(encoder["x264_params"]),
        "-g", str(encoder["gop"]), "-qp", str(encoder["qp"]),
        "-f", "h264", "pipe:1",
    ]


def collect_run_environment(native_cli_path: Path, *, camera_device_name: str) -> dict[str, Any]:
    """Capture enough machine/tool identity to compare benchmark runs later."""
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise ValueError("ffmpeg not found while collecting benchmark environment")
    cli_path = Path(native_cli_path).resolve(strict=True)
    if not cli_path.is_file():
        raise ValueError(f"native CLI not found while collecting benchmark environment: {cli_path}")
    ffmpeg = subprocess.run(
        [ffmpeg_path, "-version"], capture_output=True, text=True, check=False, timeout=10,
    )
    if ffmpeg.returncode != 0:
        raise ValueError(f"could not query FFmpeg version: {ffmpeg.stderr.strip()}")
    ffmpeg_version = next((line.strip() for line in ffmpeg.stdout.splitlines() if line.strip()), "")
    if not ffmpeg_version:
        raise ValueError("FFmpeg returned an empty version string")

    digest = hashlib.sha256()
    with cli_path.open("rb") as native_cli:
        for chunk in iter(lambda: native_cli.read(1024 * 1024), b""):
            digest.update(chunk)
    memory = psutil.virtual_memory()
    return {
        "camera_device_name": camera_device_name,
        "hostname": platform.node() or "unknown",
        "os": platform.platform(),
        "architecture": platform.machine() or "unknown",
        "cpu_model": platform.processor() or "unknown",
        "logical_cpu_count": int(os.cpu_count() or 1),
        "ram_total_bytes": int(memory.total),
        "python_version": platform.python_version(),
        "ffmpeg_path": str(Path(ffmpeg_path).resolve()),
        "ffmpeg_version": ffmpeg_version,
        "native_cli_path": str(cli_path),
        "native_cli_sha256": digest.hexdigest(),
    }


def _validate_metrics(metrics: dict[str, Any]) -> None:
    def finite_number(value: Any) -> bool:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        try:
            return math.isfinite(value)
        except OverflowError:
            return False

    def require_number(
        record: dict[str, Any], field: str, *, positive: bool = False, label: str | None = None,
    ) -> float:
        value = record.get(field)
        if not finite_number(value) or (value <= 0 if positive else value < 0):
            qualifier = "positive" if positive else "non-negative"
            raise ValueError(f"{label or field} must be a finite {qualifier} number")
        return float(value)

    required = {
        "capture_source", "capture_duration_seconds", "camera_input_buffer_bytes",
        "camera_pipe_read_chunk_bytes", "active_stream_seconds",
        "captured_frames", "stego_frames", "source_bytes", "stego_bytes", "resolution",
        "active_stream_frame_rate_fps", "ffmpeg_strict_decode_exit", "decoded_quality",
        "native_metrics", "full_stream_capacity", "capacity_scan_seconds",
        "native_resources", "capture_process_tree_resources", "flow_control",
        "camera_pipe_to_client_nal_latency",
        "capture_device_name", "capture_encoder", "run_environment",
        *REQUIRED_TRUE_FIELDS,
    }
    missing = required.difference(metrics)
    if missing:
        raise ValueError(f"camera run is missing required metrics: {', '.join(sorted(missing))}")
    duration = metrics["capture_duration_seconds"]
    source_frames = metrics["captured_frames"]
    stego_frames = metrics["stego_frames"]
    if not finite_number(duration) or duration <= 0:
        raise ValueError("capture duration must be a positive number")
    if type(metrics["camera_input_buffer_bytes"]) is not int or metrics["camera_input_buffer_bytes"] <= 0:
        raise ValueError("camera_input_buffer_bytes must be a positive integer")
    active_stream_seconds = metrics["active_stream_seconds"]
    if not finite_number(active_stream_seconds) or active_stream_seconds <= 0:
        raise ValueError("active_stream_seconds must be a finite positive number")
    if type(metrics["camera_pipe_read_chunk_bytes"]) is not int or metrics["camera_pipe_read_chunk_bytes"] <= 0:
        raise ValueError("camera_pipe_read_chunk_bytes must be a positive integer")
    if not isinstance(source_frames, int) or isinstance(source_frames, bool) or source_frames <= 0:
        raise ValueError("captured frame count must be a positive integer")
    if source_frames != stego_frames:
        raise ValueError("camera and stego frame counts differ")
    if type(stego_frames) is not int or stego_frames <= 0:
        raise ValueError("stego frame count must be a positive integer")
    require_number(metrics, "active_stream_frame_rate_fps", positive=True)
    measured_fps = stego_frames / active_stream_seconds
    if not math.isclose(
        metrics["active_stream_frame_rate_fps"], measured_fps, rel_tol=0.01, abs_tol=0.01,
    ):
        raise ValueError("active_stream_frame_rate_fps is inconsistent with frame count and active duration")
    for field in ("source_bytes", "stego_bytes"):
        if type(metrics[field]) is not int or metrics[field] <= 0:
            raise ValueError(f"{field} must be a positive integer")
    if type(metrics["ffmpeg_strict_decode_exit"]) is not int or metrics["ffmpeg_strict_decode_exit"] != 0:
        raise ValueError("strict FFmpeg decoder gate did not pass")
    if any(metrics[field] is not True for field in REQUIRED_TRUE_FIELDS):
        raise ValueError("camera E2E proof, authentication, or streaming gate did not pass")
    for field in (
        "decoded_quality", "native_metrics", "full_stream_capacity", "native_resources",
        "capture_process_tree_resources", "flow_control", "camera_pipe_to_client_nal_latency",
    ):
        if not isinstance(metrics[field], dict):
            raise ValueError(f"{field} must be an object")
    require_number(metrics, "capacity_scan_seconds", positive=True)
    quality = metrics["decoded_quality"]
    quality_fields = (
        "decoded_frame_count", "yuv420_psnr_full_video_db", "yuv420_psnr_min_modified_frame_db",
        "luma_ssim_mean", "luma_ssim_min", "identical_decoded_frames",
    )
    if any(field not in quality for field in quality_fields):
        raise ValueError("decoded_quality is missing required PSNR, SSIM, or frame-count metrics")
    if type(quality["decoded_frame_count"]) is not int or quality["decoded_frame_count"] != stego_frames:
        raise ValueError("decoded_quality.decoded_frame_count must equal the stego frame count")
    if type(quality["identical_decoded_frames"]) is not int or not 0 <= quality["identical_decoded_frames"] <= stego_frames:
        raise ValueError("decoded_quality.identical_decoded_frames is outside the decoded frame count")
    full_psnr = require_number(quality, "yuv420_psnr_full_video_db")
    min_psnr = require_number(quality, "yuv420_psnr_min_modified_frame_db")
    mean_ssim = require_number(quality, "luma_ssim_mean")
    min_ssim = require_number(quality, "luma_ssim_min")
    if full_psnr < min_psnr or not (-1 <= min_ssim <= mean_ssim <= 1):
        raise ValueError("decoded_quality PSNR/SSIM measurements are inconsistent")
    native_metrics = metrics["native_metrics"]
    for field in ("candidate_capacity_bits", "bits_embedded"):
        if type(native_metrics.get(field)) is not int or native_metrics[field] < 0:
            raise ValueError(f"native_metrics.{field} must be a non-negative integer")
    if native_metrics["bits_embedded"] <= 0:
        raise ValueError("native stream must report positive embedded payload bits")
    if native_metrics["candidate_capacity_bits"] < native_metrics["bits_embedded"]:
        raise ValueError("native candidate capacity is smaller than embedded payload bits")
    for field in (
        "patched_idr_segments", "idr_segment_count", "idr_service_samples", "idr_service_sample_limit",
    ):
        if type(native_metrics.get(field)) is not int or native_metrics[field] < 0:
            raise ValueError(f"native_metrics.{field} must be a non-negative integer")
    if (native_metrics["idr_segment_count"] <= 0 or native_metrics["idr_service_sample_limit"] != 4096
            or native_metrics["idr_service_samples"] != min(
                native_metrics["idr_segment_count"], native_metrics["idr_service_sample_limit"],
            ) or native_metrics["idr_segment_count"] < native_metrics["patched_idr_segments"]):
        raise ValueError("native IDR service sample counts are inconsistent")
    for field in ("idr_service_p50_ms", "idr_service_p95_ms"):
        value = native_metrics.get(field)
        if not finite_number(value) or value < 0:
            raise ValueError(f"native_metrics.{field} must be a finite non-negative number")
    if native_metrics["idr_service_p50_ms"] > native_metrics["idr_service_p95_ms"]:
        raise ValueError("native IDR service p50 must not exceed p95")
    for field in ("segment_process_p50_ms", "segment_process_p95_ms"):
        require_number(native_metrics, field)
    if native_metrics["segment_process_p50_ms"] > native_metrics["segment_process_p95_ms"]:
        raise ValueError("native segment process p50 must not exceed p95")
    for field in ("segment_process_samples", "segment_process_sample_limit"):
        if type(native_metrics.get(field)) is not int or native_metrics[field] < 0:
            raise ValueError(f"native_metrics.{field} must be a non-negative integer")
    if (native_metrics["segment_process_sample_limit"] != 4096
            or native_metrics["segment_process_samples"] != min(
                native_metrics["patched_idr_segments"], native_metrics["segment_process_sample_limit"],
            )):
        raise ValueError("native segment process sample counts are inconsistent")
    full_capacity = metrics["full_stream_capacity"]
    for field in ("idr_segments", "raw_candidate_signs", "candidate_capacity_bits", "max_bits_per_idr"):
        if type(full_capacity.get(field)) is not int or full_capacity[field] < 0:
            raise ValueError(f"full_stream_capacity.{field} must be a non-negative integer")
    if (full_capacity["idr_segments"] <= 0 or full_capacity["max_bits_per_idr"] <= 0
            or full_capacity["raw_candidate_signs"] < full_capacity["candidate_capacity_bits"]
            or full_capacity["candidate_capacity_bits"] <= 0
            or full_capacity["candidate_capacity_bits"] > full_capacity["idr_segments"] * full_capacity["max_bits_per_idr"]):
        raise ValueError("full stream candidate capacity is inconsistent with its measured bounds")
    for group_name in ("native_resources", "capture_process_tree_resources"):
        group = metrics[group_name]
        for field in ("sample_count", "sample_interval_ms", "peak_rss_bytes"):
            if type(group.get(field)) is not int or group[field] <= 0:
                raise ValueError(f"{group_name}.{field} must be a positive integer")
        require_number(group, "cpu_seconds", label=f"{group_name}.cpu_seconds")
        require_number(group, "wall_seconds", positive=True, label=f"{group_name}.wall_seconds")
    flow = metrics["flow_control"]
    flow_integer_fields = (
        "dropped_input_chunks", "input_chunks", "input_bytes", "input_chunk_limit_bytes",
        "max_input_chunk_bytes", "input_drain_count", "max_native_stdin_buffer_bytes",
        "native_stdin_write_drain_samples",
        "native_stdin_high_water_bytes", "output_chunks", "output_chunk_limit_bytes",
        "max_output_chunk_bytes", "native_stdout_to_websocket_send_samples",
        "native_stdout_read_wait_samples",
    )
    for field in flow_integer_fields:
        if type(flow.get(field)) is not int or flow[field] < 0:
            raise ValueError(f"flow_control.{field} must be a non-negative integer")
    if (flow["dropped_input_chunks"] != 0 or flow["input_chunks"] <= 0 or flow["output_chunks"] <= 0
            or flow["input_bytes"] <= 0 or flow["input_drain_count"] != flow["input_chunks"]
            or flow["input_chunk_limit_bytes"] <= 0 or flow["output_chunk_limit_bytes"] <= 0
            or flow["native_stdin_high_water_bytes"] <= 0
            or flow["max_input_chunk_bytes"] > flow["input_chunk_limit_bytes"]
            or flow["max_output_chunk_bytes"] > flow["output_chunk_limit_bytes"]
            or flow["max_native_stdin_buffer_bytes"] > (
                flow["native_stdin_high_water_bytes"] + flow["max_input_chunk_bytes"]
            )):
        raise ValueError("camera stream flow-control measurements are inconsistent or report dropped input chunks")
    require_number(flow, "input_drain_wait_ms_total", label="flow_control.input_drain_wait_ms_total")
    for prefix, expected_count in (
        ("native_stdin_write_drain", flow["input_chunks"]),
        ("native_stdout_to_websocket_send", flow["output_chunks"]),
        ("native_stdout_read_wait", flow["output_chunks"] + 1),
    ):
        sample_count = flow[f"{prefix}_samples"]
        if sample_count != min(expected_count, 4096):
            raise ValueError(f"flow_control.{prefix}_samples is inconsistent with bounded sample count")
        p50 = require_number(flow, f"{prefix}_p50_ms", label=f"flow_control.{prefix}_p50_ms")
        p95 = require_number(flow, f"{prefix}_p95_ms", label=f"flow_control.{prefix}_p95_ms")
        if p50 > p95:
            raise ValueError(f"flow_control.{prefix} p50 must not exceed p95")
    channel_latency = metrics["camera_pipe_to_client_nal_latency"]
    if channel_latency.get("measurement") not in {
        "ffmpeg_stdout_nal_completion_to_websocket_testclient_nal_completion",
        "ffmpeg_stdout_nal_completion_to_websocket_loopback_tcp_nal_completion",
    }:
        raise ValueError("camera_pipe_to_client_nal_latency.measurement is unsupported")
    if type(channel_latency.get("nal_count")) is not int or channel_latency["nal_count"] <= 0:
        raise ValueError("camera_pipe_to_client_nal_latency.nal_count must be a positive integer")
    channel_p50 = require_number(
        channel_latency, "p50_ms", label="camera_pipe_to_client_nal_latency.p50_ms",
    )
    channel_p95 = require_number(
        channel_latency, "p95_ms", label="camera_pipe_to_client_nal_latency.p95_ms",
    )
    if channel_p50 > channel_p95:
        raise ValueError("camera pipe-to-client NAL latency p50 must not exceed p95")
    channel_components = (
        "camera_read_to_send_start_p50_ms", "camera_read_to_send_start_p95_ms",
        "send_start_to_client_receive_p50_ms", "send_start_to_client_receive_p95_ms",
    )
    component_values = {
        field: require_number(channel_latency, field, label=f"camera_pipe_to_client_nal_latency.{field}")
        for field in channel_components
    }
    if (component_values["camera_read_to_send_start_p50_ms"]
            > component_values["camera_read_to_send_start_p95_ms"]
            or component_values["send_start_to_client_receive_p50_ms"]
            > component_values["send_start_to_client_receive_p95_ms"]):
        raise ValueError("camera NAL latency component p50 must not exceed p95")
    for prefix in ("input_nal_completion_interarrival", "output_nal_completion_interarrival"):
        p50 = require_number(channel_latency, f"{prefix}_p50_ms", label=f"camera_pipe_to_client_nal_latency.{prefix}_p50_ms")
        p95 = require_number(channel_latency, f"{prefix}_p95_ms", label=f"camera_pipe_to_client_nal_latency.{prefix}_p95_ms")
        if p50 > p95:
            raise ValueError(f"camera_pipe_to_client_nal_latency.{prefix} p50 must not exceed p95")
    if not isinstance(metrics["capture_device_name"], str) or not metrics["capture_device_name"].strip():
        raise ValueError("capture_device_name must be a non-empty string")
    encoder = metrics["capture_encoder"]
    if not isinstance(encoder, dict) or any(field not in encoder for field in REQUIRED_ENCODER_FIELDS):
        raise ValueError("capture_encoder is missing its pinned profile fields")
    if not isinstance(metrics["resolution"], str) or metrics["resolution"] != encoder["resolution"]:
        raise ValueError("resolution must match the pinned capture encoder resolution")
    if (encoder["codec"] != "libx264" or encoder["preset"] != "ultrafast"
            or encoder["profile"] != "baseline"
            or encoder["coder"] != 0 or encoder["entropy_coding"] != "CAVLC"
            or encoder["pixel_format"] != "yuv420p" or encoder["resolution"] != "352x288"
            or encoder["requested_fps"] != 30 or encoder["qp"] != 22 or encoder["gop"] != 1
            or encoder["fps_mode"] != "passthrough"
            or encoder["x264_params"] != "keyint=1:min-keyint=1:scenecut=0:repeat-headers=1"):
        raise ValueError("capture_encoder differs from the supported Baseline/CAVLC all-intra fps_mode=passthrough profile")
    environment = metrics["run_environment"]
    if not isinstance(environment, dict) or any(field not in environment for field in REQUIRED_ENVIRONMENT_FIELDS):
        raise ValueError("run_environment is missing reproducibility metadata")
    for field in ("hostname", "os", "architecture", "cpu_model", "python_version", "ffmpeg_path", "ffmpeg_version", "native_cli_path"):
        if not isinstance(environment[field], str) or not environment[field].strip():
            raise ValueError(f"run_environment.{field} must be a non-empty string")
    for field in ("logical_cpu_count", "ram_total_bytes"):
        if type(environment[field]) is not int or environment[field] <= 0:
            raise ValueError(f"run_environment.{field} must be a positive integer")
    digest = environment["native_cli_sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("run_environment.native_cli_sha256 must be a lowercase SHA-256 digest")


def persist_camera_run(destination: Path, metrics: dict[str, Any]) -> dict[str, Any]:
    """Atomically append one passing run, preserving existing JSON history."""
    _validate_metrics(metrics)
    destination = Path(destination)
    if destination.exists():
        try:
            document = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not read existing benchmark artifact {destination}") from exc
    else:
        document = {
            "benchmark": "physical camera -> authenticated WebSocket -> native H.264 CAVLC steganography",
            "measured_at": dt.date.today().isoformat(),
            "runs": [],
        }
    if not isinstance(document, dict) or not isinstance(document.get("runs"), list):
        raise ValueError("benchmark artifact must be a JSON object with a runs array")
    existing_numbers = [
        entry["run"] for entry in document["runs"]
        if isinstance(entry, dict) and isinstance(entry.get("run"), int) and not isinstance(entry.get("run"), bool)
    ]
    run_number = max(existing_numbers, default=0) + 1
    measured_active_fps = metrics["stego_frames"] / metrics["active_stream_seconds"]
    run = {
        "run": run_number,
        "run_type": f"{float(metrics['capture_duration_seconds']):g}-second physical camera E2E with Groth16 proof",
        **metrics,
        "active_fps_gate": {
            "minimum_active_stream_fps": metrics["capture_encoder"]["requested_fps"],
            "measured_active_stream_fps": measured_active_fps,
            "reported_active_stream_frame_rate_fps": metrics["active_stream_frame_rate_fps"],
            "passed": measured_active_fps >= metrics["capture_encoder"]["requested_fps"],
            "frame_accounting": "captured_frames == stego_frames with fps_mode=passthrough",
        },
    }
    document["runs"].append(run)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, destination)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return run


def _default_results_path() -> Path:
    existing = sorted(RESULTS_DIR.glob("realtime_camera_runs_*.json"))
    if existing:
        return existing[-1]
    return RESULTS_DIR / f"realtime_camera_runs_{dt.date.today():%Y%m%d}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=5.0, help="camera capture duration in seconds (1..300)")
    parser.add_argument("--results", type=Path, default=None, help="JSON results file to append to")
    args = parser.parse_args(argv)
    if not 1.0 <= args.duration <= 300.0:
        parser.error("--duration must be between 1 and 300 seconds")
    if not os.environ.get("ZK_STEGO_CAMERA_NAME"):
        parser.error("set ZK_STEGO_CAMERA_NAME to an FFmpeg DirectShow video device")

    environment = os.environ.copy()
    environment["ZK_STEGO_CAMERA_DURATION_SECONDS"] = str(args.duration)
    configured_native_cli = environment.get("ZK_STEGO_NATIVE_CLI")
    if configured_native_cli:
        native_cli = Path(configured_native_cli)
    else:
        native_cli = (
            ROOT / "native" / "build" / "Release" / "zkstego_blind_bits.exe"
            if os.name == "nt"
            else ROOT / "native" / "edge-build" / "zkstego_blind_bits"
        )
    command = [sys.executable, str(ROOT / "src" / "runtest" / "test_native_camera_http.py")]
    # Capture + embed + strict decode + proof checks scale with capture duration; bound the
    # child so a wedged camera or native process cannot hang the recorder forever.
    child_timeout_seconds = CAMERA_TEST_TIMEOUT_BASE_SECONDS + 10.0 * args.duration
    try:
        result = subprocess.run(
            command, cwd=ROOT, env=environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=child_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        print(partial, end="")
        print(f"Camera E2E timed out after {child_timeout_seconds:.0f} s", file=sys.stderr)
        return 2
    print(result.stdout, end="")
    if result.returncode != 0:
        return result.returncode

    metric_lines = [line[len("LIVE_CAMERA_WS_METRICS "):] for line in result.stdout.splitlines()
                    if line.startswith("LIVE_CAMERA_WS_METRICS ")]
    if len(metric_lines) != 1:
        print(f"Expected one LIVE_CAMERA_WS_METRICS record, got {len(metric_lines)}", file=sys.stderr)
        return 2
    try:
        metrics = json.loads(metric_lines[0])
        metrics["run_environment"] = collect_run_environment(
            native_cli, camera_device_name=environment["ZK_STEGO_CAMERA_NAME"],
        )
        run = persist_camera_run(args.results or _default_results_path(), metrics)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"Could not persist successful camera metrics: {exc}", file=sys.stderr)
        return 2
    print("RECORDED_CAMERA_RUN " + json.dumps(run, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
