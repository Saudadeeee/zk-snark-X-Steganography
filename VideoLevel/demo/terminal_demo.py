#!/usr/bin/env python3
"""One terminal walkthrough of the real native CAVLC segment protocol + camera Groth16 proof.

Run from any directory: python demo/terminal_demo.py --help
Only ephemeral educational secrets are generated; no production key is loaded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import secrets
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.native_blind_contract import (
    FRAME_HEADER_BYTES,
    FRAME_VERSION,
    HKDF_SALT,
    SCHEDULE_INFO,
    WHITENING_INFO,
    NativeCavlcCandidate,
    bits_to_bytes,
    bytes_to_bits,
    derive_channel_keys,
    pack_frame,
    score_candidate,
    segment_schedule,
    unpack_frame,
    unwhiten_bits,
    whitening_keystream_bits,
)
from src.camera_proof import frame_bits_for_message, verify_payload
from src.camera_registry import CameraRegistry, camera_public_key, new_camera_secret
from src.video_binding import MODE_VIDEO, binding_digest, binding_public_inputs, native_video_digest
from src.zk_setup import PTAU_BLAKE2B
from src.zk_proof import (
    PAYLOAD_HEADER_BYTES,
    PROOF_SIZE_BYTES,
    CameraProofBridge,
    bytes_to_proof,
    pack_payload,
    proof_to_bytes,
    unpack_payload,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import camera_trace  # noqa: E402  (demo-local: Merkle opening + video digest, step by step)
import deep_trace  # noqa: E402  (demo-local: FFmpeg internals + one-block anatomy)
from native_io import (  # noqa: E402  (demo-local: native tool calls)
    MAX_PAYLOAD_BYTES,
    Tools,
    find_tools,
    inspect_segments,
    native_embed,
    native_extract,
    trace_video,
)
import negative_cases  # noqa: E402  (demo-local: rejection cases)
from segment_plan import (  # noqa: E402  (demo-local: segment schedule helpers)
    DEFAULT_MAX_BITS_PER_IDR,
    EmbedPlan,
    file_candidate,
    resolve_max_bits,
    segment_capacity,
    show_allocation,
)
import service_steps  # noqa: E402  (demo-local: native HTTP jobs + WebSocket stream)

CATEGORIES = ("LumaDC", "Luma4x4", "ChromaDC", "ChromaAC")
ZIGZAG = (0, 1, 4, 8, 5, 2, 3, 6, 9, 12, 13, 10, 7, 11, 14, 15)
NAL_NAMES = {1: "P/non-IDR", 5: "IDR", 6: "SEI", 7: "SPS", 8: "PPS", 9: "AUD"}
# Pinned phase-2 artifact/digest: https://github.com/iden3/snarkjs#7-prepare-phase-2
PTAU_URL = "https://circom.info/powersOfTau28_hez_final_16.ptau"


def prepared_ptau(session: Session, build: Path) -> Path:
    path = build / "powersOfTau28_hez_final_16.ptau"
    if not path.is_file():
        session.say("Tai prepared Powers of Tau power 16 (~75 MB), kiem BLAKE2b theo snarkjs README...")
        temporary = build / ("ptau_download_" + secrets.token_hex(6) + ".part")
        try:
            with urllib.request.urlopen(PTAU_URL, timeout=60) as response, temporary.open("xb") as output:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > 100 * 1024 * 1024:
                        raise RuntimeError("PTAU download vuot gioi han 100 MiB")
                    output.write(chunk)
            with temporary.open("rb") as stream:
                digest = hashlib.file_digest(stream, "blake2b").hexdigest()
            if digest != PTAU_BLAKE2B:
                raise RuntimeError("PTAU BLAKE2b mismatch; khong su dung artifact nay")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "blake2b").hexdigest() != PTAU_BLAKE2B:
            raise RuntimeError(f"PTAU cache khong dung hash: {path}")
    session.report["ptau_blake2b"] = PTAU_BLAKE2B
    session.say("Prepared PTAU hash: PASS. Groth16 phase 2 key contribution van tao cuc bo cho demo.")
    return path


def shell_display(args: list[str]) -> str:
    """For display only; commands are always executed as argument lists."""
    return subprocess.list2cmdline(args)


class Session:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        name = datetime.now().astimezone().strftime("terminal_%Y%m%d_%H%M%S_") + secrets.token_hex(3)
        self.folder = ROOT / "demo/runs" / name
        self.folder.mkdir(parents=True)
        self.transcript = (self.folder / "transcript.txt").open("w", encoding="utf-8")
        self.report: dict = {"status": "running", "timings_seconds": {}, "checks": {}}
        self.step_number = 0
        self.raw_input: Path | None = None  # encoder_input.yuv when the deep trace is enabled

    def say(self, text: object = "", *, private: bool = False) -> None:
        print(text, flush=True)
        self.transcript.write("[private demo value omitted]\n" if private else str(text) + "\n")
        self.transcript.flush()

    def stage(self, title: str) -> None:
        if self.step_number and not self.args.auto:
            input("\nNhan Enter de sang buoc tiep theo (Ctrl+C de dung)... ")
        self.step_number += 1
        self.say(f"\n{'=' * 78}\n{self.step_number:02d}. {title}\n{'=' * 78}")

    def save(self, name: str, value: object) -> None:
        (self.folder / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    def check(self, name: str, passed: bool) -> None:
        self.report["checks"][name] = bool(passed)
        self.say(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        if not passed:
            raise RuntimeError(f"Demo audit failed: {name}")

    def run(self, label: str, args: list[str | Path], *, data: bytes | None = None,
            cwd: Path = ROOT, allow_failure: bool = False, timeout: int = 1800) -> subprocess.CompletedProcess:
        command = [str(a) for a in args]
        start = time.perf_counter()
        result = subprocess.run(command, cwd=cwd, input=data, capture_output=True, timeout=timeout, check=False)
        self.report["timings_seconds"][label] = time.perf_counter() - start
        (self.folder / f"{label}.stdout").write_bytes(result.stdout)
        (self.folder / f"{label}.stderr").write_bytes(result.stderr)
        if result.returncode and not allow_failure:
            error = (result.stderr + result.stdout).decode("utf-8", errors="replace")[-2500:]
            raise RuntimeError(f"{label} exit={result.returncode}:\n{error}")
        return result

    def finish(self) -> None:
        self.save("report.json", self.report)
        self.say(f"\nArtifacts + transcript + report: {self.folder}")
        self.transcript.close()


class MeasuredBridge(CameraProofBridge):
    """Same bridge, with timings around its existing witness/prover operations."""
    def __init__(self, session: Session) -> None:
        super().__init__(ROOT / "circuits")
        self.session = session

    def _compute_witness(self, circuit_input: dict) -> Path:
        start = time.perf_counter()
        witness = super()._compute_witness(circuit_input)
        self.session.report["timings_seconds"]["witness"] = time.perf_counter() - start
        self.session.report["witness_bytes"] = witness.stat().st_size
        self.session.say(f"Witness thuc: {witness.stat().st_size:,} bytes; duoc xoa sau prove.")
        return witness

    def _snarkjs_prove(self, witness_path: Path) -> tuple[dict, dict]:
        start = time.perf_counter()
        result = super()._snarkjs_prove(witness_path)
        self.session.report["timings_seconds"]["groth16_prove"] = time.perf_counter() - start
        return result


def setup(session: Session) -> None:
    """Build missing local dependencies. Never replace existing proving keys."""
    session.stage("SETUP cuc bo (chi can lan dau)")
    for tool in ("cmake", "node", "circom", "ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RuntimeError(f"Can cai {tool} va them vao PATH truoc --setup.")
    session.say("Build C++ Release va cai dependencies theo circuits/package-lock.json...")
    # Do not force BUILD_TESTING here: that would overwrite an existing native/build cache
    # that has the CTest suite enabled. Only the demo targets below are built.
    session.run("cmake_configure", ["cmake", "-S", "native", "-B", "native/build"])
    session.run("cmake_build", ["cmake", "--build", "native/build", "--config", "Release",
                                "--target", "zkstego_blind_bits", "zkstego_inspect"])
    circuits = ROOT / "circuits"
    cli = circuits / "node_modules/snarkjs/build/cli.cjs"
    if not cli.is_file():
        session.run("npm_ci", ["npm.cmd" if os.name == "nt" else "npm", "ci", "--no-audit", "--no-fund"], cwd=circuits)
    build = circuits / "build"
    build.mkdir(exist_ok=True)
    bridge = CameraProofBridge(circuits)
    if bridge.zkey_path.is_file() and bridge.vkey_path.is_file():
        session.say("Da co proving/verification key cua camera_video: giu nguyen.")
        return
    prepared_ptau(session, build)
    session.say("Groth16 setup cho camera_video.circom (src/zk_setup.py): Phase 1 = PTAU Hermez cong khai,")
    session.say("Phase 2 = 2 dong gop (entropy qua stdin) + beacon cong khai, roi 'snarkjs zkey verify'.")
    session.say("Ca hai dong gop chay tren MOT may: day la nghi thuc DEMO, khong phai production.")
    session.run("zk_setup", [sys.executable, "-m", "src.zk_setup"], timeout=3600)


def preflight(session: Session) -> tuple[Tools, MeasuredBridge]:
    for tool in ("ffmpeg", "ffprobe", "node", "npx"):
        if not shutil.which(tool):
            raise RuntimeError(f"Thieu {tool} trong PATH.")
    tools = find_tools()
    bridge = MeasuredBridge(session)
    required = [*bridge.required_files(), bridge.js_dir / "witness_calculator.js"]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.is_file()]
    if missing:
        raise RuntimeError("Thieu artifacts: " + ", ".join(missing) + ". Chay --setup.")
    session.say("Native C++ (zkstego_blind_bits + zkstego_inspect) + FFmpeg + Circom witness + snarkjs: san sang.")
    session.say("Giao thuc kenh: SEGMENT protocol v3. Moi IDR = 1 segment (SPS/PPS + IDR do),")
    session.say("mang toi da --max-bits-per-idr bit cua khung; segment sau tiep tuc tu bit ke tiep.")
    session.say("Cung giao thuc voi dich vu HTTP/WebSocket native (embed-stream-auth / embed-live-auth).")
    session.say("Gioi han core: Baseline, CAVLC, progressive, 4:2:0; chi nhung IDR.")
    if session.args.no_service:
        session.say("--no-service: bo qua buoc HTTP jobs va WebSocket stream.")
    session.report["scope"] = ("native keyed segment protocol v3 + camera Groth16 proof: registry membership "
                               "and binding to the video digest (carrier bits cleared) and the message")
    for label, command in (("ffmpeg_version", ["ffmpeg", "-version"]), ("node_version", ["node", "--version"]),
                           ("git_commit", ["git", "rev-parse", "HEAD"])):
        try:
            result = session.run(label, command, allow_failure=True)
        except OSError:  # e.g. git not installed: version metadata is optional
            session.report[label] = ["unavailable"]
            continue
        session.report[label] = result.stdout.decode("utf-8", errors="replace").splitlines()[:1]
    session.report["verification_key_sha256"] = hashlib.sha256(bridge.vkey_path.read_bytes()).hexdigest()
    session.report["circuit_sha256"] = hashlib.sha256((ROOT / "circuits/camera_video.circom").read_bytes()).hexdigest()
    return tools, bridge


def choose_input(session: Session) -> Path:
    if session.args.input:
        source = Path(session.args.input).expanduser().resolve()
    else:
        options = sorted((ROOT / "data/raw").glob("*.y4m"))
        options += sorted((ROOT / "data").glob("**/*.h264"))[:20]
        if not options:
            raise RuntimeError("Khong co video mau; truyen --input PATH.")
        for i, path in enumerate(options, 1):
            session.say(f"  {i}. {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")
        if session.args.auto:
            source = options[0]
        else:
            answer = input("Chon so hoac nhap duong dan video [1]: ").strip().strip('"')
            if not answer:
                source = options[0]
            elif answer.isdigit() and 1 <= int(answer) <= len(options):
                source = options[int(answer) - 1]
            else:
                source = Path(answer).expanduser().resolve()
    if not source.is_file():
        raise RuntimeError(f"Khong tim thay video: {source}")
    return source


def video_prepare(session: Session) -> Path:
    session.stage("Chon video, Y4M va encode H.264")
    source = choose_input(session)
    session.say(f"Input: {source}")
    if source.suffix.lower() == ".y4m":
        with source.open("rb") as stream:
            header = stream.readline(4096).decode("ascii", errors="replace").strip()
        session.say(f"Y4M header: {header}")
        session.say("W/H = kich thuoc; F = FPS dang phan so; I = interlace; C = chroma.")
        session.say("Y4M chua pixel Y/U/V chua nen, marker FRAME phan tach tung frame.")
    probe = session.run("input_probe", ["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=codec_name,profile,width,height,pix_fmt,r_frame_rate", "-of", "json", source])
    info = json.loads(probe.stdout)["streams"][0]
    session.say(json.dumps(info, ensure_ascii=False, indent=2))
    output = session.folder / "source.h264"
    # Bounded clip and geometry keep full coefficient traces practical in a terminal.
    scale = "scale=w='min(640,iw)':h='min(480,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1"
    params = f"cabac=0:keyint={session.args.gop}:min-keyint={session.args.gop}:scenecut=0:bframes=0:slices=1:threads=1"
    # verbose: FFmpeg logs every component (demuxer, filtergraph, libx264, muxer) to encode.stderr.
    command = ["ffmpeg", "-hide_banner", "-loglevel", "verbose", "-nostdin", "-n", "-i", str(source),
               "-map", "0:v:0", "-an", "-frames:v", str(session.args.frames), "-vf", scale,
               "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-qp", str(session.args.qp),
               "-g", str(session.args.gop), "-bf", "0", "-threads", "1", "-x264-params", params, "-f", "h264", str(output)]
    session.say(f"Encode toi da {session.args.frames} frame, <=640x480, QP={session.args.qp}, GOP={session.args.gop}.")
    session.say("GOP=1: all-IDR, moi frame la 1 segment; GOP>1: co P, chi IDR la segment mang bit.")
    session.say("Moi input (ke ca H.264) deu duoc encode lai ve profile tren cho demo.")
    session.say(shell_display(command))
    encoded = session.run("encode", command)
    session.report.update(input=str(source), input_metadata=info, encoder_command=command,
                          requested_frames=session.args.frames, gop=session.args.gop, qp=session.args.qp,
                          source_h264_bytes=output.stat().st_size)
    if not session.args.brief:
        session.stage("Ben trong FFmpeg / libx264: tu frame chua nen den file H.264")
        deep_trace.ffmpeg_pipeline(session, encoded.stderr.decode("utf-8", errors="replace"))
        probe = session.run("encoded_probe", ["ffprobe", "-v", "error", "-select_streams", "v:0",
                                              "-show_entries", "stream=width,height", "-of", "json", output])
        size = json.loads(probe.stdout)["streams"][0]
        width, height = int(size["width"]), int(size["height"])
        session.raw_input = deep_trace.raw_input_view(session, source, command, width, height, ascii_frame)
        deep_trace.encode_loss(session, session.raw_input, output, width, height)
    return output


@dataclass(frozen=True)
class DemoCamera:
    """The demo's camera registry, the signing camera and what its proof was bound to."""
    registry: CameraRegistry
    secret: int
    index: int
    video_digest: bytes
    binding: bytes


