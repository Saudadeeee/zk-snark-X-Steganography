"""End-to-end ZK steganography benchmark: stage timing, attack matrix and host facts.

Every trial runs the real chain on one H.264 clip: Groth16 prove -> pack ->
native embed (protocol v3, 64 bits per IDR) -> strict FFmpeg decode -> blind
extraction -> unpack -> mandatory Groth16 verify. The attack matrix then feeds
modified streams and mismatched payloads through the same verify decision the
HTTP verify job uses, and records whether each one is accepted or why it is
rejected. Nothing here is estimated; every number is a measured call.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import statistics
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from benchmark.media_benchmark_new import (
    MESSAGE,
    PER_IDR_MAX_BITS,
    QP,
    CameraContext,
    _encode_args,
    _inspect_binary,
    _native_binary,
    _probe,
    _run,
    _run_measured,
    _sha256_file,
    _tool,
    camera_context,
    extract_payload,
    inspect_segments,
    is_frame_not_found,
    make_zk_payload,
    sign_statistics,
    verify_zk_payload,
)
from src.native_blind_contract import FRAME_VERSION, segment_schedule
from src.video_binding import MODE_VIDEO
from src.zk_proof import PAYLOAD_HEADER_BYTES, PROOF_SIZE_BYTES, pack_payload

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmark" / "results"
E2E_SOURCE = ROOT / "data" / "raw" / "foreman_cif_300f.y4m"
FALLBACK_SOURCE = ROOT / "data" / "raw" / "foreman_cif.y4m"
REPLAY_SOURCE = ROOT / "data" / "raw" / "akiyo_cif.y4m"
# Channel frame v3: version 1 B + length 2 B around the payload, no MAC.
FRAME_OVERHEAD = 3


# ----------------------------------------------------------------- host facts

def _first_line(args: list[str]) -> str | None:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (result.stdout or result.stderr).strip()
    return text.splitlines()[0].strip() if text else None


def _cpu_name() -> str:
    if os.name == "nt":
        name = _first_line(["powershell", "-NoProfile", "-Command",
                            "(Get-CimInstance Win32_Processor | Select-Object -First 1).Name"])
        if name:
            return name
    return platform.processor() or platform.machine()


def collect_environment() -> dict[str, Any]:
    """Host, toolchain and source revision the measurements belong to."""
    snarkjs_package = ROOT / "circuits" / "node_modules" / "snarkjs" / "package.json"
    snarkjs_version = (json.loads(snarkjs_package.read_text(encoding="utf-8")).get("version")
                       if snarkjs_package.is_file() else None)
    status = _first_line(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"])
    native, inspect = _native_binary(), _inspect_binary()
    return {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "os": platform.platform(),
        "cpu": _cpu_name(),
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "ram_gb": round(psutil.virtual_memory().total / 1e9, 1),
        "python": platform.python_version(),
        "ffmpeg": _first_line([_tool("ffmpeg"), "-version"]),
        "node": _first_line(["node", "--version"]),
        "snarkjs": snarkjs_version,
        "git_commit": _first_line(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"]),
        "git_tracked_changes": bool(status),
        "native_blind_bits_sha256": _sha256_file(native),
        "native_inspect_sha256": _sha256_file(inspect),
    }


# ------------------------------------------------------------ verify decision

def verify_decision(native: Path, ctx: CameraContext, stego: Path, key: bytes) -> dict[str, Any]:
    """Same outcome classes as the HTTP verify job: accepted or the rejection reason."""
    code, payload_hex, stderr, extract_ms = extract_payload(native, stego, key)
    if code != 0:
        reason = "payload_not_found" if is_frame_not_found(code, stderr) else "stream_rejected_by_parser"
        return {"outcome": "rejected", "reason": reason, "extract_ms": extract_ms,
                "detail": stderr.strip().splitlines()[-1][:200] if stderr.strip() else f"exit {code}"}
    verification = verify_zk_payload(ctx, payload_hex, stego, key)
    if not verification["verified"]:
        return {"outcome": "rejected", "reason": verification["reason"], "extract_ms": extract_ms,
                "detail": "payload frame found, but the Groth16 check failed"}
    return {"outcome": "accepted", "reason": None, "extract_ms": extract_ms,
            "detail": f"message {len(verification['message'])} B, proof verified"}


def _strict_decode_ok(path: Path) -> bool:
    result = _run([_tool("ffmpeg"), "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"])
    return result.returncode == 0


# ------------------------------------------------------------- stream edits

def file_offset_of_rbsp_bit(data: bytes, nal: dict[str, Any], rbsp_bit: int) -> int:
    """Byte offset in the Annex-B file of an RBSP bit (NAL header excluded, EPBs skipped)."""
    payload_start = nal["offset"] + nal["start_code_bytes"] + 1
    target, rbsp_index, zeros = rbsp_bit // 8, 0, 0
    for ebsp_index in range(nal["ebsp_bytes"]):
        byte = data[payload_start + ebsp_index]
        if zeros >= 2 and byte == 0x03:
            zeros = 0
            continue
        if rbsp_index == target:
            return payload_start + ebsp_index
        zeros = zeros + 1 if byte == 0 else 0
        rbsp_index += 1
    raise ValueError("RBSP bit lies outside its NAL")


def flip_sign_bit(data: bytes, nals: dict[int, dict[str, Any]], nal_index: int, rbsp_bit: int) -> bytes:
    offset = file_offset_of_rbsp_bit(data, nals[nal_index], rbsp_bit)
    edited = bytearray(data)
    edited[offset] ^= 0x80 >> (rbsp_bit % 8)
    return bytes(edited)


def _nal_table(inspect: Path, path: Path) -> dict[int, dict[str, Any]]:
    full = _run([str(inspect), str(path)])
    if full.returncode:
        raise RuntimeError(full.stderr.decode(errors="replace")[-300:])
    return {row["index"]: row for row in json.loads(full.stdout)["nals"]}


def _sign_at(inspect: Path, path: Path, nal_index: int, rbsp_bit: int) -> int:
    for segment in inspect_segments(inspect, path)["segments"]:
        for item in segment["candidates"]:
            if item["nal_index"] == nal_index and item["rbsp_bit_offset"] == rbsp_bit:
                return item["bit"]
    raise RuntimeError("candidate not found after edit")


# ------------------------------------------------------------------ helpers

def _cover(work: Path, source: Path | None = None) -> tuple[Path, dict[str, Any]]:
    source = source or (E2E_SOURCE if E2E_SOURCE.is_file() else FALLBACK_SOURCE)
    meta = _probe(source)
    cover = work / f"{source.stem}__qp{QP}_allintra_e2e.h264"
    result = _run(_encode_args(source, cover, meta["width"], meta["height"], fps_expr=meta["fps_expr"]))
    if result.returncode:
        raise RuntimeError(f"cover encode failed: {result.stderr.decode(errors='replace')[-300:]}")
    encoded = _probe(cover)
    return cover, {"source": source.name, "resolution": f"{encoded['width']}x{encoded['height']}",
                   "frames": encoded["frames"], "fps": meta["fps"],
                   "duration_seconds": encoded["frames"] / meta["fps"] if meta["fps"] else None,
                   "bytes": cover.stat().st_size, "qp": QP}


def _embed(native: Path, cover: Path, stego: Path, key: bytes, payload: bytes) -> dict[str, Any]:
    stego.unlink(missing_ok=True)
    record = _run_measured([str(native), "embed-stream-auth-stdin", str(cover), str(stego), str(PER_IDR_MAX_BITS)],
                           key.hex().encode("ascii") + b"\n" + payload.hex().encode("ascii") + b"\n")
    if record["returncode"]:
        raise RuntimeError(f"embed failed: {record['stderr'].decode(errors='replace')[-300:]}")
    return record


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None, "min": None, "max": None, "stdev": None}
    return {"mean": statistics.fmean(values), "median": statistics.median(values), "min": min(values),
            "max": max(values), "stdev": statistics.stdev(values) if len(values) > 1 else 0.0}


# ------------------------------------------------------------------- trials

def _trial(index: int, native: Path, inspect: Path, ctx: CameraContext, cover: Path,
           work: Path, cover_segments: dict[str, Any]) -> dict[str, Any]:
    key = os.urandom(32)
    message = f"{MESSAGE.decode('utf-8')} #{index + 1}".encode("utf-8")
    zk = make_zk_payload(ctx, message, cover, key)
    stego = work / f"trial_{index + 1}.h264"
    embed = _embed(native, cover, stego, key, zk["payload"])
    started = time.perf_counter()
    decoded = _strict_decode_ok(stego)
    strict_ms = (time.perf_counter() - started) * 1000.0
    code, payload_hex, stderr, extract_ms = extract_payload(native, stego, key)
    extracted = code == 0 and payload_hex.decode("ascii", errors="ignore") == zk["payload"].hex()
    verification = (verify_zk_payload(ctx, payload_hex, stego, key) if extracted
                    else {"verified": False, "verify_ms": None, "message": None, "video_bound": False})
    signs = sign_statistics(cover_segments, inspect_segments(inspect, stego), key, zk["frame_bits"])
    stages = {"video_digest_ms": zk["digest_ms"], "prove_ms": zk["prove_ms"], "embed_ms": embed["wall_ms"],
              "strict_decode_ms": strict_ms, "extract_ms": extract_ms, "groth16_verify_ms": verification["verify_ms"]}
    return {
        "trial": index + 1, "message_bytes": len(message), "payload_bytes": len(zk["payload"]),
        "frame_bits": zk["frame_bits"], "stages": stages,
        "sender_total_ms": zk["digest_ms"] + zk["prove_ms"] + embed["wall_ms"],
        "receiver_total_ms": extract_ms + (verification["verify_ms"] or 0.0),
        "embed_peak_rss_mb": embed["peak_rss_bytes_sampled"] / 1e6,
        "embed_cpu_seconds": embed["cpu_seconds_sampled"],
        "stego_bytes": stego.stat().st_size, "strict_decode_ok": decoded,
        "extracted": extracted, "video_bound": bool(verification["video_bound"]),
        "groth16_verified": bool(verification["verified"] and verification["message"] == message),
        "sign_statistics": signs,
        "passed": bool(decoded and extracted and verification["verified"] and verification["video_bound"]
                       and signs["changed_outside_schedule"] == 0),
        "error": None if extracted else stderr[-300:],
    }


# ------------------------------------------------------------- attack matrix

def _attack(name: str, description: str, expected: str, stream: Path | None,
            decision: dict[str, Any], decodable: bool | None) -> dict[str, Any]:
    return {"case": name, "description": description, "expected": expected,
            "outcome": decision["outcome"], "reason": decision["reason"], "detail": decision["detail"],
            "strict_decode_ok": decodable, "as_expected": decision["outcome"] == expected,
            "stream_bytes": stream.stat().st_size if stream and stream.exists() else None}


def run_attack_matrix(native: Path, inspect: Path, ctx: CameraContext, cover: Path, work: Path) -> list[dict[str, Any]]:
    key, other_key = os.urandom(32), os.urandom(32)
    zk = make_zk_payload(ctx, MESSAGE, cover, key)
    stego = work / "attack_base.h264"
    _embed(native, cover, stego, key, zk["payload"])
    data = stego.read_bytes()
    segments = inspect_segments(inspect, stego)
    placements = segment_schedule(segments, key, zk["frame_bits"], PER_IDR_MAX_BITS)
    scheduled = {(p.candidate.nal_index, p.candidate.rbsp_bit_offset) for p in placements}
    nals = _nal_table(inspect, stego)
    rows: list[dict[str, Any]] = []

    def case(name: str, description: str, expected: str, path: Path, *, known_limitation: bool = False) -> None:
        rows.append(_attack(name, description, expected, path,
                            verify_decision(native, ctx, path, key), _strict_decode_ok(path)))
        if known_limitation:
            rows[-1]["known_limitation"] = True

    def flipped_copy(name: str, item: dict[str, Any]) -> Path:
        path = work / f"attack_{name}.h264"
        path.write_bytes(flip_sign_bit(data, nals, item["nal_index"], item["rbsp_bit_offset"]))
        if _sign_at(inspect, path, item["nal_index"], item["rbsp_bit_offset"]) == item["bit"]:
            raise RuntimeError(f"{name}: the sign flip did not land on its candidate")
        return path

    case("baseline", "Stego gốc, đúng khóa, đúng sổ đăng ký", "accepted", stego)

    decision = verify_decision(native, ctx, stego, other_key)
    rows.append(_attack("wrong_key", "Stego gốc, khóa giấu tin sai", "rejected", stego, decision, True))

    target = placements[len(placements) // 2].candidate
    case("flip_scheduled_sign", "Lật 1 bit dấu nằm trong lịch nhúng (giữa khung)", "rejected",
         flipped_copy("flip_scheduled", {"nal_index": target.nal_index, "rbsp_bit_offset": target.rbsp_bit_offset,
                                         "bit": target.bit}))

    carrier_nals = {p.candidate.nal_index for p in placements}
    inside = next(item for segment in segments["segments"] for item in segment["candidates"]
                  if item["nal_index"] in carrier_nals and (item["nal_index"], item["rbsp_bit_offset"]) not in scheduled)
    case("flip_unscheduled_carrier_sign", "Lật 1 bit dấu ứng viên ngoài lịch, ngay trong IDR mang khung",
         "rejected", flipped_copy("flip_unscheduled", inside))

    later = segments["segments"][-1]["candidates"][0]
    case("flip_later_frame_sign", "Lật 1 bit dấu ở IDR cuối (ngoài vùng nhúng)", "rejected",
         flipped_copy("flip_later_frame", later))

    first_idr = min(p.candidate.nal_index for p in placements)
    idr = nals[first_idr]
    end_offset = idr["offset"] + idr["start_code_bytes"] + 1 + idr["ebsp_bytes"]
    dropped = work / "attack_drop_first_idr.h264"
    dropped.write_bytes(data[:idr["offset"]] + data[end_offset:])
    case("drop_first_idr", "Xóa IDR mang bit đầu tiên của khung", "rejected", dropped)

    truncated = work / "attack_truncate_half.h264"
    truncated.write_bytes(data[: len(data) // 2])
    case("truncate_half", "Cắt còn 50% đầu stream (payload vẫn nguyên)", "rejected", truncated)

    transcoded = work / "attack_transcode.h264"
    meta = _probe(stego)
    result = _run([_tool("ffmpeg"), "-v", "error", "-y", "-i", str(stego), "-c:v", "libx264", "-preset", "ultrafast",
                   "-profile:v", "baseline", "-qp", str(QP), "-g", "1", "-bf", "0", "-threads", "1",
                   "-x264-params", "keyint=1:min-keyint=1:scenecut=0:repeat-headers=1:slices=1:threads=1",
                   "-pix_fmt", "yuv420p", "-frames:v", str(meta["frames"]), "-f", "h264", str(transcoded)])
    if result.returncode:
        raise RuntimeError(f"transcode failed: {result.stderr.decode(errors='replace')[-300:]}")
    case("transcode", "Giải mã rồi mã hóa lại (libx264, cùng QP 22)", "rejected", transcoded)

    swapped = work / "attack_message_swap.h264"
    other_message = "attacker-chosen message, proof reused".encode("utf-8")
    _embed(native, cover, swapped, key, pack_payload(MODE_VIDEO, other_message, zk["payload"][-PROOF_SIZE_BYTES:]))
    case("message_swap", "Người có khóa giấu tin thay message, giữ proof cũ", "rejected", swapped)

    outsider = camera_context(native)  # its own registry: not the root the verifier trusts
    foreign = work / "attack_unregistered_camera.h264"
    _embed(native, cover, foreign, key, make_zk_payload(outsider, MESSAGE, cover, key)["payload"])
    case("unregistered_camera", "Camera ngoài sổ đăng ký tin cậy tự tạo proof hợp lệ với cây của nó", "rejected", foreign)

    if REPLAY_SOURCE.is_file():
        other_cover, _meta = _cover(work, REPLAY_SOURCE)
        replayed = work / "attack_replay_other_video.h264"
        _embed(native, other_cover, replayed, key, zk["payload"])
        case("replay_other_video", f"Chép payload sang video khác ({REPLAY_SOURCE.name}) cùng khóa", "rejected", replayed)
    return rows


# --------------------------------------------------------------------- main

def run_e2e_benchmark(output_root: Path = RESULTS, trials: int = 5) -> dict[str, Any]:
    native, inspect = _native_binary(), _inspect_binary()
    ctx = camera_context(native)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
    work = Path(tempfile.mkdtemp(prefix="zkstego_e2e_"))
    try:
        cover, cover_meta = _cover(work)
        cover_segments = inspect_segments(inspect, cover)
        trial_rows = [_trial(index, native, inspect, ctx, cover, work, cover_segments) for index in range(trials)]
        for row in trial_rows:
            print(f"[{'passed' if row['passed'] else 'failed'}] e2e trial {row['trial']}: "
                  f"prove {row['stages']['prove_ms']:.0f} ms, embed {row['stages']['embed_ms']:.0f} ms, "
                  f"extract {row['stages']['extract_ms']:.0f} ms", flush=True)
        attacks = run_attack_matrix(native, inspect, ctx, cover, work)
        for row in attacks:
            print(f"[{'ok' if row['as_expected'] else 'UNEXPECTED'}] attack {row['case']}: {row['outcome']} ({row['reason']})",
                  flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    stage_names = ("video_digest_ms", "prove_ms", "embed_ms", "strict_decode_ms", "extract_ms", "groth16_verify_ms")
    record = {
        "schema": "zkstego-e2e-benchmark-new-v1", "run_id": run_id,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "environment": collect_environment(),
        "cover": cover_meta,
        "protocol": {"version": FRAME_VERSION, "max_bits_per_idr": PER_IDR_MAX_BITS,
                     "candidate_signs": cover_segments["raw_candidate_signs"],
                     "idr_segments": cover_segments["idr_segments"],
                     "capacity_bits_at_cap": cover_segments["candidate_capacity_bits"],
                     "capacity_payload_bytes_at_cap": max(0, cover_segments["candidate_capacity_bits"] // 8 - FRAME_OVERHEAD),
                     "max_message_bytes_at_cap": max(0, cover_segments["candidate_capacity_bits"] // 8 - FRAME_OVERHEAD
                                                     - PAYLOAD_HEADER_BYTES - PROOF_SIZE_BYTES),
                     "frame_overhead_bytes": FRAME_OVERHEAD,
                     "payload_layout": "[0x01][mode][len 2B][message][Groth16 proof 129B] inside [0x03][len 2B][payload] (no MAC)",
                     "registry_cameras": len(ctx.registry.public_keys)},
        "trials": trial_rows,
        "stage_summary_ms": {name: _stats([row["stages"][name] for row in trial_rows if row["stages"][name] is not None])
                             for name in stage_names},
        "sender_total_ms": _stats([row["sender_total_ms"] for row in trial_rows]),
        "receiver_total_ms": _stats([row["receiver_total_ms"] for row in trial_rows]),
        "attacks": attacks,
        "summary": {"trials": len(trial_rows), "trials_passed": sum(row["passed"] for row in trial_rows),
                    "attacks": len(attacks), "attacks_as_expected": sum(row["as_expected"] for row in attacks),
                    "all_passed": all(row["passed"] for row in trial_rows) and all(row["as_expected"] for row in attacks)},
        "methodology": ("Wall times of real calls on this host. Sender: native video digest of the cover, Groth16 prove "
                        "(Node.js start-up included), native embed. Receiver: native extract, then the verify decision "
                        "(native digest of the stego + Groth16 verify against the trusted registry root). Attack outcomes use "
                        "the HTTP verify-job decision (payload_not_found / malformed_proof_payload / proof_invalid / accepted). "
                        "Stream edits keep the file otherwise byte-identical; every sign flip is checked to land on its "
                        "candidate before it is evaluated."),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "e2e_new.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return record


if __name__ == "__main__":
    summary = run_e2e_benchmark()["summary"]
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if summary["all_passed"] else 2)
