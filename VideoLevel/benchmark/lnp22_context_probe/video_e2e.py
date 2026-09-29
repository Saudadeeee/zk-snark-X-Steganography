"""Experimental full-size LNP22 proof transport through H.264/CAVLC carriers.

This program is a research probe, not the application's accepted ZKP backend.
It proves knowledge for a pre-provisioned linear relation, binds canonical
context bytes to that proof, and exercises the existing blind payload channel.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import psutil

MODULE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = MODULE_DIR.parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.blind_payload_chunks import pack_payload_chunks
from src.blind_sync import (
    BlindOperatingContract,
)
from src.blind_sync_streaming import (
    DEFAULT_STREAM_CHUNK_BYTES,
    DEFAULT_STREAM_SEGMENT_FRAMES,
    ProgressCallback,
    derive_chunked_video_context,
    embed_chunked_video_payload,
    extract_chunked_video_payload,
)

PROBE_MAGIC = b"ZVLP"
PROBE_VERSION = 3
PROBE_HEADER = struct.Struct(">4sBIII")
PROBE_MAX_FIELD_BYTES = 16 * 1024 * 1024
PROBE_PROTOCOL = "zkstego/lnp22-video-transport-probe/v3"
STATEMENT_DOMAIN = b"zkstego/lnp22-video-transport-statement/v3/"
PAYLOAD_DOMAIN = b"zkstego/lnp22-video-transport-payload/v3/"
VIDEO_COMMITMENT_POLICY = "canonical-h264-carrier-normalized-sha256-v1"
PROBE_SECURITY_SCOPE = (
    "knowledge of the verifier-pinned short linear-relation witness, "
    "bound to this public context"
)
SYNC_KEY_ENV = "ZKSTEGOLNP22_SYNC_KEY_HEX"
DEFAULT_CONTRACT = BlindOperatingContract(
    version="stable-carriers-video-only-v1",
    require_bitstream_patchable=True,
    patchability_headroom=64,
    max_modifications_per_block=1,
    stable_carriers_only=True,
)
DEMO_PAYLOAD = b"LNP22 experimental proof transport only; not an application claim."
RSS_SAMPLE_INTERVAL_SECONDS = 0.1
_PROGRESS_EVENT_FIELDS = {
    "phase",
    "event",
    "segment_index",
    "segments_total",
    "frames_total",
    "payload_segments",
    "segments_used",
    "carriers_used",
    "error_type",
}


def _emit_progress_event(event: dict[str, str | int]) -> None:
    """Write a redacted progress record as one flushed JSONL line to stderr."""
    if not isinstance(event, dict) or set(event) - _PROGRESS_EVENT_FIELDS:
        raise ValueError("progress event contains unsupported fields")
    if not isinstance(event.get("phase"), str) or not isinstance(event.get("event"), str):
        raise TypeError("progress event requires string phase and event")
    record = dict(event)
    record["timestamp_utc"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    sys.stderr.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stderr.flush()


class ProcessTreeRSSSampler:
    """Track peak RSS for this process and all recursive child processes."""

    def __init__(
        self,
        process: Any | None = None,
        sample_interval_seconds: float = RSS_SAMPLE_INTERVAL_SECONDS,
    ) -> None:
        if not math.isfinite(sample_interval_seconds) or sample_interval_seconds <= 0:
            raise ValueError("sample_interval_seconds must be finite positive")
        self._process = process if process is not None else psutil.Process()
        self._sample_interval_seconds = sample_interval_seconds
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._peak_rss_bytes = 0
        self._rss_sampling_error_count = 0

    @property
    def peak_rss_bytes(self) -> int:
        with self._lock:
            return self._peak_rss_bytes

    @property
    def peak_rss_mb(self) -> float:
        return self.peak_rss_bytes / (1024 * 1024)

    @property
    def rss_sampling_error_count(self) -> int:
        with self._lock:
            return self._rss_sampling_error_count

    @property
    def rss_sampling_errors_observed(self) -> bool:
        return self.rss_sampling_error_count > 0

    def _record_sampling_error(self) -> None:
        with self._lock:
            self._rss_sampling_error_count += 1

    def sample_once(self) -> int:
        """Sample the current process tree once and return the summed RSS."""
        try:
            processes = [self._process, *self._process.children(recursive=True)]
        except psutil.NoSuchProcess:
            processes = [self._process]
        except psutil.Error:
            self._record_sampling_error()
            processes = [self._process]

        total_rss_bytes = 0
        seen_pids: set[int] = set()
        for process in processes:
            try:
                pid = process.pid
                if pid in seen_pids:
                    continue
                seen_pids.add(pid)
                rss_bytes = process.memory_info().rss
            except psutil.NoSuchProcess:
                continue
            except psutil.Error:
                self._record_sampling_error()
                continue
            if rss_bytes > 0:
                total_rss_bytes += rss_bytes

        with self._lock:
            self._peak_rss_bytes = max(self._peak_rss_bytes, total_rss_bytes)
        return total_rss_bytes

    def _sample_until_stopped(self) -> None:
        while not self._stop_event.wait(self._sample_interval_seconds):
            self.sample_once()

    def start(self) -> ProcessTreeRSSSampler:
        if self._thread is not None:
            raise RuntimeError("RSS sampler is already running")
        self._stop_event.clear()
        self.sample_once()
        self._thread = threading.Thread(
            target=self._sample_until_stopped,
            name="lnp22-process-tree-rss-sampler",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self) -> float:
        thread = self._thread
        if thread is not None:
            self._stop_event.set()
            thread.join()
            self._thread = None
        self.sample_once()
        return self.peak_rss_mb

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.stop()


@dataclass(frozen=True)
class VideoProbeEnvelope:
    statement_bytes: bytes
    context: dict[str, Any]
    proof_bytes: bytes
    payload_bytes: bytes


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("video proof context must be finite canonical JSON") from error


def _validate_sha256(value: str, name: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


def _payload_commitment(payload: bytes) -> str:
    return hashlib.sha256(PAYLOAD_DOMAIN + payload).hexdigest()


def make_video_probe_statement(
    *,
    session_id: bytes,
    payload: bytes,
    canonical_video_sha256: str,
    positions_hash: str,
    relation_sha256: str,
) -> bytes:
    """Return canonical context bytes, explicitly marked as unregistered."""
    if not isinstance(session_id, bytes) or len(session_id) != 32:
        raise ValueError("session_id must contain exactly 32 random bytes")
    if not isinstance(payload, bytes) or not payload:
        raise ValueError("probe payload must be non-empty bytes")
    for name, value in (
        ("canonical_video_sha256", canonical_video_sha256),
        ("positions_hash", positions_hash),
        ("relation_sha256", relation_sha256),
    ):
        _validate_sha256(value, name)

    unsigned = {
        "protocol": PROBE_PROTOCOL,
        "version": PROBE_VERSION,
        "session_id": session_id.hex(),
        "payload_commitment": _payload_commitment(payload),
        "canonical_video_sha256": canonical_video_sha256,
        "positions_hash": positions_hash,
        "relation_id": relation_sha256,
        "relation_pin_sha256": relation_sha256,
        "registry_binding": "unregistered-experimental-probe",
        "codec_policy": {
            "codec": "h264-baseline-cavlc",
            "video_commitment": VIDEO_COMMITMENT_POLICY,
            "embedding_contract": DEFAULT_CONTRACT.version,
            "max_modifications_per_block": 1,
            "proof_backend": "lnp22-experimental",
            "transport": "zkbc-v1-segmented",
            "frames_per_segment": DEFAULT_STREAM_SEGMENT_FRAMES,
            "chunk_bytes": DEFAULT_STREAM_CHUNK_BYTES,
        },
        "security_scope": PROBE_SECURITY_SCOPE,
    }
    context_id = hashlib.sha3_256(
        STATEMENT_DOMAIN + _canonical_json(unsigned)
    ).hexdigest()
    return _canonical_json({**unsigned, "statement_id": context_id})


def _parse_statement(statement_bytes: bytes) -> dict[str, Any]:
    if not isinstance(statement_bytes, bytes) or not statement_bytes:
        raise ValueError("statement context is required")
    try:
        context = json.loads(statement_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("statement context must be UTF-8 JSON") from error
    if not isinstance(context, dict) or _canonical_json(context) != statement_bytes:
        raise ValueError("statement context is not canonical JSON")
    expected_fields = {
        "protocol", "version", "session_id", "payload_commitment",
        "canonical_video_sha256", "positions_hash", "relation_id", "relation_pin_sha256",
        "registry_binding", "codec_policy", "security_scope", "statement_id",
    }
    if set(context) != expected_fields:
        raise ValueError("statement context has an invalid field set")
    if context["protocol"] != PROBE_PROTOCOL or context["version"] != PROBE_VERSION:
        raise ValueError("unsupported experimental statement version")
    if context["registry_binding"] != "unregistered-experimental-probe":
        raise ValueError("probe context must remain explicitly unregistered")
    if context["security_scope"] != PROBE_SECURITY_SCOPE:
        raise ValueError("unexpected experimental security scope")
    session_id = context["session_id"]
    if not isinstance(session_id, str) or re.fullmatch(r"[0-9a-f]{64}", session_id) is None:
        raise ValueError("statement session_id is invalid")
    for field in (
        "payload_commitment", "canonical_video_sha256", "positions_hash",
        "relation_id", "relation_pin_sha256", "statement_id",
    ):
        _validate_sha256(context[field], field)
    if context["relation_id"] != context["relation_pin_sha256"]:
        raise ValueError("relation identifier does not match the explicit relation pin")
    if context["codec_policy"] != {
        "codec": "h264-baseline-cavlc",
        "video_commitment": VIDEO_COMMITMENT_POLICY,
        "embedding_contract": DEFAULT_CONTRACT.version,
        "max_modifications_per_block": 1,
        "proof_backend": "lnp22-experimental",
        "transport": "zkbc-v1-segmented",
        "frames_per_segment": DEFAULT_STREAM_SEGMENT_FRAMES,
        "chunk_bytes": DEFAULT_STREAM_CHUNK_BYTES,
    }:
        raise ValueError("statement codec policy is unsupported")
    unsigned = {key: value for key, value in context.items() if key != "statement_id"}
    expected_id = hashlib.sha3_256(
        STATEMENT_DOMAIN + _canonical_json(unsigned)
    ).hexdigest()
    if context["statement_id"] != expected_id:
        raise ValueError("statement identifier does not match canonical context")
    return context


def encode_video_probe_payload(
    statement_bytes: bytes,
    proof_bytes: bytes,
    payload_bytes: bytes,
) -> bytes:
    """Serialize context, complete proof, and demo payload for H.264 embedding."""
    context = _parse_statement(statement_bytes)
    if len(statement_bytes) > PROBE_MAX_FIELD_BYTES:
        raise ValueError("statement exceeds the configured envelope limit")
    if not isinstance(proof_bytes, bytes) or not proof_bytes:
        raise ValueError("serialized proof must be non-empty bytes")
    if not isinstance(payload_bytes, bytes) or not payload_bytes:
        raise ValueError("payload must be non-empty bytes")
    if len(proof_bytes) > PROBE_MAX_FIELD_BYTES or len(payload_bytes) > PROBE_MAX_FIELD_BYTES:
        raise ValueError("proof or payload exceeds the configured envelope limit")
    if context["payload_commitment"] != _payload_commitment(payload_bytes):
        raise ValueError("payload does not match the statement commitment")
    header = PROBE_HEADER.pack(
        PROBE_MAGIC,
        PROBE_VERSION,
        len(statement_bytes),
        len(proof_bytes),
        len(payload_bytes),
    )
    return header + statement_bytes + proof_bytes + payload_bytes


def decode_video_probe_payload(encoded: bytes) -> VideoProbeEnvelope:
    """Parse a strict length-delimited envelope and validate all public framing."""
    if not isinstance(encoded, bytes) or len(encoded) < PROBE_HEADER.size:
        raise ValueError("video proof envelope is truncated")
    magic, version, context_size, proof_size, payload_size = PROBE_HEADER.unpack_from(encoded)
    if magic != PROBE_MAGIC or version != PROBE_VERSION:
        raise ValueError("video proof envelope magic or version is unsupported")
    if any(size == 0 or size > PROBE_MAX_FIELD_BYTES for size in (context_size, proof_size, payload_size)):
        raise ValueError("video proof envelope contains an invalid field size")
    expected_size = PROBE_HEADER.size + context_size + proof_size + payload_size
    if len(encoded) != expected_size:
        raise ValueError("video proof envelope length does not match its header")
    offset = PROBE_HEADER.size
    statement_bytes = encoded[offset : offset + context_size]
    offset += context_size
    proof_bytes = encoded[offset : offset + proof_size]
    offset += proof_size
    payload_bytes = encoded[offset:]
    context = _parse_statement(statement_bytes)
    if context["payload_commitment"] != _payload_commitment(payload_bytes):
        raise ValueError("extracted payload does not match the bound commitment")
    return VideoProbeEnvelope(statement_bytes, context, proof_bytes, payload_bytes)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sync_key_from_environment() -> bytes:
    value = os.environ.get(SYNC_KEY_ENV, "")
    if not value or re.fullmatch(r"[0-9a-fA-F]{32,}", value) is None or len(value) % 2:
        raise ValueError(f"set {SYNC_KEY_ENV} to at least 16 bytes of hex key material")
    return bytes.fromhex(value)


def _run_go(
    args: list[str],
    *,
    stdin: bytes | None = None,
    go_command: str = "go",
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    child_environment = os.environ.copy()
    for secret_name in (
        SYNC_KEY_ENV,
        "ZKSTEGOLNP22_API_TOKEN",
        "ZKSTEGOLNP22_WITNESS_PATH",
    ):
        child_environment.pop(secret_name, None)
    completed = subprocess.run(
        [go_command, "run", ".", *args],
        input=stdin,
        capture_output=True,
        cwd=MODULE_DIR,
        timeout=timeout_seconds,
        check=False,
        env=child_environment,
    )
    if completed.returncode != 0:
        error_text = completed.stderr.decode("utf-8", errors="replace")[-2000:]
        raise RuntimeError(f"LNP22 CLI failed (exit {completed.returncode}): {error_text}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("LNP22 CLI returned invalid JSON output") from error
    if not isinstance(result, dict):
        raise TypeError("LNP22 CLI output must be a JSON object")
    return result


def _verify_from_video(
    video_path: Path,
    *,
    relation_path: Path,
    trusted_relation_sha256: str,
    sync_key: bytes,
    go_command: str = "go",
    timeout_seconds: int = 1800,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    extracted = extract_chunked_video_payload(
        str(video_path),
        sync_key,
        DEFAULT_CONTRACT,
        frames_per_segment=DEFAULT_STREAM_SEGMENT_FRAMES,
        progress_callback=progress_callback,
    )
    envelope = decode_video_probe_payload(extracted.payload)
    context = envelope.context
    if context["relation_pin_sha256"] != trusted_relation_sha256:
        raise ValueError("video context relation pin differs from verifier configuration")

    if extracted.positions_hash != context["positions_hash"]:
        raise ValueError("video-derived carrier positions do not match the proof context")
    actual_canonical_video_sha256 = extracted.canonical_video_sha256
    if actual_canonical_video_sha256 != context["canonical_video_sha256"]:
        raise ValueError("carrier-normalized H.264 digest does not match proof context")

    proof_format, verify_flag = _proof_format_and_verify_flag(envelope.proof_bytes)

    with tempfile.TemporaryDirectory(prefix="lnp22-video-verify-") as temp_dir:
        proof_path = Path(temp_dir) / "proof.lnpf"
        proof_path.write_bytes(envelope.proof_bytes)
        verified = _run_go(
            [
                verify_flag,
                "-relation-in", str(relation_path),
                "-proof-in", str(proof_path),
                "-trusted-base-relation-sha256", trusted_relation_sha256,
            ],
            stdin=envelope.statement_bytes,
            go_command=go_command,
            timeout_seconds=timeout_seconds,
        )
    if verified.get("valid") is not True:
        raise ValueError("LNP22 verifier rejected the extracted proof")
    return {
        "valid": True,
        "proof_format": proof_format,
        "proof_bytes": len(envelope.proof_bytes),
        "payload_bytes": len(envelope.payload_bytes),
        "carriers_used": extracted.carriers_used,
        "statement_id": context["statement_id"],
        "canonical_video_sha256": actual_canonical_video_sha256,
        "positions_hash": extracted.positions_hash,
        "verify_ms": verified.get("verify_ms"),
        "security_status": "experimental LNP22 proof for a pre-provisioned pinned relation; not an accepted application ZKP",
    }


def _proof_format_and_verify_flag(proof_bytes: bytes) -> tuple[str, str]:
    """Select the verifier from the self-describing LNPF proof header."""
    if len(proof_bytes) < 11 or proof_bytes[:4] != b"LNPF":
        raise ValueError("unsupported embedded proof format: missing LNPF header")
    version = proof_bytes[4]
    if version == 1:
        return "LNPF-v1", "-fixed-verify"
    if version == 2:
        return "LNPF-v2", "-fixed-compact-verify"
    raise ValueError(f"unsupported embedded proof format: LNPF version {version}")


def embed_and_verify(
    video_path: Path,
    output_path: Path,
    report_output: Path,
    *,
    relation_path: Path,
    witness_path: Path,
    trusted_relation_sha256: str,
    proof_mode: str = "augmented",
    go_command: str = "go",
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    with ProcessTreeRSSSampler() as rss_sampler:
        return _embed_and_verify(
            video_path,
            output_path,
            report_output,
            relation_path=relation_path,
            witness_path=witness_path,
            trusted_relation_sha256=trusted_relation_sha256,
            proof_mode=proof_mode,
            go_command=go_command,
            timeout_seconds=timeout_seconds,
            rss_sampler=rss_sampler,
        )


def _embed_and_verify(
    video_path: Path,
    output_path: Path,
    report_output: Path,
    *,
    relation_path: Path,
    witness_path: Path,
    trusted_relation_sha256: str,
    proof_mode: str,
    go_command: str,
    timeout_seconds: int,
    rss_sampler: ProcessTreeRSSSampler,
) -> dict[str, Any]:
    """Use pre-provisioned relation material; embed and verify from video only."""
    prove_flags = {
        "augmented": "-fixed-prove",
        "compact": "-fixed-compact-prove",
    }
    if proof_mode not in prove_flags:
        raise ValueError("proof mode must be 'augmented' or 'compact'")
    prove_flag = prove_flags[proof_mode]
    source = video_path.resolve(strict=True)
    output = output_path.resolve()
    report_final = report_output.resolve()
    if not source.is_file():
        raise ValueError("input video must be a regular file")
    if source == output:
        raise ValueError("output video must differ from input video")
    if not output.parent.is_dir():
        raise FileNotFoundError("output video directory does not exist")
    if any(path.exists() or path.is_symlink() for path in (output, report_final)):
        raise FileExistsError("refusing to overwrite a video or report artifact")
    if output == report_final:
        raise ValueError("video and report output paths must be distinct")
    if not report_final.parent.is_dir():
        raise FileNotFoundError("report output directory must already exist")

    relation_input = relation_path.resolve(strict=True)
    witness_input = witness_path.resolve(strict=True)
    if not relation_input.is_file() or not witness_input.is_file():
        raise ValueError("pre-provisioned relation and private witness must be regular files")
    _validate_sha256(trusted_relation_sha256, "trusted relation digest")
    try:
        relation_artifact = json.loads(relation_input.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("could not read the pre-provisioned relation artifact") from error
    if not isinstance(relation_artifact, dict):
        raise TypeError("pre-provisioned relation artifact must be a JSON object")
    relation_pin = relation_artifact.get("relation_sha256")
    _validate_sha256(relation_pin, "relation artifact digest")
    if relation_pin != trusted_relation_sha256:
        raise ValueError("pre-provisioned relation does not match the verifier pin")

    sync_key = _sync_key_from_environment()
    session_id = os.urandom(32)
    stage_ms: dict[str, float] = {}
    started = time.perf_counter()
    _emit_progress_event({"phase": "run", "event": "started"})
    with tempfile.TemporaryDirectory(prefix="lnp22-video-e2e-", dir=output.parent) as temp_dir:
        temp = Path(temp_dir)
        provisional = make_video_probe_statement(
            session_id=session_id,
            payload=DEMO_PAYLOAD,
            canonical_video_sha256="0" * 64,
            positions_hash="0" * 64,
            relation_sha256=relation_pin,
        )
        provisional_proof = temp / "provisional.lnpf"
        phase_started = time.perf_counter()
        _emit_progress_event({"phase": "provisional_prove", "event": "started"})
        provisional_result = _run_go(
            [
                prove_flag,
                "-relation-in", str(relation_input),
                "-witness-in", str(witness_input),
                "-proof-out", str(provisional_proof),
            ],
            stdin=provisional,
            go_command=go_command,
            timeout_seconds=timeout_seconds,
        )
        stage_ms["provisional_prove"] = (time.perf_counter() - phase_started) * 1000
        provisional_bytes = provisional_proof.read_bytes()
        if len(provisional_bytes) != provisional_result.get("proof_bytes"):
            raise RuntimeError("provisional proof size disagrees with CLI result")
        _emit_progress_event({"phase": "provisional_prove", "event": "completed"})

        provisional_envelope = encode_video_probe_payload(
            provisional, provisional_bytes, DEMO_PAYLOAD
        )
        provisional_chunks = pack_payload_chunks(
            provisional_envelope,
            chunk_size=DEFAULT_STREAM_CHUNK_BYTES,
        )
        phase_started = time.perf_counter()
        _emit_progress_event({"phase": "carrier_context", "event": "started"})
        carrier_context = derive_chunked_video_context(
            source,
            provisional_chunks,
            sync_key,
            DEFAULT_CONTRACT,
            frames_per_segment=DEFAULT_STREAM_SEGMENT_FRAMES,
            progress_callback=_emit_progress_event,
        )
        stage_ms["cover_analysis_and_carrier_selection"] = (time.perf_counter() - phase_started) * 1000
        _emit_progress_event(
            {
                "phase": "carrier_context",
                "event": "completed",
                "segments_used": carrier_context.segments_used,
            }
        )
        statement = make_video_probe_statement(
            session_id=session_id,
            payload=DEMO_PAYLOAD,
            canonical_video_sha256=carrier_context.canonical_video_sha256,
            positions_hash=carrier_context.positions_hash,
            relation_sha256=relation_pin,
        )
        phase_started = time.perf_counter()
        proof_path = temp / "proof.lnpf"
        _emit_progress_event({"phase": "final_prove", "event": "started"})
        prove_result = _run_go(
            [
                prove_flag,
                "-relation-in", str(relation_input),
                "-witness-in", str(witness_input),
                "-proof-out", str(proof_path),
            ],
            stdin=statement,
            go_command=go_command,
            timeout_seconds=timeout_seconds,
        )
        stage_ms["final_prove"] = (time.perf_counter() - phase_started) * 1000
        proof_bytes = proof_path.read_bytes()
        if len(proof_bytes) != len(provisional_bytes) or len(proof_bytes) != prove_result.get("proof_bytes"):
            raise RuntimeError("final proof length changed after carrier positions were fixed")
        _emit_progress_event({"phase": "final_prove", "event": "completed"})
        payload = encode_video_probe_payload(statement, proof_bytes, DEMO_PAYLOAD)
        payload_chunks = pack_payload_chunks(
            payload,
            chunk_size=DEFAULT_STREAM_CHUNK_BYTES,
        )
        if [len(chunk) for chunk in payload_chunks] != [
            len(chunk) for chunk in provisional_chunks
        ]:
            raise RuntimeError("final statement changed the predetermined segment carrier layout")

        candidate_path = temp / "candidate.h264"
        phase_started = time.perf_counter()
        _emit_progress_event({"phase": "embed", "event": "started"})
        embedded = embed_chunked_video_payload(
            source,
            candidate_path,
            payload,
            sync_key,
            DEFAULT_CONTRACT,
            frames_per_segment=DEFAULT_STREAM_SEGMENT_FRAMES,
            chunk_size=DEFAULT_STREAM_CHUNK_BYTES,
            progress_callback=_emit_progress_event,
        )
        stage_ms["embed_and_strict_decode"] = (time.perf_counter() - phase_started) * 1000
        _emit_progress_event(
            {
                "phase": "embed",
                "event": "completed",
                "segments_used": embedded.segments_used,
                "carriers_used": embedded.carriers_used,
            }
        )
        if embedded.segments_used != len(provisional_chunks):
            raise RuntimeError("embedding used a different number of video segments than planned")

        phase_started = time.perf_counter()
        _emit_progress_event({"phase": "blind_extract_verify", "event": "started"})
        verification = _verify_from_video(
            candidate_path,
            relation_path=relation_input,
            trusted_relation_sha256=relation_pin,
            sync_key=sync_key,
            go_command=go_command,
            timeout_seconds=timeout_seconds,
            progress_callback=_emit_progress_event,
        )
        stage_ms["blind_extract_and_verify"] = (time.perf_counter() - phase_started) * 1000
        _emit_progress_event(
            {
                "phase": "blind_extract_verify",
                "event": "completed",
                "carriers_used": verification["carriers_used"],
            }
        )
        stage_ms["total_before_artifact_publish"] = (time.perf_counter() - started) * 1000

        # Publish verifier configuration and measurements, never the witness or proof.
        if output.exists() or output.is_symlink():
            raise FileExistsError("output video appeared during the run; refusing to overwrite")
        os.link(candidate_path, output)
        candidate_path.unlink()
        output_video_sha256 = _sha256_file(output)
        peak_rss_mb = rss_sampler.stop()
        report = {
            "protocol": PROBE_PROTOCOL,
            "security_status": "experimental only; pre-provisioned verifier-pinned relation, no independent audit, not application ZKP",
            "input_video": str(source),
            "input_video_sha256": _sha256_file(source),
            "output_video": str(output),
            "output_video_sha256": output_video_sha256,
            "relation_artifact": str(relation_input),
            "trusted_relation_sha256": relation_pin,
            "statement_id": verification["statement_id"],
            "proof_mode": proof_mode,
            "proof_format": verification["proof_format"],
            "proof_bytes": verification["proof_bytes"],
            "cryptographic_prove_ms": prove_result.get("prove_ms"),
            "cryptographic_verify_ms": verification["verify_ms"],
            "embedded_payload_bytes": len(payload),
            "blind_envelope_bytes": sum(14 + len(chunk) for chunk in payload_chunks),
            "carriers_used": verification["carriers_used"],
            "strict_h264_decode": True,
            "blind_video_only_extraction": True,
            "proof_verification": True,
            "segmented_transport": {
                "protocol": "ZKBC-v1",
                "frames_per_segment": DEFAULT_STREAM_SEGMENT_FRAMES,
                "chunk_bytes": DEFAULT_STREAM_CHUNK_BYTES,
                "segments_used": embedded.segments_used,
                "segments_with_payload": carrier_context.segments_used,
                "carrier_bits_used": verification["carriers_used"],
            },
            "verification_result": verification,
            "phase_ms": stage_ms,
            "peak_rss_mb": peak_rss_mb,
            "rss_sampling_errors_observed": rss_sampler.rss_sampling_errors_observed,
            "rss_sampling_error_count": rss_sampler.rss_sampling_error_count,
            "rss_note": (
                "peak summed RSS of this Python process and recursive child processes; "
                f"nominal wait interval {RSS_SAMPLE_INTERVAL_SECONDS:.3f} seconds; "
                "sampling may miss short spikes; process exit races are ignored, while "
                "access/measurement errors increment rss_sampling_error_count and mark "
                "rss_sampling_errors_observed true"
            ),
            "limitations": [
                "relation and private witness must be provisioned by a separate trusted setup",
                "proof establishes knowledge of the pinned short linear-relation witness only",
                "proof does not establish the payload commitment opening or H.264 encoder correctness",
                "demo payload is public; no payload privacy or replay-state service is provided",
                "sync key and relation pin are verifier configuration and are not embedded",
                "one run is not a realtime or representative performance benchmark",
            ],
        }
        with report_final.open("x", encoding="utf-8", newline="\n") as report_file:
            json.dump(report, report_file, indent=2, sort_keys=True)
            report_file.write("\n")
        _emit_progress_event({"phase": "run", "event": "completed"})
        return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    embed_parser = subparsers.add_parser("embed", help="generate, embed, extract and verify a probe proof")
    embed_parser.add_argument("--video", type=Path, required=True)
    embed_parser.add_argument("--output", type=Path, required=True)
    embed_parser.add_argument("--relation", type=Path, required=True)
    embed_parser.add_argument("--witness", type=Path, required=True)
    embed_parser.add_argument("--trusted-relation-sha256", required=True)
    embed_parser.add_argument("--report-output", type=Path, required=True)
    embed_parser.add_argument(
        "--proof-mode",
        choices=("augmented", "compact"),
        default="augmented",
        help=(
            "proof representation; compact (LNPF v2) is experimental and "
            "does not imply an audited application ZKP"
        ),
    )
    embed_parser.add_argument("--go-command", default="go")
    embed_parser.add_argument("--timeout-seconds", type=int, default=1800)

    verify_parser = subparsers.add_parser("verify", help="extract and verify a proof from video only")
    verify_parser.add_argument("--video", type=Path, required=True)
    verify_parser.add_argument("--relation", type=Path, required=True)
    verify_parser.add_argument("--trusted-relation-sha256", required=True)
    verify_parser.add_argument("--go-command", default="go")
    verify_parser.add_argument("--timeout-seconds", type=int, default=1800)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        sync_key = _sync_key_from_environment()
        if args.timeout_seconds < 1:
            raise ValueError("timeout-seconds must be positive")
        if args.mode == "embed":
            result = embed_and_verify(
                args.video,
                args.output,
                args.report_output,
                relation_path=args.relation,
                witness_path=args.witness,
                trusted_relation_sha256=args.trusted_relation_sha256,
                proof_mode=args.proof_mode,
                go_command=args.go_command,
                timeout_seconds=args.timeout_seconds,
            )
        else:
            relation_path = args.relation.resolve(strict=True)
            _validate_sha256(args.trusted_relation_sha256, "trusted relation digest")
            result = _verify_from_video(
                args.video.resolve(strict=True),
                relation_path=relation_path,
                trusted_relation_sha256=args.trusted_relation_sha256,
                sync_key=sync_key,
                go_command=args.go_command,
                timeout_seconds=args.timeout_seconds,
                progress_callback=_emit_progress_event,
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (FileNotFoundError, FileExistsError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        _emit_progress_event({"phase": "run", "event": "failed", "error_type": type(error).__name__})
        print(json.dumps({"valid": False, "error": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