def choose_message(session: Session) -> bytes:
    message = session.args.message
    if message is None:
        message = "Xin chao ZK video" if session.args.auto else input("Nhap message UTF-8: ")
    encoded = message.encode("utf-8")
    limit = 4096 - PAYLOAD_HEADER_BYTES - PROOF_SIZE_BYTES
    if not encoded or len(encoded) > limit:
        raise RuntimeError(f"Message phai co 1..{limit} UTF-8 bytes (native stdin payload <=4096 bytes).")
    session.say(f"Message = {message!r}; {len(message)} ky tu, {len(encoded)} UTF-8 bytes; hex {encoded.hex()}")
    return encoded


def make_camera_proof(session: Session, bridge: MeasuredBridge, tools: Tools, source: Path, message: bytes,
                      key: bytes, max_bits: int, segments: dict) -> tuple[bytes, dict, DemoCamera]:
    session.stage("Camera trong so dang ky + hash video + Groth16 proof")
    camera_secrets = [new_camera_secret() for _ in range(4)]
    index = 2
    registry = CameraRegistry([camera_public_key(secret) for secret in camera_secrets])
    secret = camera_secrets[index]
    session.say("So dang ky: cay Merkle Poseidon do sau 16; la = pk = Poseidon(secret) cua moi camera hop le.")
    for position, public_key in enumerate(registry.public_keys):
        session.say(f"  la {position}: pk = {camera_trace.short(public_key)}{'   <- camera nay' if position == index else ''}")
    session.say(f"  ROOT (cong khai, verifier tin) = {hex(registry.root)}")
    session.say(f"  secret camera (PRIVATE) = {hex(secret)}", private=True)
    camera_trace.merkle_walk(session, registry, secret, index)
    frame_bits = frame_bits_for_message(len(message))
    session.say(f"Hash video: khung {frame_bits} bit -> {frame_bits} vi tri dau do lich keyed HMAC(schedule_key, ID) chon.")
    session.say("  RBSP moi NAL (bo EPB); CHI cac bit dau se mang khung bi dat ve 0, moi bit khac deu nam trong hash;")
    session.say("  digest = SHA256('zkstego/video-digest/v1' || frame_bits || cap || [len || header || rbsp'] moi NAL).")
    started = time.perf_counter()
    digest = native_video_digest(tools.native, source, key, frame_bits, max_bits)
    session.report["timings_seconds"]["video_digest_cover"] = time.perf_counter() - started
    binding = binding_digest(MODE_VIDEO, digest, message)
    high, low = binding_public_inputs(binding)
    session.say(f"  video digest (cover, native) = {digest.hex()}")
    if not session.args.brief:
        camera_trace.digest_breakdown(session, source, segments, key, frame_bits, max_bits, digest)
    session.say("binding = SHA256('zkstego/proof-binding/v1' || 0x00 || digest || SHA256(message))")
    session.say(f"  = {binding.hex()} -> bindingHi = {hex(high)}, bindingLo = {hex(low)}")
    session.say("Circuit camera_video: PRIVATE secret + duong Merkle; PUBLIC [root, bindingHi, bindingLo] (3 so).")
    session.say("Rang buoc: Poseidon(secret) mo duong Merkle toi root; bindingHi/Lo nam trong proof.")
    session.say("Dang tinh witness va proof that...")
    proof = bridge.prove(secret, registry, binding)
    proof_bytes = proof_to_bytes(proof)
    session.check("compressed proof = 129 bytes", len(proof_bytes) == PROOF_SIZE_BYTES)
    session.say("Proof JSON (A thuoc G1, B thuoc G2, C thuoc G1, BN254):")
    session.say(json.dumps(proof, indent=2))
    session.say("Compressed: [A.x 32B][B.x.c0 32B][B.x.c1 32B][C.x 32B][3 sign flags 1B]")
    for name, start, end in (("A.x", 0, 32), ("B.x.c0", 32, 64), ("B.x.c1", 64, 96), ("C.x", 96, 128), ("flags", 128, 129)):
        session.say(f"  {name:8} [{start:3}:{end:3}] {proof_bytes[start:end].hex()}")
    session.say(f"flags byte: {proof_bytes[-1]:08b}; chi 3 bit thap duoc dung cho dau y.")
    session.say("Verifier chi can root + verification key (+ stego key de trich); KHONG can secret camera,")
    session.say("va khong biet la nao (camera nao) da tao proof.")
    session.save("proof.json", proof)
    session.save("public_signals.json", CameraProofBridge.public_signals(registry.root, binding))
    (session.folder / "proof.bin").write_bytes(proof_bytes)
    registry.save(session.folder / "camera_registry.json")
    session.report.update(message_utf8_bytes=len(message), message_sha256=hashlib.sha256(message).hexdigest(),
                          registry_root=hex(registry.root), registry_cameras=len(registry.public_keys),
                          video_digest=digest.hex(), binding=binding.hex(), proof_bytes=len(proof_bytes),
                          public_signals=3)
    return proof_bytes, proof, DemoCamera(registry, secret, index, digest, binding)


