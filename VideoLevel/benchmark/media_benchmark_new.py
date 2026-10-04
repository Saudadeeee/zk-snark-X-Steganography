"""Convert raw Y4M sources to supported all-intra H.264 and measure the native path.

The output is a host-side experiment. Upscaled resolutions are explicitly marked
as derived from CIF source material; they are not native high-resolution scenes.
Each sample must pass native keyed embed, blind extraction, and strict
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
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from src.camera_proof import frame_bits_for_message, parse_payload, verify_payload
from src.camera_registry import CameraRegistry, camera_public_key, new_camera_secret
from src.native_blind_contract import segment_schedule
from src.video_binding import MODE_VIDEO, binding_digest, native_video_digest
from src.zk_proof import (
    PROOF_SIZE_BYTES,
    CameraProofBridge,
    pack_payload,
    proof_to_bytes,
)

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
NATIVE_CANDIDATES = (
    ROOT / "native" / "build" / "Release" / "zkstego_blind_bits.exe",
    ROOT / "native" / "build" / "zkstego_blind_bits",
)
INSPECT_CANDIDATES = (
    ROOT / "native" / "build" / "Release" / "zkstego_inspect.exe",
    ROOT / "native" / "build" / "zkstego_inspect",
)
RESOLUTIONS = ((352, 288), (640, 480), (1280, 960))
QP = 22
# Protocol default cap (README, demo, service): changes are spread over many IDRs.
PER_IDR_MAX_BITS = 64
MAX_PAYLOAD_BYTES = 4096
# Every case carries the real camera payload: [format][mode][len][message][129-byte Groth16 proof],
# proving that a registered camera vouches for this video (masked digest) and message.
MESSAGE = "zkstego benchmark: Groth16 proof carried in CAVLC trailing-one signs".encode("utf-8")
REGISTRY_CAMERAS = 8


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


def _inspect_binary() -> Path:
    for candidate in INSPECT_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise RuntimeError("native zkstego_inspect executable not found; build native Release first")


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
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    # Read stdout/stderr and write stdin on threads: a child that writes more than
    # the OS pipe buffer must never block while this loop is only sampling resources.
    captured: dict[str, bytes] = {}
    readers = [threading.Thread(target=lambda name=name, pipe=pipe: captured.__setitem__(name, pipe.read()), daemon=True)
               for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr))]

    def feed_stdin() -> None:
        try:
            process.stdin.write(stdin)
        except (BrokenPipeError, OSError):
            pass
        finally:
            process.stdin.close()

    writer = threading.Thread(target=feed_stdin, daemon=True)
    for thread in (*readers, writer):
        thread.start()
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
    for thread in (writer, *readers):
        thread.join()
    stdout, stderr = captured.get("stdout", b""), captured.get("stderr", b"")
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
                       "-filter_complex", prep + compare, "-f", "null", "-"])
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


# Native messages for "no v3 frame under this key" (the frame has no MAC).
FRAME_NOT_FOUND_MARKERS = (
    "CAVLC frame version is invalid",
    "CAVLC frame length",
    "CAVLC stream version is invalid",
    "CAVLC stream length exceeds configured maximum",
    "ended before payload",
    "blind schedule capacity is insufficient",
)


def extract_payload(native: Path, stego_path: Path, key: bytes,
                    max_bits: int = PER_IDR_MAX_BITS) -> tuple[int, bytes, str, float]:
    """Blind file-mode extraction (key on stdin); returns (exit, payload hex, stderr, wall ms)."""
    started = time.perf_counter()
    result = _run([str(native), "extract-stream-auth", str(stego_path), "-", str(MAX_PAYLOAD_BYTES), str(max_bits)],
                  input_bytes=key.hex().encode("ascii") + b"\n")
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return result.returncode, result.stdout.strip(), result.stderr.decode(errors="replace"), elapsed_ms


def is_frame_not_found(returncode: int, stderr: str) -> bool:
    """Exit 2 is also used for I/O and parse errors; require a frame-not-found message."""
    return returncode == 2 and any(marker in stderr for marker in FRAME_NOT_FOUND_MARKERS)


def inspect_segments(inspect: Path, path: Path, max_bits: int = PER_IDR_MAX_BITS) -> dict[str, Any]:
    result = _run([str(inspect), str(path), "--segments", str(max_bits)])
    if result.returncode:
        raise RuntimeError(f"zkstego_inspect --segments failed for {path.name}: {result.stderr.decode(errors='replace')[-500:]}")
    return json.loads(result.stdout)


def _sign_bits(segments: dict[str, Any]) -> dict[tuple[int, int], int]:
    return {(item["nal_index"], item["rbsp_bit_offset"]): item["bit"]
            for segment in segments["segments"] for item in segment["candidates"]}


def sign_statistics(cover_segments: dict[str, Any], stego_segments: dict[str, Any],
                    key: bytes, frame_bit_count: int, max_bits: int = PER_IDR_MAX_BITS) -> dict[str, Any]:
    """Compare every trailing-one sign of cover and stego against the keyed schedule.

    Sign flag 1 means a -1 trailing one. A correct embed changes only scheduled
    positions, about half of them (whitened bits are uniform), so the share of
    negative signs over all candidates should barely move.
    """
    cover_bits, stego_bits = _sign_bits(cover_segments), _sign_bits(stego_segments)
    if cover_bits.keys() != stego_bits.keys():
        raise RuntimeError("cover and stego expose different candidate positions")
    scheduled = {(p.candidate.nal_index, p.candidate.rbsp_bit_offset)
                 for p in segment_schedule(stego_segments, key, frame_bit_count, max_bits)}
    changed = {position for position, bit in cover_bits.items() if stego_bits[position] != bit}
    total = len(cover_bits)
    cover_negative = sum(cover_bits.values())
    stego_negative = sum(stego_bits.values())
    p_cover, p_stego = cover_negative / total, stego_negative / total
    pooled = (cover_negative + stego_negative) / (2 * total)
    spread = math.sqrt(2 * pooled * (1 - pooled) / total) if 0 < pooled < 1 else 0.0
    return {
        "candidate_signs": total,
        "scheduled_positions": len(scheduled),
        "changed_signs": len(changed),
        "changed_outside_schedule": len(changed - scheduled),
        "changed_fraction_of_scheduled": len(changed) / len(scheduled) if scheduled else None,
        "idr_segments_with_changes": len({nal for nal, _ in changed}),
        "negative_sign_fraction_cover": p_cover,
        "negative_sign_fraction_stego": p_stego,
        "negative_sign_fraction_delta": p_stego - p_cover,
        "two_proportion_z": (p_stego - p_cover) / spread if spread else 0.0,
    }


@dataclass(frozen=True)
class CameraContext:
    """One registered camera (its secret and the registry it belongs to) plus the native CLI."""

    bridge: CameraProofBridge
    registry: CameraRegistry
    secret: int
    native: Path


def camera_context(native: Path, cameras: int = REGISTRY_CAMERAS) -> CameraContext:
    camera_secrets = [new_camera_secret() for _ in range(cameras)]
    registry = CameraRegistry([camera_public_key(secret) for secret in camera_secrets])
    return CameraContext(CameraProofBridge(ROOT / "circuits"), registry, camera_secrets[cameras // 2], native)


def make_zk_payload(ctx: CameraContext, message: bytes, cover: Path, stego_key: bytes) -> dict[str, Any]:
    """Digest the cover for this payload size, prove membership + binding, pack the payload."""
    frame_bits = frame_bits_for_message(len(message))
    started = time.perf_counter()
    digest = native_video_digest(ctx.native, cover, stego_key, frame_bits, PER_IDR_MAX_BITS)
    digest_ms = (time.perf_counter() - started) * 1000.0
    started = time.perf_counter()
    proof = ctx.bridge.prove(ctx.secret, ctx.registry, binding_digest(MODE_VIDEO, digest, message))
    prove_ms = (time.perf_counter() - started) * 1000.0
    payload = pack_payload(MODE_VIDEO, message, proof_to_bytes(proof))
    return {"payload": payload, "proof_bytes": PROOF_SIZE_BYTES, "digest_ms": digest_ms, "prove_ms": prove_ms,
            "frame_bits": frame_bits, "video_digest": digest.hex()}


def verify_zk_payload(ctx: CameraContext | None, payload_hex: bytes, stego: Path | None,
                      stego_key: bytes | None = None) -> dict[str, Any]:
    """Parse, digest the stego video and verify the proof against the registry root (the verify job's decision)."""
    malformed = {"verified": False, "reason": "malformed_proof_payload", "verify_ms": None, "message": None,
                 "video_bound": False}
    started = time.perf_counter()
    try:
        payload = bytes.fromhex(payload_hex.decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        return malformed
    if parse_payload(payload) is None or ctx is None:
        return malformed
    verdict = verify_payload(ctx.bridge, ctx.registry.root, payload, native_cli=ctx.native, stego=stego,
                             stego_key=stego_key, max_bits_per_idr=PER_IDR_MAX_BITS)
    return {"verified": verdict.valid, "reason": verdict.reason, "verify_ms": (time.perf_counter() - started) * 1000.0,
            "message": verdict.message, "video_bound": verdict.video_bound}


def run_media_benchmark(output_root: Path, sources: list[Path] | None = None,
                        resolutions: tuple[tuple[int, int], ...] = RESOLUTIONS,
                        max_frames: int | None = None) -> dict[str, Any]:
    raw_sources = sorted((sources or list(RAW_DIR.glob("*.y4m"))), key=lambda path: path.name.lower())
    if not raw_sources:
        raise RuntimeError(f"no .y4m sources found in {RAW_DIR}")
    native = _native_binary()
    inspect = _inspect_binary()
    ctx = camera_context(native)
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
            zk = make_zk_payload(ctx, MESSAGE, cover, key)
            payload_line = zk["payload"].hex().encode("ascii") + b"\n"
            native_record = _run_measured(
                [str(native), "embed-stream-auth-stdin", str(cover), str(stego), str(PER_IDR_MAX_BITS)],
                key.hex().encode("ascii") + b"\n" + payload_line,
            )
            emb_err = native_record["stderr"].decode(errors="replace")[-1000:]
            embedded = native_record["returncode"] == 0
            strict_result: subprocess.CompletedProcess[bytes] | None = None
            decoded_ok = False
            strict_decode_ms = None
            if embedded:
                started = time.perf_counter()
                strict_result = _run([_tool("ffmpeg"), "-v", "error", "-xerror", "-i", str(stego),
                                      "-f", "null", "-"])
                strict_decode_ms = (time.perf_counter() - started) * 1000.0
                decoded_ok = strict_result.returncode == 0 and _probe(stego)["frames"] == encoded_meta["frames"]
            recovered_code, recovered_hex, extract_error, extract_ms = (-1, b"", "not attempted", None)
            if embedded:
                recovered_code, recovered_hex, extract_error, extract_ms = extract_payload(native, stego, key)
            correct_key = recovered_code == 0 and recovered_hex.decode("ascii", errors="ignore") == zk["payload"].hex()
            verification = verify_zk_payload(ctx, recovered_hex, stego, key) if correct_key else {
                "verified": False, "reason": "not_extracted", "verify_ms": None, "message": None, "video_bound": False}
            groth16_ok = verification["verified"] and verification["video_bound"] and verification["message"] == MESSAGE
            wrong_key = os.urandom(32)
            wrong_code, _, wrong_error, wrong_extract_ms = (
                extract_payload(native, stego, wrong_key) if embedded else (-1, b"", "not attempted", None))
            wrong_key_rejected = is_frame_not_found(wrong_code, wrong_error)
            signs = (sign_statistics(inspect_segments(inspect, cover), inspect_segments(inspect, stego),
                                     key, zk["frame_bits"]) if embedded else None)
            measured = bool(capacity_ok and embedded and decoded_ok and correct_key and groth16_ok
                            and wrong_key_rejected and signs and signs["changed_outside_schedule"] == 0)
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
                lengths = {len(raw_psnr), len(raw_ssim), len(diff_psnr), len(diff_ssim)}
                if lengths != {encoded_meta["frames"]}:
                    raise RuntimeError(f"quality stats cover {sorted(lengths)} frames, expected {encoded_meta['frames']} for {stego.name}")
                frame_count = encoded_meta["frames"]
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
                "payload_bytes": len(zk["payload"]), "message_bytes": len(MESSAGE),
                "proof_bytes": zk["proof_bytes"], "frame_bits": zk["frame_bits"],
                "max_bits_per_idr": PER_IDR_MAX_BITS,
                "idr_segments_needed": math.ceil(zk["frame_bits"] / PER_IDR_MAX_BITS),
                "video_digest_ms": zk["digest_ms"], "prove_ms": zk["prove_ms"], "strict_decode_ms": strict_decode_ms,
                "extract_ms": extract_ms, "wrong_key_extract_ms": wrong_extract_ms,
                "groth16_verify_ms": verification["verify_ms"],
                "embedded": embedded, "strict_decode_ok": decoded_ok,
                "blind_correct_key_payload_ok": correct_key,
                "groth16_verified": groth16_ok, "video_bound": verification["video_bound"],
                "groth16_failure_reason": verification["reason"],
                "wrong_key_rejected": wrong_key_rejected,
                "sign_statistics": signs,
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
        "schema": "zkstego-media-benchmark-new-v4",
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
            "acceptance": "Passing rows require native capacity scan, native embed success, FFmpeg strict decode (-v error -xerror), exact blind extraction with the right key, a video-bound camera proof that verifies against the registry root (digest recomputed from the stego video), rejection with a wrong key, and no changed sign outside the keyed schedule.",
            "payload": "Each case uses a fresh 32-byte stego key; one camera of an 8-camera Poseidon registry proves membership and a binding of the cover's masked video digest and the message; the payload [format][mode][len][message][129-byte proof] travels in the v3 channel frame; max_bits_per_idr is the protocol default 64.",
            "zkp_boundary": "Groth16 proving runs before embedding on the host (not in the camera pixel path). The proof binds the masked digest of the whole video and the message, so replaying it into another video fails.",
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
