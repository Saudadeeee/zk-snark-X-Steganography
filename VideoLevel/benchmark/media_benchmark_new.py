"""Convert raw Y4M sources to supported all-intra H.264 and measure the native path.

The output is a host-side experiment. Upscaled resolutions are explicitly marked
as derived from CIF source material; they are not native high-resolution scenes.
Each sample must pass native authenticated embed, blind extraction, and strict
FFmpeg decode before it is included in the passing performance summary.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
NATIVE_CANDIDATES = (
    ROOT / "native" / "build" / "Release" / "zkstego_blind_bits.exe",
    ROOT / "native" / "build" / "zkstego_blind_bits",
)
RESOLUTIONS = ((352, 288), (640, 480), (1280, 960))
QP = 22
PER_IDR_MAX_BITS = 4096
PAYLOAD = b"native-cavlc-benchmark-payload-v1"


def _tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"required executable not found on PATH: {name}")
    return found


def _native_binary() -> Path:
    for candidate in NATIVE_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise RuntimeError("native zkstego_blind_bits executable not found; build native Release first")


def _run(args: list[str], *, input_bytes: bytes | None = None, timeout: int = 3600) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(args, input=input_bytes, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout, check=False)


def _probe(path: Path) -> dict[str, Any]:
    probe = _run([_tool("ffprobe"), "-v", "error", "-count_frames", "-select_streams", "v:0",
                  "-show_entries", "stream=width,height,profile,pix_fmt,avg_frame_rate,nb_read_frames",
                  "-of", "json", str(path)])
    if probe.returncode:
        raise RuntimeError(f"ffprobe failed for {path.name}: {probe.stderr.decode(errors='replace')[-500:]}")
    streams = json.loads(probe.stdout).get("streams", [])
    if not streams:
        raise RuntimeError(f"no video stream found: {path}")
    stream = streams[0]
    rate = stream.get("avg_frame_rate", "0/1").split("/")
    fps = float(rate[0]) / float(rate[1]) if len(rate) == 2 and float(rate[1]) else 0.0
    frames = int(stream.get("nb_read_frames", 0))
    return {"width": int(stream["width"]), "height": int(stream["height"]),
            "profile": stream.get("profile"), "pix_fmt": stream.get("pix_fmt"),
            "fps": fps, "fps_expr": stream.get("avg_frame_rate", "0/1"), "frames": frames,
            "duration_seconds": frames / fps if fps else None}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_measured(args: list[str], stdin: bytes, timeout: int = 3600) -> dict[str, Any]:
    start_ns = time.perf_counter_ns()
    process = psutil.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdin is not None
    process.stdin.write(stdin)
    process.stdin.close()
    peak_rss = 0
    peak_cpu = 0.0
    process_info = psutil.Process(process.pid)
    deadline = time.monotonic() + timeout
    while process.poll() is None:
        try:
            peak_rss = max(peak_rss, process_info.memory_info().rss)
            cpu = process_info.cpu_times()
            peak_cpu = max(peak_cpu, cpu.user + cpu.system)
        except psutil.Error:
            pass
        if time.monotonic() > deadline:
            process.kill()
            raise TimeoutError(f"process exceeded {timeout}s: {args[0]}")
        time.sleep(0.005)
    stdout = process.stdout.read() if process.stdout else b""
    stderr = process.stderr.read() if process.stderr else b""
    return {"returncode": int(process.returncode), "stdout": stdout, "stderr": stderr,
            "wall_ms": (time.perf_counter_ns() - start_ns) / 1e6,
            "peak_rss_bytes_sampled": peak_rss, "cpu_seconds_sampled": peak_cpu}


def _encode_args(source: Path, output: Path, width: int, height: int,
                 max_frames: int | None = None, fps_expr: str | None = None) -> list[str]:
    args = [
        _tool("ffmpeg"), "-v", "error", "-y", "-i", str(source),
        "-vf", f"scale={width}:{height}:flags=lanczos,format=yuv420p",
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
        "-profile:v", "baseline", "-qp", str(QP), "-g", "1", "-bf", "0",
        "-threads", "1", "-pix_fmt", "yuv420p", "-an",
        "-x264-params", "keyint=1:min-keyint=1:scenecut=0:repeat-headers=1:slices=1:threads=1",
    ]
    if fps_expr and fps_expr != "0/1":
        args.extend(["-r", fps_expr, "-fps_mode", "cfr"])
    args.extend(["-f", "h264", str(output)])
    if max_frames is not None:
        args[args.index("-vf"):args.index("-vf")] = ["-frames:v", str(max_frames)]
    return args


def convert_sources_full(output_root: Path, sources: list[Path] | None = None) -> dict[str, Any]:
    """Convert every source in full at its native resolution, independently of sampled pipeline runs."""
    raw_sources = sorted((sources or list(RAW_DIR.glob("*.y4m"))), key=lambda path: path.name.lower())
    if not raw_sources:
        raise RuntimeError(f"no .y4m sources found in {RAW_DIR}")
    native = _native_binary()
    output_dir = output_root / "converted_h264_new"
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for source in raw_sources:
        metadata = _probe(source)
        destination = output_dir / f"{source.stem}__full__qp{QP}_allintra_new.h264"
        started = time.perf_counter()
        result = _run(_encode_args(source, destination, metadata["width"], metadata["height"],
                                   fps_expr=metadata["fps_expr"]), timeout=3600)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if result.returncode:
            records.append({"source": source.name, "status": "failed", "encode_ms": elapsed_ms,
                            "error": result.stderr.decode(errors="replace")[-1000:]})
            continue
        encoded = _probe(destination)
        playback_fps = metadata["fps"]
        playback_duration = encoded["frames"] / playback_fps if playback_fps else None
        records.append({"source": source.name, "status": "converted", "source_frames": metadata["frames"],
                        "source_duration_seconds": metadata["duration_seconds"], "source_fps": playback_fps,
                        "source_frame_rate": metadata["fps_expr"], "resolution": f"{metadata['width']}x{metadata['height']}",
                        "encoded_frames": encoded["frames"], "playback_duration_seconds_at_source_rate": playback_duration,
                        "profile": encoded["profile"], "pixel_format": encoded["pix_fmt"], "qp": QP,
                        "encode_ms": elapsed_ms, "output": str(destination.relative_to(output_root)),
                        "output_bytes": destination.stat().st_size, "sha256": _sha256_file(destination)})
    manifest = {"schema": "zkstego-full-y4m-conversion-new-v1", "created_utc": datetime.now(timezone.utc).isoformat(),
                "encoding": "libx264 Baseline/CAVLC QP 22, all-intra, one thread and one slice per IDR",
                "total": len(records), "converted": sum(item["status"] == "converted" for item in records),
                "failed": sum(item["status"] != "converted" for item in records), "results": records}
    (output_root / "conversion_manifest_new.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _parse_stat_file(path: Path, metric: str) -> list[float | None]:
    values: list[float | None] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if metric == "psnr":
            match = re.search(r"psnr_y:([^ ]+)", line)
        else:
            match = re.search(r"All:([^ ]+)", line)
        if not match:
            continue
        try:
            value = float(match.group(1))
            values.append(value if math.isfinite(value) else None)
        except ValueError:
            values.append(None)
    return values


def _quality(reference: Path, stego: Path, out_prefix: Path,
             scale: tuple[int, int] | None = None) -> tuple[list[float | None], list[float | None]]:
    ffmpeg = _tool("ffmpeg")
    w, h = scale if scale else (0, 0)
    for metric in ("psnr", "ssim"):
        stats = out_prefix.with_suffix(f".{metric}.log")
        # Filter option values use ':' as a separator; escape the Windows drive
        # colon after converting the filesystem path to FFmpeg-style slashes.
        stats_name = stats.resolve().as_posix().replace(":", r"\\:")
        if scale:
            prep = f"[0:v]scale={w}:{h}:flags=lanczos,format=yuv420p[ref];"
            compare = f"[ref][1:v]{metric}=stats_file={stats_name}:shortest=1"
        else:
            prep = "[0:v]format=yuv420p[ref];"
            compare = f"[ref][1:v]{metric}=stats_file={stats_name}:shortest=1"
        result = _run([ffmpeg, "-v", "error", "-i", str(reference), "-i", str(stego),
                       "-filter_complex", prep + compare, "-f", "null", "NUL"])
        if result.returncode:
            raise RuntimeError(f"{metric} failed for {stego.name}: {result.stderr.decode(errors='replace')[-500:]}")
    return (_parse_stat_file(out_prefix.with_suffix(".psnr.log"), "psnr"),
            _parse_stat_file(out_prefix.with_suffix(".ssim.log"), "ssim"))


def _summary(values: list[float | None]) -> dict[str, Any]:
    finite = [x for x in values if x is not None and math.isfinite(x)]
    return {"mean_finite": statistics.fmean(finite) if finite else None,
            "min_finite": min(finite) if finite else None,
            "p05_finite": sorted(finite)[max(0, int(0.05 * (len(finite) - 1)))] if finite else None,
            "identical_or_infinite_frames": len(values) - len(finite),
            "frames_measured": len(values)}


def _extract(native: Path, stego_path: Path, key: bytes) -> tuple[int, bytes, str]:
    result = _run([str(native), "extract-live-auth-stdin", "4096", str(PER_IDR_MAX_BITS)],
                  input_bytes=key.hex().encode("ascii") + b"\n" + stego_path.read_bytes())
    return result.returncode, result.stdout.strip(), result.stderr.decode(errors="replace")


def run_media_benchmark(output_root: Path, sources: list[Path] | None = None,
                        resolutions: tuple[tuple[int, int], ...] = RESOLUTIONS,
                        max_frames: int | None = None) -> dict[str, Any]:
    raw_sources = sorted((sources or list(RAW_DIR.glob("*.y4m"))), key=lambda path: path.name.lower())
    if not raw_sources:
        raise RuntimeError(f"no .y4m sources found in {RAW_DIR}")
    native = _native_binary()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
    run_dir = output_root / "media_new" / run_id
    encoded_dir = run_dir / "encoded_h264"
    stego_dir = run_dir / "stego_h264"
    stats_dir = run_dir / "frame_stats"
    for directory in (encoded_dir, stego_dir, stats_dir):
        directory.mkdir(parents=True, exist_ok=False)
    results: list[dict[str, Any]] = []
    frame_csv = run_dir / "quality_per_frame_new.csv"

    for source in raw_sources:
        source_meta = _probe(source)
        for width, height in resolutions:
            stem = f"{source.stem}__{width}x{height}__qp{QP}_allintra_new"
            cover = encoded_dir / f"{stem}.h264"
            encoded_started = time.perf_counter()
            encode_result = _run(_encode_args(source, cover, width, height, max_frames, source_meta["fps_expr"]), timeout=3600)
            encode_ms = (time.perf_counter() - encoded_started) * 1000.0
            if encode_result.returncode:
                results.append({"source": source.name, "resolution": f"{width}x{height}",
                                "source_frames": source_meta["frames"], "status": "encode_failed",
                                "error": encode_result.stderr.decode(errors="replace")[-1000:]})
                continue
            encoded_meta = _probe(cover)
            encoded_meta["fps"] = source_meta["fps"]
            encoded_meta["duration_seconds"] = encoded_meta["frames"] / source_meta["fps"] if source_meta["fps"] else None
            capacity_record = _run_measured(
                [str(native), "measure-live-capacity-stdin", str(PER_IDR_MAX_BITS)],
                cover.read_bytes(),
            )
            capacity_metrics = None
            if capacity_record["returncode"] == 0:
                try:
                    capacity_text = capacity_record["stdout"].decode("utf-8")
                    marker = "ZKSTEG_CAPACITY_METRICS "
                    if marker in capacity_text:
                        capacity_text = capacity_text.split(marker, 1)[1].strip().splitlines()[0]
                    capacity_metrics = json.loads(capacity_text)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    capacity_metrics = {"unparsed_stdout": capacity_record["stdout"].decode(errors="replace")[-500:]}
            capacity_ok = capacity_record["returncode"] == 0 and isinstance(capacity_metrics, dict) and "candidate_capacity_bits" in capacity_metrics
            stego = stego_dir / f"{stem}__stego_new.h264"
            key = os.urandom(32)
            payload_line = PAYLOAD.hex().encode("ascii") + b"\n"
            native_record = _run_measured(
                [str(native), "embed-stream-auth-stdin", str(cover), str(stego), str(PER_IDR_MAX_BITS)],
                key.hex().encode("ascii") + b"\n" + payload_line,
            )
            emb_err = native_record["stderr"].decode(errors="replace")[-1000:]
            embedded = native_record["returncode"] == 0
            strict_result: subprocess.CompletedProcess[bytes] | None = None
            decoded_ok = False
            if embedded:
                strict_result = _run([_tool("ffmpeg"), "-v", "error", "-xerror", "-i", str(stego),
                                      "-f", "null", "NUL"])
                decoded_ok = strict_result.returncode == 0
            recovered_code, recovered_hex, extract_error = (-1, b"", "not attempted")
            if embedded:
                recovered_code, recovered_hex, extract_error = _extract(native, stego, key)
            correct_key = recovered_code == 0 and recovered_hex.decode("ascii", errors="ignore") == PAYLOAD.hex()
            wrong_key = os.urandom(32)
            wrong_code, _, wrong_error = _extract(native, stego, wrong_key) if embedded else (-1, b"", "not attempted")
            wrong_key_rejected = wrong_code != 0
            measured = bool(capacity_ok and embedded and decoded_ok and correct_key and wrong_key_rejected)
            quality_records: dict[str, Any] = {}
            frame_rows: list[dict[str, Any]] = []
            if measured:
                raw_psnr, raw_ssim = _quality(source, stego, stats_dir / f"{stem}.source", (width, height))
                diff_psnr, diff_ssim = _quality(cover, stego, stats_dir / f"{stem}.incremental")
                quality_records = {
                    "source_to_stego_psnr_y": _summary(raw_psnr),
                    "source_to_stego_ssim": _summary(raw_ssim),
                    "cover_to_stego_psnr_y": _summary(diff_psnr),
                    "cover_to_stego_ssim": _summary(diff_ssim),
                }
                frame_count = min(map(len, (raw_psnr, raw_ssim, diff_psnr, diff_ssim)))
                for index in range(frame_count):
                    frame_rows.append({
                        "source": source.name, "resolution": f"{width}x{height}",
                        "frame_index": index + 1,
                        "source_to_stego_psnr_y": raw_psnr[index],
                        "source_to_stego_ssim": raw_ssim[index],
                        "cover_to_stego_psnr_y": diff_psnr[index],
                        "cover_to_stego_ssim": diff_ssim[index],
                    })
            record = {
                "source": source.name,
                "source_sha256": _sha256_file(source),
                "source_resolution": f"{source_meta['width']}x{source_meta['height']}",
                "source_frames": source_meta["frames"], "encoded_frames": encoded_meta["frames"],
                "encoded_duration_seconds": encoded_meta["duration_seconds"],
                "source_fps": source_meta["fps"],
                "source_duration_seconds": source_meta["duration_seconds"],
                "resolution": f"{width}x{height}",
                "resolution_origin": "native CIF" if (width, height) == (source_meta["width"], source_meta["height"]) else "scaled from CIF Y4M source",
                "encoder": "libx264", "profile": encoded_meta["profile"],
                "pixel_format": encoded_meta["pix_fmt"], "qp": QP,
                "gop": 1, "b_frames": 0, "threads": 1, "slices_per_idr": 1,
                "input_bytes": cover.stat().st_size,
                "stego_bytes": stego.stat().st_size if stego.exists() else None,
                "input_h264_sha256": _sha256_file(cover),
                "stego_h264_sha256": _sha256_file(stego) if stego.exists() else None,
                "capacity_measurement_ms": capacity_record["wall_ms"],
                "capacity_cpu_seconds_sampled": capacity_record["cpu_seconds_sampled"],
                "capacity_peak_rss_bytes_sampled": capacity_record["peak_rss_bytes_sampled"],
                "capacity_metrics": capacity_metrics,
                "capacity_measurement_ok": capacity_ok,
                "capacity_error": capacity_record["stderr"].decode(errors="replace")[-500:] if capacity_record["returncode"] else None,
                "encode_ms": encode_ms, "embed_ms": native_record["wall_ms"],
                "embed_cpu_seconds_sampled": native_record["cpu_seconds_sampled"],
                "embed_peak_rss_bytes_sampled": native_record["peak_rss_bytes_sampled"],
                "output_fps": encoded_meta["frames"] / (native_record["wall_ms"] / 1000.0) if native_record["wall_ms"] else None,
                "embedded": embedded, "strict_decode_ok": decoded_ok,
                "blind_correct_key_payload_ok": correct_key,
                "wrong_key_rejected": wrong_key_rejected,
                "wrong_key_error": wrong_error[-300:] if not wrong_key_rejected else None,
                "status": "passed" if measured else "failed",
                "embed_error": emb_err if not embedded else None,
                "extract_error": extract_error[-500:] if not correct_key else None,
                "quality": quality_records,
            }
            results.append(record)
            if frame_rows:
                with frame_csv.open("a", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(frame_rows[0]))
                    if handle.tell() == 0:
                        writer.writeheader()
                    writer.writerows(frame_rows)
            print(f"[{record['status']}] {source.name} -> {width}x{height}; {encoded_meta['frames']} frames; {record['embed_ms']:.1f} ms")

    passed = sum(record.get("status") == "passed" for record in results)
    record = {
        "schema": "zkstego-media-benchmark-new-v1",
        "run_id": run_id,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "host": {"platform": os.name, "python": os.sys.version,
                 "native_executable_sha256": hashlib.sha256(native.read_bytes()).hexdigest()},
        "methodology": {
            "source_directory": str(RAW_DIR), "source_files": [path.name for path in raw_sources],
            "resolutions": [f"{w}x{h}" for w, h in resolutions],
            "max_frames_per_case": max_frames,
            "encoding": "FFmpeg libx264, Baseline/CAVLC, QP 22, all-intra, one thread and one slice per IDR; this is a controlled host encode, not arbitrary camera H.264.",
            "encoder_version": _run([_tool("ffmpeg"), "-version"]).stdout.decode(errors="replace").splitlines()[0],
            "quality": "Per-frame FFmpeg PSNR Y and SSIM measured both from source Y4M to stego decode (total encode+embed distortion) and clean H.264 decode to stego decode (incremental embed distortion).",
            "fps_definition": "encoded frame count divided by native embed wall time; not camera acquisition FPS.",
            "resource_scope": "Native embed child process sampled every 5ms; sampled RSS/CPU may miss sub-sampling peaks.",
            "acceptance": "Passing rows require native capacity scan, native embed success, FFmpeg strict decode (-v error -xerror), exact blind extraction with right key, and rejection with wrong key.",
            "zkp_boundary": "Native authenticated CAVLC stream benchmark embeds HMAC-protected payloads. Groth16/PLONK proving is separately measured in zkp_new.json/pdf and is not claimed to be in the native streaming pixel path.",
        },
        "summary": {"total_cases": len(results), "passed": passed, "failed": len(results) - passed,
                    "all_passed": bool(results) and passed == len(results)},
        "results": results,
        "frame_quality_csv": str(frame_csv.relative_to(output_root)),
    }
    out_json = run_dir / "video_pipeline_new.json"
    out_json.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


if __name__ == "__main__":
    results = ROOT / "benchmark" / "results"
    conversion = convert_sources_full(results)
    print("CONVERSION", json.dumps({"converted": conversion["converted"], "failed": conversion["failed"]}), flush=True)
    result = run_media_benchmark(results, max_frames=30)
    print(json.dumps(result["summary"], indent=2))