def indexed(trace: dict) -> dict[NativeCavlcCandidate, dict]:
    return {NativeCavlcCandidate(*row["id"]): row for row in trace["candidates"]}


def show_video_trace(session: Session, trace: dict) -> None:
    session.say("Annex-B: start code 00 00 01 / 00 00 00 01 -> NAL header -> EBSP.")
    session.say("Bo emulation-prevention byte 03 de co RBSP; bit offsets ben duoi tinh tren RBSP.")
    session.say("NAL   byte offset  type        ref  EBSP bytes  RBSP bytes")
    for row in trace["nals"][:session.args.rows]:
        session.say(f"{row['index']:3} {row['offset']:12}  {NAL_NAMES.get(row['type'], str(row['type'])):10}"
                    f" {row['ref_idc']:3} {row['ebsp_bytes']:11} {row['rbsp_bytes']:11}")
    session.say(f"Tong {len(trace['nals'])} NAL; {len(trace['slices'])} IDR slice. Bang day du: trace_before.json")
    counts = Counter(row["id"][0] for row in trace["candidates"])
    for row in trace["slices"]:
        session.say(f"IDR NAL={row['nal_index']} profile={row['profile_idc']} level={row['level_idc']} "
                    f"MB={row['mb_width']}x{row['mb_height']} QP ban dau={row['initial_qp']} "
                    f"data bit={row['data_bit_offset']} candidates={counts[row['nal_index']]}")
    session.say("Moi MB: 16x16 luma + 2 plane chroma 8x8; residual gom LumaDC/Luma4x4/ChromaDC/ChromaAC.")
    session.say("Trailing-one = he so +/-1 o cuoi scan, toi da 3/block. Native lay sign DAU TIEN moi block.")
    session.say("Bit 0 -> +1, bit 1 -> -1. Doi dau giu TotalCoeff, runs va do dai ma CAVLC.")
    session.say("'An toan' o day la giu cu phap codec; pixel co the thay doi sau decode.")


