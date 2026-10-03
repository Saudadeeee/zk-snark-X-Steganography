"""FastAPI adapter for the authenticated native CAVLC CLI.

The 32-byte key is delivered only through the child's stdin, never argv or a
temporary key file. Configure ``ZK_STEGO_NATIVE_CLI`` with the built executable.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import math
import os
import subprocess
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psutil
from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect

from src.api.app import ApiSettings, bearer_token_matches, client_host, create_app
from src.zk_proof import PROOF_SIZE_BYTES, ZKSnarkBridge, bytes_to_proof, unpack

_LOGGER = logging.getLogger(__name__)

NATIVE_STDERR_TAIL_BYTES = 64 * 1024
DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS = 15.0

# (stego_video_path, secret_key, maximum_payload_bytes) -> authenticated payload bytes.
PayloadExtractor = Callable[[str, bytes, int], bytes]
# (proof_dict, message, secret_key) -> True only when the Groth16 proof verifies.
ProofVerifier = Callable[[dict, bytes, bytes], bool]


class _StreamIdleTimeout(Exception):
    pass


class NativePayloadNotAuthenticated(RuntimeError):
    """The native CLI exited non-zero: no authenticated payload under this key (or a bad stream)."""


def make_proof_verify_handler(
    extract_payload: PayloadExtractor, verify_proof: ProofVerifier,
) -> Callable[..., dict[str, Any]]:
    """Blind-extract ``pack(message, proof)`` and accept it only if its Groth16 proof verifies.

    Returns ``{"valid": True, "message_b64", "payload_bytes"}`` for a verified proof and
    ``{"valid": False, "reason"}`` when no authenticated payload, a malformed blob or an
    invalid proof is found. Infrastructure errors (timeouts, missing Node.js/circuits)
    propagate, so the job service marks the job "failed" rather than "rejected".
    """

    def verify_handler(*, stego_video_path: str, secret_key: bytes, maximum_payload_bytes: int) -> dict[str, Any]:
        try:
            blob = extract_payload(stego_video_path, secret_key, maximum_payload_bytes)
        except NativePayloadNotAuthenticated:
            return {"valid": False, "reason": "payload_not_authenticated"}
        try:
            message, proof_bytes = unpack(blob)
            if not message or len(blob) != 4 + len(message) + PROOF_SIZE_BYTES:
                raise ValueError("proof payload length mismatch")
            proof = bytes_to_proof(proof_bytes)
        except ValueError:
            return {"valid": False, "reason": "malformed_proof_payload"}
        if verify_proof(proof, message, secret_key) is not True:
            return {"valid": False, "reason": "proof_invalid"}
        return {
            "valid": True,
            "message_b64": base64.b64encode(message).decode("ascii"),
            "payload_bytes": len(blob),
        }

    return verify_handler


async def _drain_bounded(stream: asyncio.StreamReader, tail: bytearray, limit: int) -> None:
    """Continuously drain a child pipe so it never blocks, keeping only the last ``limit`` bytes."""
    while chunk := await stream.read(16 * 1024):
        tail.extend(chunk)
        if len(tail) > limit:
            del tail[: len(tail) - limit]


def create_native_app(
    settings: ApiSettings | None = None,
    *,
    cli_path: str | Path | None = None,
    timeout_seconds: float = 120.0,
    stream_timeout_seconds: float = 3600.0,
    stream_idle_timeout_seconds: float | None = None,
    payload_extractor: PayloadExtractor | None = None,
    proof_verifier: ProofVerifier | None = None,
) -> FastAPI:
    """Create bounded HTTP-job and WebSocket-stream services backed by native authenticated CAVLC.

    ``stream_idle_timeout_seconds`` (default ``ZK_STEGO_STREAM_IDLE_TIMEOUT_SECONDS`` or 15 s)
    bounds how long a stream may hold a capacity slot without sending a frame.
    ``/api/v1/jobs/verify`` blind-extracts with the native CLI and verifies the Groth16 proof
    against ``settings.circuits_dir`` (``ZK_STEGO_CIRCUITS_DIR``); ``payload_extractor`` and
    ``proof_verifier`` replace those two steps (tests inject them for determinism).
    """
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    if not math.isfinite(stream_timeout_seconds) or stream_timeout_seconds <= 0:
        raise ValueError("stream_timeout_seconds must be finite and positive")
    if stream_idle_timeout_seconds is None:
        try:
            stream_idle_timeout_seconds = float(os.environ.get(
                "ZK_STEGO_STREAM_IDLE_TIMEOUT_SECONDS", DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS,
            ))
        except ValueError as exc:
            raise ValueError("ZK_STEGO_STREAM_IDLE_TIMEOUT_SECONDS must be a number of seconds") from exc
    if not math.isfinite(stream_idle_timeout_seconds) or stream_idle_timeout_seconds <= 0:
        raise ValueError("stream_idle_timeout_seconds must be finite and positive")
    settings = settings or ApiSettings.from_environment()
    configured_cli = cli_path or os.environ.get("ZK_STEGO_NATIVE_CLI")
    if not configured_cli:
        raise RuntimeError("ZK_STEGO_NATIVE_CLI must point to zkstego_blind_bits")
    executable = Path(configured_cli).resolve(strict=True)
    if not executable.is_file():
        raise RuntimeError("ZK_STEGO_NATIVE_CLI must point to a regular executable file")
    try:
        maximum_bits_per_idr = int(os.environ.get("ZK_STEGO_MAX_BITS_PER_IDR", "64"))
    except ValueError as exc:
        raise ValueError("ZK_STEGO_MAX_BITS_PER_IDR must be a positive integer") from exc
    if maximum_bits_per_idr <= 0:
        raise ValueError("ZK_STEGO_MAX_BITS_PER_IDR must be a positive integer")

    def invoke(
        arguments: list[str], secret_key: bytes, *, stdin_tail: bytes = b"",
    ) -> subprocess.CompletedProcess[bytes]:
        if len(secret_key) != 32:
            raise ValueError("native CAVLC key must be 32 bytes")
        try:
            result = subprocess.run(
                [str(executable), *arguments],
                input=secret_key.hex().encode("ascii") + b"\n" + stdin_tail,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("native CAVLC operation timed out") from exc
        if result.returncode != 0:
            raise NativePayloadNotAuthenticated("native CAVLC operation failed")
        return result

    def embed_handler(
        *, video_path: str, message: bytes, output_path: str, secret_key: bytes, **_: Any,
    ) -> dict[str, Any]:
        invoke(
            ["embed-stream-auth-stdin", video_path, output_path, str(maximum_bits_per_idr)],
            secret_key,
            stdin_tail=message.hex().encode("ascii") + b"\n",
        )
        if not Path(output_path).is_file():
            raise RuntimeError("native CAVLC operation did not create output")
        # NOTE: computed here, not reported by the native CLI. One authenticated frame is
        # version(1) + length(2) + HMAC tag(16) + payload, i.e. (len + 19) bytes. The
        # "bits_embedded" key is kept for API compatibility; "bits_embedded_source" says how it was derived.
        computed_frame_bits = (len(message) + 19) * 8
        return {
            "valid": True,
            "bits_embedded": computed_frame_bits,
            "bits_embedded_source": "computed_frame_size",
            "output_file": Path(output_path).name,
        }

    def native_extract_payload(stego_video_path: str, secret_key: bytes, maximum_payload_bytes: int) -> bytes:
        result = invoke(
            ["extract-stream-auth", stego_video_path, "-", str(maximum_payload_bytes), str(maximum_bits_per_idr)],
            secret_key,
        )
        try:
            payload = bytes.fromhex(result.stdout.decode("ascii").strip())
        except (UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError("native CAVLC extractor returned malformed payload") from exc
        if len(payload) > maximum_payload_bytes:
            raise RuntimeError("native CAVLC extractor exceeded requested payload bound")
        return payload

    def groth16_verify(proof: dict, message: bytes, secret_key: bytes) -> bool:
        bridge = ZKSnarkBridge(str(settings.circuits_dir))
        # A missing verification key is a deployment fault ("failed"), not an invalid proof.
        if not (bridge.build_dir / bridge.VKEY_FILE).is_file():
            raise RuntimeError("Groth16 verification key is not available")
        return bridge.verify_proof_for_payload(proof, message, secret_key)

    def extract_handler(
        *, stego_video_path: str, output_path: str, secret_key: bytes, maximum_payload_bytes: int,
    ) -> dict[str, Any]:
        payload = native_extract_payload(stego_video_path, secret_key, maximum_payload_bytes)
        destination = Path(output_path)
        try:
            with destination.open("xb") as stream:
                stream.write(payload)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        return {"valid": True, "payload_bytes": len(payload)}

    app = create_app(
        settings,
        embed_handler=embed_handler,
        verify_handler=make_proof_verify_handler(
            payload_extractor or native_extract_payload, proof_verifier or groth16_verify,
        ),
        extract_handler=extract_handler,
    )

    @app.websocket("/api/v1/stream")
    async def native_stream(websocket: WebSocket) -> None:
        # Authenticate before accept(): an unauthenticated peer never completes the handshake
        # (uvicorn answers HTTP 403; the ASGI close code stays 4401 for in-process clients).
        # Failures share the HTTP guard's per-client limiter, so the WebSocket is no bypass.
        auth_limiter = app.state.auth_failure_limiter
        client = client_host(websocket.scope)
        retry_after = auth_limiter.retry_after(client)
        if retry_after:
            if "websocket.http.response" in websocket.scope.get("extensions", {}):
                await websocket.send_denial_response(JSONResponse(
                    {"detail": "too many failed authentication attempts; retry later"},
                    status_code=429, headers={"Retry-After": str(retry_after)},
                ))
            else:
                await websocket.close(code=4429, reason="too many failed authentication attempts")
            return
        if not bearer_token_matches(websocket.headers.get("authorization"), settings.api_token):
            failures = auth_limiter.record_failure(client)
            _LOGGER.warning(
                "WebSocket authentication failed: client=%s failures_in_window=%s", client, failures,
            )
            await websocket.close(code=4401, reason="authentication required")
            return
        await websocket.accept()
        if not app.state.capacity.acquire(blocking=False):
            await websocket.send_json({"type": "error", "code": "stream_capacity_reached"})
            await websocket.close(code=1013, reason="stream capacity reached")
            return

        process: asyncio.subprocess.Process | None = None
        input_task: asyncio.Task[None] | None = None
        output_task: asyncio.Task[None] | None = None
        resource_task: asyncio.Task[None] | None = None
        stderr_task: asyncio.Task[None] | None = None
        stderr_tail = bytearray()
        native_resources: dict[str, int | float] = {
            "sample_count": 0,
            "peak_rss_bytes": 0,
            "cpu_seconds": 0.0,
            "sample_interval_ms": 100,
        }
        accepted = True
        try:
            try:
                start_event = await asyncio.wait_for(websocket.receive(), timeout=10.0)
                start_text = start_event.get("text")
                if start_event.get("type") != "websocket.receive" or start_text is None or len(start_text) > 12 * 1024:
                    raise ValueError("invalid stream control message size")
                start = json.loads(start_text)
                if not isinstance(start, dict) or start.get("operation") not in {"embed", "extract"}:
                    raise ValueError("invalid stream operation")
                operation = start["operation"]
                expected_fields = (
                    {"operation", "secret_key_b64", "message_b64"}
                    if operation == "embed"
                    else {"operation", "secret_key_b64", "maximum_payload_bytes"}
                )
                if set(start) != expected_fields:
                    raise ValueError("invalid stream control message")
                key_text = start["secret_key_b64"]
                if not isinstance(key_text, str):
                    raise ValueError("invalid key encoding")
                key = base64.b64decode(key_text, validate=True)
                if len(key) != 32:
                    raise ValueError("invalid key length")
                if operation == "embed":
                    message_text = start["message_b64"]
                    if not isinstance(message_text, str):
                        raise ValueError("invalid payload encoding")
                    message = base64.b64decode(message_text, validate=True)
                    if not message or len(message) > 4096:
                        raise ValueError("invalid payload length")
                    arguments = ["embed-live-auth-stdin", str(maximum_bits_per_idr)]
                    preamble = key.hex().encode("ascii") + b"\n" + message.hex().encode("ascii") + b"\n"
                    maximum_payload_bytes = 0
                else:
                    maximum_payload_bytes = start["maximum_payload_bytes"]
                    if (not isinstance(maximum_payload_bytes, int) or isinstance(maximum_payload_bytes, bool)
                            or not 1 <= maximum_payload_bytes <= 4096):
                        raise ValueError("invalid payload bound")
                    arguments = [
                        "extract-live-auth-stdin", str(maximum_payload_bytes), str(maximum_bits_per_idr),
                    ]
                    preamble = key.hex().encode("ascii") + b"\n"
                del key
            except (asyncio.TimeoutError, KeyError, TypeError, ValueError, UnicodeError):
                await websocket.send_json({"type": "error", "code": "invalid_stream_request"})
                await websocket.close(code=4400, reason="invalid stream request")
                return

            process = await asyncio.create_subprocess_exec(
                str(executable), *arguments,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=64 * 1024,
            )
            assert process.stdin is not None and process.stdout is not None and process.stderr is not None
            # Drain stderr concurrently; an unread pipe would block the child once its buffer fills.
            stderr_task = asyncio.create_task(
                _drain_bounded(process.stderr, stderr_tail, NATIVE_STDERR_TAIL_BYTES),
            )
            native_stdin_high_water_bytes = 64 * 1024
            native_stdin_low_water_bytes = 16 * 1024
            stdin_transport = process.stdin.transport
            set_write_limits = getattr(stdin_transport, "set_write_buffer_limits", None)
            get_write_limits = getattr(stdin_transport, "get_write_buffer_limits", None)
            get_write_buffer_size = getattr(stdin_transport, "get_write_buffer_size", None)
            if not callable(set_write_limits) or not callable(get_write_limits) or not callable(get_write_buffer_size):
                raise RuntimeError("native stdin transport does not expose bounded flow control")
            set_write_limits(high=native_stdin_high_water_bytes, low=native_stdin_low_water_bytes)
            _stdin_low, observed_stdin_high = get_write_limits()
            if observed_stdin_high != native_stdin_high_water_bytes:
                raise RuntimeError("native stdin flow-control high-water mark was not applied")
            async def sample_native_resources() -> None:
                assert process is not None
                started_at = time.perf_counter()
                try:
                    monitored = psutil.Process(process.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    return
                while process.returncode is None:
                    try:
                        native_resources["peak_rss_bytes"] = max(
                            int(native_resources["peak_rss_bytes"]), monitored.memory_info().rss,
                        )
                        cpu = monitored.cpu_times()
                        native_resources["cpu_seconds"] = cpu.user + cpu.system
                        native_resources["sample_count"] = int(native_resources["sample_count"]) + 1
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        break
                    await asyncio.sleep(0.1)
                native_resources["wall_seconds"] = round(time.perf_counter() - started_at, 6)

            resource_task = asyncio.create_task(sample_native_resources())
            process.stdin.write(preamble)
            await asyncio.wait_for(process.stdin.drain(), timeout=10.0)
            deadline = asyncio.get_running_loop().time() + stream_timeout_seconds
            media_bytes_received = 0
            maximum_stream_bytes = settings.max_upload_bytes
            maximum_ws_chunk_bytes = min(1024 * 1024, settings.max_upload_bytes)
            maximum_ws_chunks = 100_000
            chunks_received = 0
            flow_control: dict[str, int | float | str] = {
                "buffering_model": "one-websocket-message-at-a-time-with-await-drain",
                "input_chunks": 0,
                "input_bytes": 0,
                "input_chunk_limit_bytes": maximum_ws_chunk_bytes,
                "max_input_chunk_bytes": 0,
                "native_stdin_low_water_bytes": native_stdin_low_water_bytes,
                "native_stdin_high_water_bytes": native_stdin_high_water_bytes,
                "max_native_stdin_buffer_bytes": 0,
                "input_drain_count": 0,
                "input_drain_wait_ms_total": 0.0,
                "output_chunks": 0,
                "output_chunk_limit_bytes": 64 * 1024,
                "max_output_chunk_bytes": 0,
                "dropped_input_chunks": 0,
            }
            input_work_samples: deque[float] = deque(maxlen=4096)
            output_send_samples: deque[float] = deque(maxlen=4096)
            output_read_wait_samples: deque[float] = deque(maxlen=4096)

            def summarize_samples(samples: deque[float], prefix: str) -> None:
                ordered = sorted(samples)

                def percentile(percent: int) -> float:
                    rank = math.ceil(percent * len(ordered) / 100)
                    return round(ordered[max(rank - 1, 0)], 4)

                flow_control[f"{prefix}_samples"] = len(ordered)
                flow_control[f"{prefix}_p50_ms"] = percentile(50)
                flow_control[f"{prefix}_p95_ms"] = percentile(95)

            await websocket.send_json({"type": "ready", "operation": operation})

            async def feed_native_stdin() -> None:
                nonlocal chunks_received, media_bytes_received
                assert process is not None and process.stdin is not None
                while True:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise TimeoutError("native stream deadline exceeded")
                    try:
                        event = await asyncio.wait_for(
                            websocket.receive(), timeout=min(remaining, stream_idle_timeout_seconds),
                        )
                    except asyncio.TimeoutError:
                        if deadline - asyncio.get_running_loop().time() <= 0:
                            raise
                        raise _StreamIdleTimeout from None
                    if event["type"] == "websocket.disconnect":
                        process.stdin.close()
                        return
                    data = event.get("bytes")
                    if data is not None:
                        chunks_received += 1
                        if (not data or len(data) > maximum_ws_chunk_bytes
                                or chunks_received > maximum_ws_chunks):
                            raise ValueError("invalid stream chunk size")
                        media_bytes_received += len(data)
                        if media_bytes_received > maximum_stream_bytes:
                            raise ValueError("stream byte limit exceeded")
                        flow_control["input_chunks"] = int(flow_control["input_chunks"]) + 1
                        flow_control["input_bytes"] = media_bytes_received
                        flow_control["max_input_chunk_bytes"] = max(
                            int(flow_control["max_input_chunk_bytes"]), len(data),
                        )
                        process.stdin.write(data)
                        flow_control["max_native_stdin_buffer_bytes"] = max(
                            int(flow_control["max_native_stdin_buffer_bytes"]), get_write_buffer_size(),
                        )
                        try:
                            remaining = deadline - asyncio.get_running_loop().time()
                            if remaining <= 0:
                                raise TimeoutError("native stream deadline exceeded")
                            write_drain_started = time.perf_counter()
                            await asyncio.wait_for(process.stdin.drain(), timeout=remaining)
                            input_work_samples.append((time.perf_counter() - write_drain_started) * 1000.0)
                            flow_control["input_drain_count"] = int(flow_control["input_drain_count"]) + 1
                            flow_control["input_drain_wait_ms_total"] = (
                                float(flow_control["input_drain_wait_ms_total"])
                                + (time.perf_counter() - write_drain_started) * 1000.0
                            )
                            flow_control["max_native_stdin_buffer_bytes"] = max(
                                int(flow_control["max_native_stdin_buffer_bytes"]), get_write_buffer_size(),
                            )
                        except (BrokenPipeError, ConnectionResetError):
                            if operation == "extract":
                                return
                            raise
                        continue
                    text = event.get("text")
                    if text is None or len(text) > 128:
                        raise ValueError("invalid stream control frame")
                    control = json.loads(text)
                    if control != {"type": "end"}:
                        raise ValueError("invalid stream control frame")
                    process.stdin.close()
                    with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                        await process.stdin.wait_closed()
                    return

            async def forward_native_output() -> None:
                assert process is not None and process.stdout is not None
                if operation == "embed":
                    while True:
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            raise TimeoutError("native stream deadline exceeded")
                        read_started = time.perf_counter()
                        chunk = await asyncio.wait_for(process.stdout.read(64 * 1024), timeout=remaining)
                        output_read_wait_samples.append((time.perf_counter() - read_started) * 1000.0)
                        if not chunk:
                            break
                        flow_control["output_chunks"] = int(flow_control["output_chunks"]) + 1
                        flow_control["max_output_chunk_bytes"] = max(
                            int(flow_control["max_output_chunk_bytes"]), len(chunk),
                        )
                        send_started = time.perf_counter()
                        await websocket.send_bytes(chunk)
                        output_send_samples.append((time.perf_counter() - send_started) * 1000.0)
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise TimeoutError("native stream deadline exceeded")
                    return_code = await asyncio.wait_for(process.wait(), timeout=remaining)
                    if return_code == 0:
                        if resource_task is not None:
                            with contextlib.suppress(asyncio.TimeoutError):
                                await asyncio.wait_for(asyncio.shield(resource_task), timeout=0.5)
                        if stderr_task is not None:
                            # The child has exited, so EOF is imminent; bound the wait regardless.
                            with contextlib.suppress(asyncio.TimeoutError):
                                await asyncio.wait_for(asyncio.shield(stderr_task), timeout=2.0)
                        native_diagnostics = bytes(stderr_tail)
                        stream_metrics = None
                        for line in native_diagnostics.decode("utf-8", errors="replace").splitlines():
                            if line.startswith("ZKSTEG_STREAM_METRICS "):
                                try:
                                    candidate_metrics = json.loads(line.removeprefix("ZKSTEG_STREAM_METRICS "))
                                except (TypeError, ValueError):
                                    continue
                                if (isinstance(candidate_metrics, dict)
                                        and set(candidate_metrics) == {
                                            "patched_idr_segments", "segment_process_samples",
                                            "segment_process_sample_limit",
                                            "segment_process_p50_ms", "segment_process_p95_ms",
                                            "candidate_capacity_bits", "bits_embedded",
                                            "idr_segment_count", "idr_service_samples",
                                            "idr_service_sample_limit", "idr_service_p50_ms",
                                            "idr_service_p95_ms",
                                        }
                                        and type(candidate_metrics["patched_idr_segments"]) is int
                                        and candidate_metrics["patched_idr_segments"] > 0
                                        and type(candidate_metrics["idr_segment_count"]) is int
                                        and candidate_metrics["idr_segment_count"] >= candidate_metrics["patched_idr_segments"]
                                        and type(candidate_metrics["idr_service_samples"]) is int
                                        and type(candidate_metrics["idr_service_sample_limit"]) is int
                                        and candidate_metrics["idr_service_sample_limit"] == 4096
                                        and candidate_metrics["idr_service_samples"] == min(
                                            candidate_metrics["idr_segment_count"],
                                            candidate_metrics["idr_service_sample_limit"],
                                        )
                                        and type(candidate_metrics["candidate_capacity_bits"]) is int
                                        and type(candidate_metrics["bits_embedded"]) is int
                                        and candidate_metrics["bits_embedded"] > 0
                                        and candidate_metrics["candidate_capacity_bits"] >= candidate_metrics["bits_embedded"]
                                        and type(candidate_metrics["segment_process_samples"]) is int
                                        and 1 <= candidate_metrics["segment_process_samples"] <= 4096
                                        and candidate_metrics["segment_process_samples"] <= candidate_metrics["patched_idr_segments"]
                                        and candidate_metrics["segment_process_sample_limit"] == 4096
                                        and all(
                                            isinstance(candidate_metrics[field], (int, float))
                                            and not isinstance(candidate_metrics[field], bool)
                                            and math.isfinite(candidate_metrics[field])
                                            and candidate_metrics[field] >= 0
                                            for field in (
                                                "segment_process_p50_ms", "segment_process_p95_ms",
                                                "idr_service_p50_ms", "idr_service_p95_ms",
                                            )
                                        )):
                                    if (candidate_metrics["segment_process_p50_ms"] > candidate_metrics["segment_process_p95_ms"]
                                            or candidate_metrics["idr_service_p50_ms"] > candidate_metrics["idr_service_p95_ms"]):
                                        continue
                                    stream_metrics = candidate_metrics
                                    break
                        response = {"type": "complete", "media_bytes": media_bytes_received}
                        if input_work_samples:
                            summarize_samples(input_work_samples, "native_stdin_write_drain")
                        if output_send_samples:
                            summarize_samples(output_send_samples, "native_stdout_to_websocket_send")
                        if output_read_wait_samples:
                            summarize_samples(output_read_wait_samples, "native_stdout_read_wait")
                        response["flow_control"] = flow_control
                        if stream_metrics is not None:
                            response["native_metrics"] = stream_metrics
                        if native_resources["sample_count"]:
                            response["native_resources"] = native_resources
                        await websocket.send_json(response)
                    else:
                        await websocket.send_json({"type": "error", "code": "incomplete_or_invalid_stream"})
                    return

                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError("native stream deadline exceeded")
                output = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
                if len(output) > maximum_payload_bytes * 2 + 1:
                    await websocket.send_json({"type": "error", "code": "invalid_native_response"})
                    return
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError("native stream deadline exceeded")
                return_code = await asyncio.wait_for(process.wait(), timeout=remaining)
                if return_code != 0:
                    await websocket.send_json({"type": "error", "code": "payload_not_authenticated"})
                    return
                try:
                    payload = bytes.fromhex(output.decode("ascii").strip())
                except (UnicodeDecodeError, ValueError):
                    await websocket.send_json({"type": "error", "code": "invalid_native_response"})
                    return
                if not payload or len(payload) > maximum_payload_bytes:
                    await websocket.send_json({"type": "error", "code": "invalid_native_response"})
                    return
                await websocket.send_json({
                    "type": "payload", "payload_b64": base64.b64encode(payload).decode("ascii"),
                })

            input_task = asyncio.create_task(feed_native_stdin())
            output_task = asyncio.create_task(forward_native_output())
            done, _ = await asyncio.wait((input_task, output_task), return_when=asyncio.FIRST_COMPLETED)
            if output_task in done:
                await output_task
                if not input_task.done():
                    input_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await input_task
            else:
                await input_task
                await output_task
        except (WebSocketDisconnect, ConnectionError, BrokenPipeError):
            pass
        except _StreamIdleTimeout:
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await websocket.send_json({"type": "error", "code": "stream_idle_timeout"})
                await websocket.close(code=4408, reason="stream idle timeout")
        except Exception:  # noqa: BLE001 - errors are deliberately generic on the wire.
            if accepted:
                with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                    await websocket.send_json({"type": "error", "code": "stream_failed"})
                    await websocket.close(code=1011, reason="stream failed")
        finally:
            try:
                for task in (input_task, output_task):
                    if task is not None and not task.done():
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError, Exception):
                            await task
                for task in (resource_task, stderr_task):
                    if task is not None and not task.done():
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError, Exception):
                            await task
                if process is not None:
                    if process.stdin is not None and not process.stdin.is_closing():
                        process.stdin.close()
                    if process.returncode is None:
                        with contextlib.suppress(ProcessLookupError):
                            process.kill()
                        with contextlib.suppress(ProcessLookupError):
                            await process.wait()
            finally:
                app.state.capacity.release()

    return app
