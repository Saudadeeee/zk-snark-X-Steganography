"""Reproducible measurements for the native in-band H.264 carrier.

This is a transport/quality benchmark, not evidence that the payload is a
valid zero-knowledge proof. Payloads are embedded in CAVLC residuals; there is
no SEI or proof sidecar in the encoded stream.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import psutil
from skimage import __version__ as SKIMAGE_VERSION
from skimage.metrics import structural_similarity

PROJECT_ROOT = Path(__file__).resolve().parents[1]


CAPACITY_RE = re.compile(r"embedded\s+(\d+)\s+of\s+(\d+)\s+bits", re.IGNORECASE)
SUCCESS_RE = re.compile(r"embedded_bits\s*=\s*(\d+)", re.IGNORECASE)
PSNR_RE = re.compile(r"n:(\d+)\s+.*?psnr_avg:([+\-\w.]+)")
SSIM_RE = re.compile(r"n:(\d+)\s+.*?\bAll:([+\-\w.]+)")


def parse_encoder_result(returncode: int, stdout: str, stderr: str) -> dict[str, Any]:
    """Normalize native CLI success, capacity exhaustion, and other errors."""
    combined = f"{stdout}\n{stderr}"
    capacity = CAPACITY_RE.search(combined)
    if capacity:
        return {
            "status": "capacity_failure",
            "embedded_bits": int(capacity.group(1)),
            "requested_bits": int(capacity.group(2)),
        }
    embedded = SUCCESS_RE.search(combined)
    if returncode == 0 and embedded:
        return {"status": "success", "embedded_bits": int(embedded.group(1))}
    return {"status": "error", "embedded_bits": None, "requested_bits": None}


def _parse_metric_value(raw: str) -> float:
    if raw.lower() in {"inf", "+inf", "infinity", "+infinity"}:
        return math.inf
    if raw.lower() in {"-inf", "-infinity"}:
        return -math.inf
    return float(raw)


def parse_metric_log(psnr_log: str, ssim_log: str) -> list[dict[str, Any]]:
    """Join FFmpeg's per-frame PSNR and SSIM stats by frame number."""
    psnr = {
        int(match.group(1)): _parse_metric_value(match.group(2))
        for match in PSNR_RE.finditer(psnr_log)
    }
    ssim = {
        int(match.group(1)): _parse_metric_value(match.group(2))
        for match in SSIM_RE.finditer(ssim_log)
    }
    return [
        {"frame": frame, "psnr_db": psnr[frame], "ssim": ssim[frame]}
        for frame in sorted(psnr.keys() & ssim.keys())
    ]