def choose_cap(session: Session, tools: Tools, source: Path, trace: dict, message: bytes) -> tuple[int, dict]:
    session.stage("Capacity theo segment: chon so bit moi IDR cho khung cua payload")
    frame_bit_count = frame_bits_for_message(len(message))
    probe_cap = session.args.max_bits_per_idr or DEFAULT_MAX_BITS_PER_IDR
    segments = inspect_segments(session, tools.inspect, source, probe_cap, "segments_before")
    by_nal = Counter(row["id"][0] for row in trace["candidates"])
    file_ids = set(indexed(trace))
    session.check("candidate moi segment = candidate cua IDR do trong trace toan file",
                  all(row["candidate_count"] == by_nal[row["idr_nal_index"]] for row in segments["segments"])
                  and all(NativeCavlcCandidate(c["nal_index"], *map(int, c["id"].split(":")[1:4]), c["rbsp_bit_offset"])
                          in file_ids for row in segments["segments"] for c in row["candidates"]))
    max_bits = resolve_max_bits(session, segments, frame_bit_count)
    if max_bits != probe_cap:
        segments = inspect_segments(session, tools.inspect, source, max_bits, "segments_before")
    session.say(f"Khung = 3B + payload [format 1B][mode 1B][len 2B][message {len(message)}B][proof 129B] "
                f"= {frame_bit_count} bit; cap = {max_bits} bit/IDR.")
    return max_bits, segments


