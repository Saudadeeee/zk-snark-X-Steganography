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
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.blind_sync import pack_blind_payload


CAPACITY_RE = re.compile(r"embedded\s+(\d+)\s+of\s+(\d+)\s+bits", re.I)
SUCCESS_RE = re.compile(r"embedded_bits\s*=\s*(\d+)", re.I)
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


def frame_transport_payload(application_payload: bytes) -> tuple[bytes, bytes]:
    """Return raw app payload and the canonical in-band blind envelope."""
    return application_payload, pack_blind_payload(application_payload)


def _run_measured(
    command: list[str], timeout_seconds: int = 1800, cwd: Path | None = None
) -> dict[str, Any]:
    """Run a child process while sampling its process-tree peak RSS and CPU."""
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
    )
    root = psutil.Process(process.pid)
    peak_rss = 0
    cpu_total = 0.0
    known: dict[int, psutil.Process] = {process.pid: root}
    while process.poll() is None:
        try:
            for child in root.children(recursive=True):
                known[child.pid] = child
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
            process.kill()
            break
        time.sleep(0.02)
    stdout, stderr = process.communicate()
    wall_seconds = time.perf_counter() - started
    # Capture the final process counters too; they can exceed the last poll.
    try:
        times = root.cpu_times()
        cpu_total = max(cpu_total, times.user + times.system)
        peak_rss = max(peak_rss, root.memory_info().rss)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return {
        "returncode": process.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "wall_seconds": wall_seconds,
        "process_tree_cpu_seconds": cpu_total,
        "process_tree_peak_rss_mb": peak_rss / (1024 * 1024),
        "timed_out": process.returncode is None,
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
        f"[0:v]settb=AVTB,setpts=N[ref];[1:v]settb=AVTB,setpts=N[dist];"
        f"[ref][dist]psnr=stats_file={psnr_log}[p];"
        f"[ref][dist]ssim=stats_file={ssim_log}[s]"
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
) -> dict[str, Any]:
    folder.mkdir(parents=True, exist_ok=True)
    encoded = folder / "stego.h264"
    application_payload, framed_payload = frame_transport_payload(bytes.fromhex(payload_hex))
    encode = _run_measured([
        encoder, "--input-y4m", str(source), "--output", str(encoded),
        "--payload-hex", framed_payload.hex(),
    ])
    native = parse_encoder_result(encode["returncode"], encode["stdout"], encode["stderr"])
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
        "passed": extract["returncode"] == 0,
        "wall_seconds": extract["wall_seconds"],
        "process_tree_cpu_seconds": extract["process_tree_cpu_seconds"],
        "process_tree_peak_rss_mb": extract["process_tree_peak_rss_mb"],
        "stdout": extract["stdout"].strip(),
        "stderr": extract["stderr"].strip(),
    }
    frames, quality = _metric_run(source, encoded, folder, ffmpeg)
    (folder / "frame_quality.json").write_text(
        json.dumps(frames, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    case["quality"] = {
        "matched_frames": len(frames),
        "mean_frame_psnr_db": _finite_mean([row["psnr_db"] for row in frames]),
        "mean_frame_ssim": _finite_mean([row["ssim"] for row in frames]),
        "quality_process_wall_seconds": quality["wall_seconds"],
        "quality_process_peak_rss_mb": quality["process_tree_peak_rss_mb"],
    }
    return case


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Native in-band H.264 pipeline matrix",
        "",
        f"Generated: {report['generated_utc']}",
        "",
        "> Transport benchmark only. A successful payload round-trip does not",
        "> prove that the payload is a valid lattice-ZK proof or that the target",
        "> application relation has been implemented.",
        "",
        "| Case | Input | Frames | Encode (s) | CPU (s) | Peak RSS (MB) | Result | Embedded bits | Blind extract | Mean PSNR (dB) | Mean SSIM |",
        "|---|---:|---:|---:|---:|---:|---|---:|---|---:|---:|",
    ]
    for case in report["cases"]:
        video = case.get("input_video", {})
        enc = case.get("encode", {})
        quality = case.get("quality", {})
        lines.append(
            "| {name} | {w}×{h} | {frames} | {wall} | {cpu} | {rss} | {status} | {bits} | {blind} | {psnr} | {ssim} |".format(
                name=case["name"], w=video.get("width", "-"), h=video.get("height", "-"),
                frames=video.get("frames", "-"), wall=_fmt(enc.get("wall_seconds")),
                cpu=_fmt(enc.get("process_tree_cpu_seconds")), rss=_fmt(enc.get("process_tree_peak_rss_mb")),
                status=enc.get("status", "error"), bits=enc.get("embedded_bits", "-"),
                blind=("PASS" if case.get("blind_extract", {}).get("passed") else "N/A/FAIL"),
                psnr=_fmt(quality.get("mean_frame_psnr_db")), ssim=_fmt(quality.get("mean_frame_ssim")),
            )
        )
    lines += [
        "",
        "PSNR and SSIM are arithmetic means over frame-matched FFmpeg per-frame",
        "logs; each case folder also retains `frame_quality.json` and raw metric",
        "logs. Capacity failures are reported as failures and have no quality",
        "score because the encoder does not publish a partial H.264 file.",
        "Peak RSS and CPU are sampled over the child process tree. Native encode",
        "and blind-extract stages are timed separately; no claim of real-time",
        "performance follows from this offline corpus run.",
        "",
    ]
    return "\n".join(lines)


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
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
                args.encoder, args.ffmpeg, args.ffprobe, extractor,
            )
            case["name"] = name
            case["variant"] = variant
            cases.append(case)
            print(f"[{case['encode']['status'].upper()}] {name}", flush=True)
    report = {
        "schema": "native-pipeline-matrix-v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "host": {"platform": sys.platform, "python": sys.version.split()[0]},
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