def label_ffmpeg_ssim(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve the source and precision of FFmpeg's all-plane SSIM field."""
    return [{**row, "ssim_ffmpeg_all": row["ssim"]} for row in rows]


def attach_luma_ssim(rows: list[dict[str, Any]], scores: list[float]) -> list[dict[str, Any]]:
    """Attach full-precision luma SSIM scores to matching FFmpeg frame rows."""
    if len(rows) != len(scores):
        raise ValueError(f"metric frame count mismatch: {len(rows)} rows vs {len(scores)} luma scores")
    return [
        {**row, "ssim_ffmpeg_all": row["ssim"], "ssim_luma": score}
        for row, score in zip(rows, scores, strict=True)
    ]


def compute_luma_ssim(reference: bytes, distorted: bytes, width: int, height: int) -> float:
    """Compute high-precision SSIM for one decoded 8-bit luma frame."""
    expected = width * height
    if len(reference) != expected or len(distorted) != expected:
        raise ValueError(f"luma frame byte length must be {expected}")
    ref_frame = np.frombuffer(reference, dtype=np.uint8).reshape(height, width)
    distorted_frame = np.frombuffer(distorted, dtype=np.uint8).reshape(height, width)
    return float(structural_similarity(ref_frame, distorted_frame, data_range=255))


def serialize_quality_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Represent non-finite PSNR explicitly so strict JSON remains valid."""
    serialized: list[dict[str, Any]] = []
    for source_row in rows:
        row = dict(source_row)
        psnr = float(row["psnr_db"])
        if math.isfinite(psnr):
            row["psnr_status"] = "finite"
        else:
            row["psnr_status"] = (
                "positive_infinity" if psnr > 0 else "negative_infinity" if psnr < 0 else "not_a_number"
            )
            row["psnr_db"] = None
        serialized.append(row)
    return serialized


def _read_exact(stream: Any, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def _luma_ssim_run(
    source: Path, encoded: Path, width: int, height: int, ffmpeg: str
) -> tuple[list[float], dict[str, float]]:
    """Stream paired luma frames through FFmpeg and compute full-precision SSIM."""
    command_base = [ffmpeg, "-hide_banner", "-loglevel", "error"]
    raw_output = ["-map", "0:v:0", "-fps_mode", "passthrough", "-pix_fmt", "gray", "-f", "rawvideo", "pipe:1"]
    processes = [
        subprocess.Popen(command_base + ["-i", str(path.resolve())] + raw_output, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        for path in (source, encoded)
    ]
    roots = [psutil.Process(process.pid) for process in processes]
    frame_size = width * height
    scores: list[float] = []
    peak_rss = 0
    child_cpu = 0.0
    known: dict[int, psutil.Process] = {root.pid: root for root in roots}
    python_process = psutil.Process()
    cpu_before = python_process.cpu_times()
    started = time.perf_counter()
    try:
        while True:
            ref_frame = _read_exact(processes[0].stdout, frame_size)
            dist_frame = _read_exact(processes[1].stdout, frame_size)
            if not ref_frame and not dist_frame:
                break
            if len(ref_frame) != frame_size or len(dist_frame) != frame_size:
                raise RuntimeError("decoded reference/stego frame counts or sizes differ")
            scores.append(compute_luma_ssim(ref_frame, dist_frame, width, height))
            for root in roots:
                try:
                    for child in root.children(recursive=True):
                        known[child.pid] = child
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            current_rss = 0
            current_cpu = 0.0
            for process in tuple(known.values()):
                try:
                    current_rss += process.memory_info().rss
                    times = process.cpu_times()
                    current_cpu += times.user + times.system
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            peak_rss = max(peak_rss, current_rss)
            child_cpu = max(child_cpu, current_cpu)
        return_codes = [process.wait() for process in processes]
        if any(return_code != 0 for return_code in return_codes):
            raise RuntimeError(f"FFmpeg luma decode failed with exit codes {return_codes}")
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait()
            if process.stdout:
                process.stdout.close()
    cpu_after = python_process.cpu_times()
    python_cpu = (cpu_after.user + cpu_after.system) - (cpu_before.user + cpu_before.system)
    return scores, {
        "wall_seconds": time.perf_counter() - started,
        "process_tree_cpu_seconds": child_cpu + python_cpu,
        "process_tree_peak_rss_mb": peak_rss / (1024 * 1024),
    }


def frame_transport_payload(application_payload: bytes) -> tuple[bytes, bytes]:
    """Return raw app payload and the canonical in-band blind envelope."""
    from src.blind_sync import pack_blind_payload

    return application_payload, pack_blind_payload(application_payload)


def _run_measured(
    command: list[str], timeout_seconds: float = 1800, cwd: Path | None = None
) -> dict[str, Any]:
    """Run a child process while sampling its process-tree peak RSS and CPU."""
    started = time.perf_counter()
    timed_out = False
    peak_rss = 0
    cpu_total = 0.0
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(command, stdout=stdout_file, stderr=stderr_file, cwd=cwd)
        root = psutil.Process(process.pid)
        known: dict[int, psutil.Process] = {process.pid: root}
        while process.poll() is None:
            try:
                known.update({child.pid: child for child in root.children(recursive=True)})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            current_rss = 0
            current_cpu = 0.0
            for child in tuple(known.values()):
                try:
                    current_rss += child.memory_info().rss
                    times = child.cpu_times()
                    current_cpu += times.user + times.system
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            peak_rss = max(peak_rss, current_rss)
            cpu_total = max(cpu_total, current_cpu)
            if time.perf_counter() - started > timeout_seconds:
                timed_out = True
                process.kill()
                break
            time.sleep(0.02)
        returncode = process.wait()
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read().decode("utf-8", errors="replace")
        stderr = stderr_file.read().decode("utf-8", errors="replace")
    wall_seconds = time.perf_counter() - started
    # Capture the final process counters too; they can exceed the last poll.
    try:
        times = root.cpu_times()
        cpu_total = max(cpu_total, times.user + times.system)
        peak_rss = max(peak_rss, root.memory_info().rss)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return {
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "wall_seconds": wall_seconds,
        "process_tree_cpu_seconds": cpu_total,
        "process_tree_peak_rss_mb": peak_rss / (1024 * 1024),
        "timed_out": timed_out,
    }


def _probe(path: Path, ffprobe: str) -> dict[str, Any]:
    command = [
        ffprobe, "-v", "error", "-select_streams", "v:0", "-count_frames",
        "-show_entries",
        "stream=width,height,r_frame_rate,avg_frame_rate,nb_read_frames,profile,pix_fmt",
        "-of", "json", str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    streams = json.loads(result.stdout).get("streams", [])
    if not streams:
        raise RuntimeError(f"ffprobe found no video stream: {path}")
    stream = streams[0]
    rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
    numerator, denominator = (int(part) for part in rate.split("/", 1))
    fps = numerator / denominator if denominator else 0.0
    frames = int(stream.get("nb_read_frames") or 0)
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": fps,
        "frame_rate": rate,
        "frames": frames,
        "duration_seconds": frames / fps if fps else None,
        "profile": stream.get("profile"),
        "pixel_format": stream.get("pix_fmt"),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_metric_filtergraph(psnr_log: str, ssim_log: str) -> str:
    """Build graph with relative log paths (avoids Windows drive-colon parsing)."""
    return (
        "[0:v]settb=AVTB,setpts=N,split=2[refp][refs];"
        "[1:v]settb=AVTB,setpts=N,split=2[distp][dists];"
        f"[refp][distp]psnr=stats_file={psnr_log}[p];"
        f"[refs][dists]ssim=stats_file={ssim_log}[s]"
    )


def _metric_run(source: Path, encoded: Path, folder: Path, ffmpeg: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    psnr_name = "psnr_per_frame.log"
    ssim_name = "ssim_per_frame.log"
    graph = build_metric_filtergraph(psnr_name, ssim_name)
    result = _run_measured([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(source.resolve()),
        "-i", str(encoded.resolve()), "-filter_complex", graph, "-map", "[p]", "-map",
        "[s]", "-f", "null", "-",
    ], cwd=folder)
    if result["returncode"] != 0:
        raise RuntimeError(f"FFmpeg quality comparison failed: {result['stderr'][-2000:]}")
    psnr_log = (folder / psnr_name).read_text(encoding="utf-8", errors="replace")
    ssim_log = (folder / ssim_name).read_text(encoding="utf-8", errors="replace")
    return parse_metric_log(psnr_log, ssim_log), result


def _finite_mean(values: list[float]) -> float | None:
    finite = [value for value in values if math.isfinite(value)]
    return sum(finite) / len(finite) if finite else None


def host_metadata() -> dict[str, Any]:
    """Describe the machine so timings are not detached from their hardware."""
    return {
        "platform": platform.platform(),
        "cpu_identifier": platform.processor() or platform.machine() or "unknown",
        "physical_cores": psutil.cpu_count(logical=False) or 0,
        "logical_processors": psutil.cpu_count(logical=True) or 0,
        "ram_total_bytes": psutil.virtual_memory().total,
        "numpy_version": np.__version__,
        "scikit_image_version": SKIMAGE_VERSION,
    }


def _prepare_scaled(source: Path, target: Path, width: int, height: int, ffmpeg: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    result = _run_measured([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(source),
        "-vf", f"scale={width}:{height}:flags=lanczos", "-pix_fmt", "yuv420p",
        "-fps_mode", "passthrough", "-f", "yuv4mpegpipe", str(target),
    ])
    if result["returncode"] != 0:
        raise RuntimeError(f"FFmpeg scale failed: {result['stderr'][-2000:]}")


def run_case(
    source: Path,
    folder: Path,
    payload_hex: str,
    encoder: str,
    ffmpeg: str,
    ffprobe: str,
    extractor_script: Path,
    precise_ssim: bool = False,
) -> dict[str, Any]:
    folder.mkdir(parents=True, exist_ok=True)
    encoded = folder / "stego.h264"
    application_payload, framed_payload = frame_transport_payload(bytes.fromhex(payload_hex))
    encode = _run_measured([
        encoder, "--input-y4m", str(source), "--output", str(encoded),
        "--payload-hex", framed_payload.hex(),
    ])
    native = parse_encoder_result(encode["returncode"], encode["stdout"], encode["stderr"])
    if encode["timed_out"]:
        native["status"] = "timeout"
    case: dict[str, Any] = {
        "source": str(source),
        "source_sha256": _sha256(source),
        "source_size_bytes": source.stat().st_size,
        "input_video": _probe(source, ffprobe),
        "application_payload_bytes": len(application_payload),
        "transport_envelope_bytes": len(framed_payload),
        "encode": {
            **native,
            "wall_seconds": encode["wall_seconds"],
            "process_tree_cpu_seconds": encode["process_tree_cpu_seconds"],
            "process_tree_peak_rss_mb": encode["process_tree_peak_rss_mb"],
            "timed_out": encode["timed_out"],
            "stdout": encode["stdout"].strip(),
            "stderr": encode["stderr"].strip(),
        },
        "final_video_published": encoded.is_file(),
    }
    if native["status"] != "success" or not encoded.is_file():
        partial = folder / "stego.h264.partial"
        case["partial_output_published"] = partial.exists()
        return case

    case["encoded_video"] = _probe(encoded, ffprobe)
    case["encoded_size_bytes"] = encoded.stat().st_size
    extract = _run_measured([
        sys.executable, str(extractor_script), str(encoded), payload_hex,
    ])
    case["blind_extract"] = {
        "passed": extract["returncode"] == 0 and not extract["timed_out"],
        "timed_out": extract["timed_out"],
        "wall_seconds": extract["wall_seconds"],
        "process_tree_cpu_seconds": extract["process_tree_cpu_seconds"],
        "process_tree_peak_rss_mb": extract["process_tree_peak_rss_mb"],
        "stdout": extract["stdout"].strip(),
        "stderr": extract["stderr"].strip(),
    }
    frames, quality = _metric_run(source, encoded, folder, ffmpeg)
    frames = label_ffmpeg_ssim(frames)
    luma_quality = None
    if precise_ssim:
        luma_scores, luma_quality = _luma_ssim_run(
            source, encoded, case["input_video"]["width"], case["input_video"]["height"], ffmpeg
        )
        frames = attach_luma_ssim(frames, luma_scores)
    (folder / "frame_quality.json").write_text(
        json.dumps(serialize_quality_rows(frames), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    case["quality"] = {
        "matched_frames": len(frames),
        "mean_frame_psnr_db": _finite_mean([row["psnr_db"] for row in frames]),
        "mean_frame_ssim_ffmpeg_all_rounded": _finite_mean([row["ssim_ffmpeg_all"] for row in frames]),
        "precise_luma_ssim_enabled": precise_ssim,
        "quality_process_wall_seconds": quality["wall_seconds"],
        "quality_process_cpu_seconds": quality["process_tree_cpu_seconds"],
        "quality_process_peak_rss_mb": quality["process_tree_peak_rss_mb"],
    }
    if luma_quality:
        case["quality"]["mean_frame_ssim_luma"] = _finite_mean([row["ssim_luma"] for row in frames])
        case["quality"]["quality_process_wall_seconds"] += luma_quality["wall_seconds"]
        case["quality"]["quality_process_cpu_seconds"] += luma_quality["process_tree_cpu_seconds"]
        case["quality"]["quality_process_peak_rss_mb"] = max(
            quality["process_tree_peak_rss_mb"], luma_quality["process_tree_peak_rss_mb"]
        )
    return case


def _markdown_report(report: dict[str, Any]) -> str:
    host = report.get("host", {})
    lines = [
        "# Native in-band H.264 pipeline matrix",
        "",
        f"Generated: {report['generated_utc']}",
        "",
        "## Measurement host",
        "",
        f"- OS/runtime: {host.get('platform', 'not recorded')} / Python {host.get('python', 'not recorded')}",
        f"- CPU identifier: {host.get('cpu_identifier', 'not recorded')}",
        f"- CPU cores: {host.get('physical_cores', 'not recorded')} physical / {host.get('logical_processors', 'not recorded')} logical",
        f"- Installed RAM: {_fmt(host.get('ram_total_bytes', 0) / (1024 ** 3), precision=2) if host.get('ram_total_bytes') else 'not recorded'} GiB",
        f"- Metric libraries: NumPy {host.get('numpy_version', 'not recorded')}; scikit-image {host.get('scikit_image_version', 'not recorded')}",
        "",
        "> Transport benchmark only. A successful payload round-trip does not",
        "> prove that the payload is a valid lattice-ZK proof or that the target",
        "> application relation has been implemented.",
        "",
        "| Case | Input | Duration (s) | Frames | Encode (s) | Encode (fps) | Encode CPU (s) | Encode RSS (MiB) | Result | Embedded bits | Blind test | Extract (s) | Extract CPU (s) | Extract peak RSS (MiB) | PSNR (dB) | FFmpeg SSIM all (6dp) | Luma SSIM (precise) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for case in report["cases"]:
        video = case.get("input_video", {})
        enc = case.get("encode", {})
        quality = case.get("quality", {})
        lines.append(
            "| {name} | {w}x{h} | {duration} | {frames} | {wall} | {encode_fps} | {cpu} | {rss} | {status} | {bits} | {blind} | {blind_s} | {blind_cpu} | {blind_rss} | {psnr} | {ssim_ffmpeg} | {ssim_luma} |".format(
                name=case["name"], w=video.get("width", "-"), h=video.get("height", "-"),
                frames=video.get("frames", "-"),
                duration=_fmt(video.get("duration_seconds")),
                wall=_fmt(enc.get("wall_seconds")),
                encode_fps=_fmt(video.get("frames", 0) / enc["wall_seconds"] if enc.get("wall_seconds") else None),
                cpu=_fmt(enc.get("process_tree_cpu_seconds")), rss=_fmt(enc.get("process_tree_peak_rss_mb")),
                status=enc.get("status", "error"), bits=enc.get("embedded_bits", "-"),
                blind=("PASS" if case.get("blind_extract", {}).get("passed") else "FAIL/N.A."),
                blind_s=_fmt(case.get("blind_extract", {}).get("wall_seconds")),
                blind_cpu=_fmt(case.get("blind_extract", {}).get("process_tree_cpu_seconds")),
                blind_rss=_fmt(case.get("blind_extract", {}).get("process_tree_peak_rss_mb")),
                psnr=_fmt(quality.get("mean_frame_psnr_db")),
                ssim_ffmpeg=_fmt(quality.get("mean_frame_ssim_ffmpeg_all_rounded"), precision=6),
                ssim_luma=_fmt(quality.get("mean_frame_ssim_luma"), precision=8),
            )
        )
    lines += [
        "",
        "PSNR and FFmpeg's all-plane SSIM are per-frame FFmpeg measurements.",
        "Optional luma SSIM is computed by scikit-image at full precision.",
        "Each case retains",
        "`frame_quality.json` and FFmpeg's raw metric",
        "logs. Capacity failures are reported as failures and have no quality",
        "score because the encoder does not publish a partial H.264 file.",
        "FFmpeg all-plane SSIM has six-decimal precision and is preserved in",
        "each frame row as `ssim_ffmpeg_all`; a reported `1.000000` means the",
        "score rounded to that display precision, not exact pixel equality.",
        "The optional luma SSIM is costly and is not enabled in the full matrix.",
        "RSS and CPU are",
        "sampled over the child process tree. Encode fps is frames / wall time.",
        "These are offline desktop measurements, not end-to-end proof latency",
        "or evidence of edge-device real-time operation.",
        "",
    ]
    return "\n".join(lines)


def _fmt(value: Any, precision: int = 3) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{precision}f}"
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+", type=Path, help="progressive YUV420 Y4M inputs")
    parser.add_argument("--encoder", required=True, help="path to zkstego_x264_y4m")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--payload-hex", default="a5", help="small round-trip payload for quality matrix")
    parser.add_argument(
        "--precise-ssim", action="store_true",
        help="compute expensive full-precision luma SSIM for every frame",
    )
    parser.add_argument(
        "--scale", action="append", default=[], metavar="WIDTHxHEIGHT",
        help="also make a real FFmpeg-scaled Y4M variant for each source",
    )
    args = parser.parse_args()
    root = PROJECT_ROOT
    extractor = root / "native" / "x264_fork" / "tests" / "blind_extract_smoke.py"
    output_dir = args.output_dir or (
        root / "benchmark" / "results" / f"native_pipeline_matrix_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    for source in args.sources:
        if not source.is_file():
            parser.error(f"input does not exist: {source}")
        variants = [(source, "original")]
        for scale in args.scale:
            match = re.fullmatch(r"(\d+)x(\d+)", scale.lower())
            if not match:
                parser.error(f"invalid --scale {scale!r}; expected WIDTHxHEIGHT")
            width, height = map(int, match.groups())
            if width % 2 or height % 2:
                parser.error("YUV420 dimensions must be even")
            scaled = output_dir / "prepared" / f"{source.stem}_{width}x{height}.y4m"
            _prepare_scaled(source, scaled, width, height, args.ffmpeg)
            variants.append((scaled, f"scaled_{width}x{height}"))
        for input_path, variant in variants:
            name = f"{source.stem}_{variant}"
            print(f"[RUN] {name}", flush=True)
            case = run_case(
                input_path, output_dir / name, args.payload_hex,
                args.encoder, args.ffmpeg, args.ffprobe, extractor, args.precise_ssim,
            )
            case["name"] = name
            case["variant"] = variant
            cases.append(case)
            print(f"[{case['encode']['status'].upper()}] {name}", flush=True)
    report = {
        "schema": "native-pipeline-matrix-v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "host": {**host_metadata(), "python": sys.version.split()[0]},
        "encoder": str(Path(args.encoder).resolve()),
        "encoder_sha256": _sha256(Path(args.encoder)),
        "ffmpeg": args.ffmpeg,
        "ffprobe": args.ffprobe,
        "payload_hex": args.payload_hex,
        "cases": cases,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    (output_dir / "summary.md").write_text(_markdown_report(report), encoding="utf-8")
    print(f"[SAVED] {output_dir / 'summary.md'}", flush=True)
    return 0 if all(case["encode"]["status"] == "success" and case.get("blind_extract", {}).get("passed") for case in cases) else 2


if __name__ == "__main__":
    raise SystemExit(main())