def pack_and_select(session: Session, source: Path, message: bytes, key: bytes, proof: bytes,
                    max_bits: int, segments: dict) -> tuple[bytes, EmbedPlan]:
    session.stage("Payload layout va lich nhung theo segment")
    payload = pack_payload(MODE_VIDEO, message, proof)
    session.say("Kenh CAVLC protocol v3: stego key 32B KHONG dung truc tiep lam khoa HMAC; HKDF-SHA256 (RFC 5869) tach 2 khoa:")
    session.say(f"  PRK           = HMAC-SHA256(key = {HKDF_SALT!r}, msg = secret)   (HKDF-Extract)")
    for name, info in (("schedule_key ", SCHEDULE_INFO), ("whitening_key", WHITENING_INFO)):
        session.say(f"  {name} = HKDF-Expand(PRK, info = {info!r}, L = 32)")
    subkeys = derive_channel_keys(key)
    session.say(f"  schedule_key  = {subkeys.schedule_key.hex()}", private=True)
    session.say(f"  whitening_key = {subkeys.whitening_key.hex()}", private=True)
    session.say("Subkey chi hien tren terminal nhu secret; transcript/report khong ghi gia tri.")
    frame = pack_frame(payload)
    frame_bits = bytes_to_bits(frame)
    keystream = whitening_keystream_bits(key, len(frame_bits))
    bits = [frame_bit ^ key_bit for frame_bit, key_bit in zip(frame_bits, keystream)]  # bits that go into the file
    embedded_frame = bits_to_bytes(bits)
    session.say(f"Payload: [format 0x01][mode 0 = video][message_len BE16][message = {len(message)}B][proof = 129B]"
                f" = {len(payload)}B")
    session.say(f"Native frame v3: [version = 0x{FRAME_VERSION:02x} 1B][payload_len BE16 = 2B][payload = {len(payload)}B]"
                " (khong MAC: proof Groth16 trong payload moi la thu xac thuc)")
    session.say("Whitening: keystream = HMAC-SHA256(whitening_key, uint64_be(j)), j = 0,1,2,...; noi lien, MSB-first.")
    session.say("Bit nhung i = frame bit i XOR keystream bit i (i dem TOAN CUC qua moi segment).")
    session.say(f"Header plaintext = {frame[:3].hex()} -> header nhung (sau XOR) = {embedded_frame[:3].hex()}")
    session.say("Header/proof co cau truc nhung bit ghi vao sign da bi keystream lam ngau nhien; sai key -> version ngau nhien.")
    capacity = segment_capacity(segments, max_bits)
    session.say(f"zkstego_inspect --segments {max_bits}: {segments['idr_segments']} IDR segment, "
                f"{segments['raw_candidate_signs']} sign candidate, capacity = sum(min({max_bits}, candidates)) = {capacity} bit.")
    session.say(f"Can {len(frame)} bytes = {len(bits)} bits; message toi da theo capacity nay: "
                f"{max(0, capacity // 8 - FRAME_HEADER_BYTES - PAYLOAD_HEADER_BYTES - PROOF_SIZE_BYTES)}B.")
    placements = segment_schedule(segments, key, len(bits), max_bits)
    show_allocation(session, segments, placements, max_bits, len(message))
    session.say("Trong MOI segment: ID = analysis_nal:mb:category:block:rbsp_bit (analysis input = SPS+PPS+IDR,")
    session.say("nen analysis_nal khac NAL index trong file); score = HMAC-SHA256(schedule_key, ID ASCII);")
    session.say(f"sort tang theo (score, ID), lay min({max_bits}, candidates) dau; chung mang cac frame bit ke tiep.")
    session.say("STT  seg  ID trong segment         file NAL:bit   score prefix      frame^ks=nhung  cu -> moi  flip")
    selected = [file_candidate(placement) for placement in placements]
    schedule, previous_segment = [], None
    for placement, candidate, bit in zip(placements, selected, bits):
        i, source_bit = placement.frame_bit_index, placement.candidate.bit
        row = {"frame_bit_index": i, "segment": placement.segment,
               "segment_id": placement.candidate.identity.serialize().decode(), "file_id": list(map(int, candidate.serialize().split(b":"))),
               "before": source_bit, "frame_bit": frame_bits[i], "keystream_bit": keystream[i], "target": bit,
               "flip": source_bit != bit, "score": score_candidate(placement.candidate.identity, key).hex()}
        schedule.append(row)
        # First rows in full, then the first bit of each later segment (where the next IDR takes over).
        first_of_segment = placement.segment != previous_segment
        previous_segment = placement.segment
        if i < session.args.rows or (first_of_segment and placement.segment < session.args.rows):
            if i >= session.args.rows:
                session.say(f" ... segment {placement.segment} bat dau o frame bit {i}:")
            location = f"{candidate.nal_index}:{candidate.rbsp_bit_offset}"
            session.say(f"{i:4} {placement.segment:4}  {row['segment_id']:24} {location:13} {row['score'][:16]}  "
                        f"  {frame_bits[i]}^{keystream[i]}={bit}       {source_bit} -> {bit}   {int(row['flip'])}")
    session.check("frame bits = un-whiten(bit nhung)", unwhiten_bits(bits, key) == frame_bits)
    session.save("schedule.json", schedule)
    session.report.update(max_bits_per_idr=max_bits, idr_segments=segments["idr_segments"],
                          raw_candidate_signs=segments["raw_candidate_signs"], capacity_bits=capacity,
                          segments_used=len({p.segment for p in placements}), embedded_bits=len(bits),
                          utilization=len(bits) / capacity, packed_payload_bytes=len(payload), native_frame_bytes=len(frame),
                          channel_protocol="cavlc-v3 segment protocol (HKDF + whitening, no frame MAC)",
                          expected_flips=sum(row["flip"] for row in schedule))
    return payload, EmbedPlan(max_bits, segments, placements, selected, bits, frame)


def matrix(scan: list[int]) -> list[list[int | None]]:
    if len(scan) == 4:
        return [scan[:2], scan[2:]]
    values: list[int | None] = [None] + scan if len(scan) == 15 else list(scan)
    if len(values) != 16:
        raise ValueError("Unexpected coefficient block size")
    raster: list[int | None] = [None] * 16
    for offset, value in zip(ZIGZAG, values):
        raster[offset] = value
    return [raster[i:i + 4] for i in range(0, 16, 4)]


def print_matrices(session: Session, left: list[list], right: list[list], title: str) -> None:
    session.say(title + "\n          BEFORE                         AFTER")
    for a, b in zip(left, right):
        fmt = lambda row: " ".join("   DC" if value is None else f"{value:5}" for value in row)
        session.say(fmt(a) + "     |     " + fmt(b))


def audit_embedding(session: Session, before: dict, after: dict, plan: EmbedPlan) -> NativeCavlcCandidate | None:
    selected, bits = plan.selected, plan.bits
    left, right = indexed(before), indexed(after)
    session.check("candidate identities khong doi sau nhung", left.keys() == right.keys())
    targets = dict(zip(selected, bits))
    session.check("tat ca bit trong file = frame bit XOR keystream bit", all(right[c]["bit"] == bit for c, bit in targets.items()))
    session.check("candidate ngoai schedule khong doi", all(left[c] == right[c] for c in left if c not in targets))
    metadata = ("mb_type", "total_coeff", "trailing_ones", "sign_offsets")
    session.check("TotalCoeff, TrailingOnes va offsets giu nguyen",
                  all(all(left[c][k] == right[c][k] for k in metadata) for c in left))
    changed = [c for c in selected if left[c]["bit"] != right[c]["bit"]]
    session.report["actual_flips"] = len(changed)
    session.say(f"Ghi {len(bits)} bits; thuc su lat {len(changed)}; {len(bits) - len(changed)} da dung gia tri.")
    segment_of = {row["idr_nal_index"]: row["segment"] for row in plan.segments["segments"]}
    session.say("Ban do IDR theo macroblock: . khong candidate; c co candidate; s selected; X co bit lat.")
    for slice_info in before["slices"]:
        nal, width, height = slice_info["nal_index"], slice_info["mb_width"], slice_info["mb_height"]
        cells = ["."] * (width * height)
        for c in left:
            if c.nal_index == nal:
                cells[c.macroblock_address] = "c"
        for c in selected:
            if c.nal_index == nal:
                cells[c.macroblock_address] = "s"
        for c in changed:
            if c.nal_index == nal:
                cells[c.macroblock_address] = "X"
        session.say(f"NAL {nal} (segment {segment_of.get(nal, '?')}): {width}x{height} MB")
        for y in range(height):
            session.say(f"{y:02} " + "".join(cells[y * width:(y + 1) * width]))
        # One full frame is readable; all selected identities remain in schedule.json.
        if not session.args.all_maps:
            break
    exemplar = next((c for c in changed if c.category == 1 and left[c]["mb_type"] == 0), None)
    exemplar = exemplar or next((c for c in changed if c.category == 1), None)
    if exemplar is None:
        exemplar = next(iter(changed), None)
    if exemplar:
        a, b = left[exemplar], right[exemplar]
        session.say(f"Vi du that: ID file {exemplar.serialize().decode()} {CATEGORIES[exemplar.category]}, MB type={a['mb_type']}")
        session.say(f"TotalCoeff={a['total_coeff']}, TrailingOnes={a['trailing_ones']}, sign offsets={a['sign_offsets']}")
        session.say(f"CAVLC sign {a['bit']} -> {b['bit']}; coeff scan before={a['coefficients_scan']}")
        session.say(f"coeff scan after ={b['coefficients_scan']}")
        print_matrices(session, matrix(a["coefficients_scan"]), matrix(b["coefficients_scan"]),
                       "He so residual luong tu (inverse zigzag); day CHUA phai pixel. DC = nam trong block rieng.")
        differences = [(i, x, y) for i, (x, y) in enumerate(zip(a["coefficients_scan"], b["coefficients_scan"])) if x != y]
        session.check("block vi du chi doi mot he so +/-1", len(differences) == 1 and differences[0][1] == -differences[0][2]
                      and abs(differences[0][1]) == 1)
        session.report["example_candidate"] = list(a["id"])
    return exemplar


def ascii_frame(frame: bytes, width: int, height: int, difference: bool = False) -> list[str]:
    palette = " .:-=+*#%@"
    terminal_columns = shutil.get_terminal_size((120, 30)).columns
    cols = min(48, width, max(12, (terminal_columns - 3) // 2))
    rows = max(1, round(height / width * cols / 2))
    output = []
    for y in range(rows):
        y0, y1 = y * height // rows, (y + 1) * height // rows
        line = ""
        for x in range(cols):
            x0, x1 = x * width // cols, (x + 1) * width // cols
            values = [frame[yy * width + xx] for yy in range(y0, y1) for xx in range(x0, x1)]
            value = max(values) if difference else sum(values) / len(values)
            line += (" " if value == 0 else str(min(9, math.ceil(value / 4)))) if difference else palette[min(9, int(value * 10 / 256))]
        output.append(line)
    return output


def visual_quality(session: Session, source: Path, stego: Path, trace: dict, exemplar: NativeCavlcCandidate | None) -> None:
    session.stage("FFmpeg decode: pixel/frame truoc-sau va chat luong")
    probe = session.run("output_probe", ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                        "-show_entries", "stream=width,height,nb_read_frames", "-of", "json", source])
    info = json.loads(probe.stdout)["streams"][0]
    width, height = int(info["width"]), int(info["height"])
    paths = [session.folder / "before.yuv", session.folder / "after.yuv"]
    for label, video, raw in zip(("decode_before", "decode_after"), (source, stego), paths):
        session.run(label, ["ffmpeg", "-v", "error", "-xerror", "-nostdin", "-n", "-i", video,
                           "-map", "0:v:0", "-pix_fmt", "yuv420p", "-f", "rawvideo", raw])
    a, b = paths[0].read_bytes(), paths[1].read_bytes()
    frame_size = width * height * 3 // 2
    session.check("decode du frame, cung kich thuoc", len(a) == len(b) and len(a) > 0 and len(a) % frame_size == 0
                  and len(a) // frame_size == int(info["nb_read_frames"]))
    sums, counts, changes = [0, 0, 0], [0, 0, 0], [0, 0, 0]
    plane_sizes = [width * height, width * height // 4, width * height // 4]
    for frame_start in range(0, len(a), frame_size):
        offset = frame_start
        for plane, size in enumerate(plane_sizes):
            for x, y in zip(a[offset:offset + size], b[offset:offset + size]):
                sums[plane] += (x - y) ** 2
                changes[plane] += x != y
            counts[plane] += size
            offset += size
    psnr = [None if total == 0 else 10 * math.log10(255 ** 2 * count / total) for total, count in zip(sums, counts)]
    session.say("PSNR so sanh source.h264 da encode voi stego.h264; khong phai Y4M voi stego.")
    for plane, value, count in zip("YUV", psnr, changes):
        session.say(f"  {plane}: PSNR={'infinity' if value is None else f'{value:.4f} dB'}; changed samples={count}")
    session.report.update(decoded_frames=len(a) // frame_size, decoded_width=width, decoded_height=height,
                          psnr_yuv_db=psnr, changed_yuv_samples=changes)
    # Encoder is deliberately constrained to one slice/frame and no B frames.
    vcl = [row["index"] for row in trace["nals"] if row["type"] in (1, 5)]
    session.check("one-slice/frame mapping", len(vcl) == len(a) // frame_size)
    frame_index = vcl.index(exemplar.nal_index) if exemplar else 0
    start = frame_index * frame_size
    left, right = a[start:start + width * height], b[start:start + width * height]
    delta = bytes(abs(x - y) for x, y in zip(left, right))
    session.say(f"Frame #{frame_index} (0-based), Y plane: BEFORE | AFTER (ASCII co the trong giong nhau)")
    for x, y in zip(ascii_frame(left, width, height), ascii_frame(right, width, height)):
        session.say(x + " | " + y)
    session.say("Ban do |delta Y|: space=0; digit=ceil(max delta/4), clamp 9.")
    for line in ascii_frame(delta, width, height, True):
        session.say(line)
    for name, plane in (("before", left), ("after", right), ("delta", delta)):
        (session.folder / f"frame_{frame_index}_{name}.pgm").write_bytes(f"P5\n{width} {height}\n255\n".encode() + plane)
    if exemplar and exemplar.category == 1:
        slice_info = next(row for row in trace["slices"] if row["nal_index"] == exemplar.nal_index)
        block = exemplar.block_index
        bx = (block // 4 % 2) * 8 + (block % 2) * 4
        by = (block // 8) * 8 + (block // 2 % 2) * 4
        x = exemplar.macroblock_address % slice_info["mb_width"] * 16 + bx
        y = exemplar.macroblock_address // slice_info["mb_width"] * 16 + by
        if x + 4 <= width and y + 4 <= height:
            grid = lambda data: [list(data[(y + row) * width + x:(y + row) * width + x + 4]) for row in range(4)]
            print_matrices(session, grid(left), grid(right), f"Pixel Y 4x4 tai ({x},{y}) sau decode TOAN FRAME")
    session.say("Doi he so -> inverse quant/transform -> prediction -> deblock; sai khac co the lan sang block/P frame khac.")


def verify_message(session: Session, tools: Tools, bridge: MeasuredBridge, camera: DemoCamera, stego: Path,
                   key: bytes, message: bytes, plan: EmbedPlan) -> tuple[bytes, dict]:
    session.stage("Verifier: chi nhan stego + stego key + registry root + verification key")
    session.say("Native tu parse SPS/PPS, ghep moi IDR thanh segment, tai tao lich keyed tung segment, un-whiten,")
    session.say("doc header 24 bit de biet do dai, gom du frame qua cac segment.")
    session.say("Khong can video goc, schedule.json, proof.json hay SECRET CAMERA.")
    result = native_extract(session, tools, stego, key, plan.max_bits, "native_extract")
    recovered = bytes.fromhex(result.stdout.decode().strip())
    unpacked = unpack_payload(recovered)
    started = time.perf_counter()
    stego_digest = native_video_digest(tools.native, stego, key, frame_bits_for_message(len(unpacked.message)),
                                       plan.max_bits)
    session.report["timings_seconds"]["video_digest_stego"] = time.perf_counter() - started
    session.say(f"Digest tinh lai tu STEGO = {stego_digest.hex()}")
    session.check("digest stego = digest cover (nhung chi doi cac bit carrier)", stego_digest == camera.video_digest)
    # Mandatory proof verification immediately after extraction: no message release first.
    started = time.perf_counter()
    verdict = verify_payload(bridge, camera.registry.root, recovered, native_cli=tools.native, stego=stego,
                             stego_key=key, max_bits_per_idr=plan.max_bits)
    session.report["timings_seconds"]["verify_payload"] = time.perf_counter() - started
    session.check("mandatory Groth16 proof verified against the registry root", verdict.valid)
    session.check("proof rang buoc video (mode 0)", verdict.video_bound)
    session.check("message roundtrip", verdict.message == message)
    session.say(f"VERDICT = true; message = {message.decode('utf-8')!r}; camera = mot la trong so dang ky (an danh).")
    # Independent educational audit AFTER acceptance; not an input to the actual verifier.
    stego_segments = inspect_segments(session, tools.inspect, stego, plan.max_bits, "segments_after")
    receiver = segment_schedule(stego_segments, key, len(plan.bits), plan.max_bits)
    session.check("verifier tu tai tao cung lich segment tu stego",
                  [(p.segment, p.candidate.identity, p.frame_bit_index) for p in receiver]
                  == [(p.segment, p.candidate.identity, p.frame_bit_index) for p in plan.placements])
    recovered_bits = [p.candidate.bit for p in receiver]
    recovered_frame = bits_to_bytes(unwhiten_bits(recovered_bits, key))
    session.check("readback --segments + un-whiten + Python contract khop native",
                  unpack_frame(recovered_frame, MAX_PAYLOAD_BYTES) == recovered)
    session.say("Readback bit trong file (prefix): " + "".join(map(str, recovered_bits[:64])))
    session.say("Sau XOR keystream (frame bits):   " + "".join(map(str, bytes_to_bits(recovered_frame)[:64])))
    session.say(f"Header sau un-whiten = {recovered_frame[:3].hex()} (version 0x{FRAME_VERSION:02x}, payload_len BE16)")
    return unpacked.message, bytes_to_proof(unpacked.proof_bytes)


def walkthrough(session: Session) -> None:
    if session.args.setup:
        setup(session)
    session.stage("Preflight va pham vi demo")
    tools, bridge = preflight(session)
    source = video_prepare(session)
    message = choose_message(session)
    key = secrets.token_bytes(32)  # stego key: schedule + whitening only
    session.stage("Parser native: Annex-B -> NAL -> RBSP -> slice -> macroblock -> residual")
    before = trace_video(session, tools.inspect, source, "trace_before")
    show_video_trace(session, before)
    if not session.args.brief:
        session.stage("Cat NAL, EBSP -> RBSP va header doc boi chinh thu vien FFmpeg")
        deep_trace.nal_anatomy(session, source, before)
        deep_trace.library_header_trace(session, source, before)
    max_bits, segments = choose_cap(session, tools, source, before, message)
    proof, proof_dict, camera = make_camera_proof(session, bridge, tools, source, message, key, max_bits, segments)
    payload, plan = pack_and_select(session, source, message, key, proof, max_bits, segments)
    session.stage("Nhung that bang native (embed-stream-auth-stdin) va doi chieu tung candidate")
    stego = session.folder / "stego.h264"
    native_embed(session, tools, source, stego, key, payload, plan.max_bits, "native_embed")
    after = trace_video(session, tools.inspect, stego, "trace_after")
    exemplar = audit_embedding(session, before, after, plan)
    session.report["stego_h264_bytes"] = stego.stat().st_size
    session.say(f"Bytes H.264: {source.stat().st_size:,} -> {stego.stat().st_size:,}.")
    session.say("RBSP sign patch giu do dai bit; EBSP co the doi so byte do emulation prevention.")
    visual_quality(session, source, stego, before, exemplar)
    if not session.args.brief and session.raw_input is not None:
        session.stage("Giai phau mot block nhung: bit -> CAVLC -> he so -> dequant -> bien doi nguoc -> du doan -> pixel")
        info = session.report
        deep_trace.block_anatomy(session, tools.inspect, source, stego, before, exemplar, session.raw_input,
                                 info["decoded_width"], info["decoded_height"])
        session.stage("Bit nhung nam o dau: segment -> thu hang HMAC -> chi so frame bit -> truong payload -> byte trong file")
        deep_trace.embedded_bit_location(session, source, stego, before, after, exemplar, plan.placements, plan.bits,
                                         plan.max_bits, len(message), key, info["decoded_width"],
                                         info["decoded_height"], ascii_frame)
    recovered_message, decoded_proof = verify_message(session, tools, bridge, camera, stego, key, message, plan)
    negative_cases.run_all(session, tools, bridge, camera, source, stego, after, key, recovered_message,
                           decoded_proof, plan)
    if not session.args.no_service:
        service_steps.run_all(session, tools, source, stego, key, payload, message, plan.max_bits,
                              session.folder / "camera_registry.json")
    session.stage("Tong ket lan chay")
    for name, seconds in session.report["timings_seconds"].items():
        session.say(f"  {name:28} {seconds:10.4f} s")
    session.say(f"{plan.segments['idr_segments']} IDR segment x cap {plan.max_bits} bit -> capacity "
                f"{session.report['capacity_bits']} bits; embed {len(plan.bits)} bit tren {session.report['segments_used']} "
                f"segment; flips {session.report['actual_flips']}.")
    passed = sum(session.report["checks"].values())
    session.say(f"Kiem tra: {passed}/{len(session.report['checks'])} PASS.")
    session.say("Thoi gian tren bao gom startup process; ASCII/trace la chi phi demo, khong phai throughput deployment.")
    session.say("Mot clip/mot lan chay la smoke evaluation; chua du de ket luan benchmark/paper.")
    session.say("Artifacts chua message/proof cong khai; secret da lo tren man hinh chi duoc dung cho demo nay.")
    session.report["status"] = "passed"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--input", help="video path; mac dinh chon tu data/raw")
    parser.add_argument("--message", help="message UTF-8; mac dinh nhap tu ban phim")
    parser.add_argument("--auto", action="store_true", help="khong dung cho Enter")
    parser.add_argument("--setup", action="store_true", help="build native + tao Groth16 setup camera_video (DEMO) neu thieu")
    parser.add_argument("--frames", type=int, default=8, help="so frame toi da, 1..120")
    parser.add_argument("--gop", type=int, default=1, help="khoang IDR, 1..120; >1 co P frames")
    parser.add_argument("--qp", type=int, default=22, help="QP libx264, 1..51")
    parser.add_argument("--max-bits-per-idr", type=int, default=None,
                        help=f"so bit toi da moi IDR segment, 1..100000; bo trong = {DEFAULT_MAX_BITS_PER_IDR}, "
                             "tu nang len gia tri nho nhat du capacity neu clip qua ngan")
    parser.add_argument("--rows", type=int, default=16, help="so dong preview NAL/segment/schedule, 1..256")
    parser.add_argument("--all-maps", action="store_true", help="in ban do macroblock cho moi IDR")
    parser.add_argument("--brief", action="store_true",
                        help="bo cac buoc giai thich sau (FFmpeg/x264, NAL/EPB, trace_headers, giai phau block)")
    parser.add_argument("--no-service", action="store_true",
                        help="bo qua buoc dich vu native: HTTP jobs (embed/extract/verify) va WebSocket stream")
    args = parser.parse_args()
    for name, lower, upper in (("frames", 1, 120), ("gop", 1, 120), ("qp", 1, 51), ("rows", 1, 256)):
        if not lower <= getattr(args, name) <= upper:
            parser.error(f"--{name} phai trong {lower}..{upper}")
    if args.max_bits_per_idr is not None and not 1 <= args.max_bits_per_idr <= 100000:
        parser.error("--max-bits-per-idr phai trong 1..100000")
    return args


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    session = Session(arguments())
    try:
        walkthrough(session)
        return 0
    except KeyboardInterrupt:
        session.report["status"] = "interrupted"
        session.say("\nDa dung demo.")
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, EOFError) as error:
        session.report.update(status="failed", error=str(error))
        session.say(f"\nDEMO FAILED: {error}")
        return 1
    except Exception as error:  # Programming error: still record a terminal status, keep the traceback.
        session.report.update(status="failed", error=f"{type(error).__name__}: {error}")
        session.say(f"\nDEMO FAILED (loi chuong trinh): {type(error).__name__}: {error}")
        session.say(traceback.format_exc())
        return 1
    finally:
        session.finish()


if __name__ == "__main__":
    raise SystemExit(main())
