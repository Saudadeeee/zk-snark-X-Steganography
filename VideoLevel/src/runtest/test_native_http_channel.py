"""Fixture E2E for native HTTP jobs, incremental pipes, and WebSocket streaming."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

from src.api.app import TERMINAL_JOB_STATUSES, ApiSettings
from src.api.native_handlers import create_native_app
from src.runtest._helpers import run_test, section, summarise

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "data" / "encoded" / "foreman_cif_q18_g1_300f.h264"
DEFAULT_CLI = ROOT / "native" / "build" / "Release" / "zkstego_blind_bits.exe"


def _wait_terminal(client: TestClient, job_id: str, headers: dict[str, str]) -> dict:
    for _ in range(300):
        response = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
        assert response.status_code == 200, response.text
        record = response.json()
        if record["status"] in TERMINAL_JOB_STATUSES:
            return record
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish within 15 seconds")


def t_native_http_embed_blind_extract_wrong_key_and_strict_decode():
    cli = Path(os.environ.get("ZK_STEGO_NATIVE_CLI", DEFAULT_CLI))
    assert cli.is_file(), f"native CLI missing: {cli}; build zkstego_blind_bits first"
    assert FIXTURE.is_file(), f"fixture missing: {FIXTURE}"
    fixture_bytes = FIXTURE.read_bytes()
    key = bytes(range(32))
    payload = b"native-http-proof"
    headers = {"Authorization": "Bearer integration-test-token-0123456789abcdef"}

    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_native_app(
            ApiSettings(api_token="integration-test-token-0123456789abcdef", work_dir=Path(temp_dir), max_workers=1, max_queued_jobs=1),
            cli_path=cli,
        )
        with TestClient(app) as client:
            # The cover fixture carries no authenticated payload: the native verify job must be
            # "rejected" (never "succeeded"), with no message in the result.
            cover_verify = client.post(
                "/api/v1/jobs/verify",
                headers=headers,
                data={
                    "secret_key_b64": base64.b64encode(key).decode("ascii"),
                    "maximum_payload_bytes": "512",
                },
                files={"stego_video": ("stego.h264", fixture_bytes, "video/h264")},
            )
            assert cover_verify.status_code == 202, cover_verify.text
            cover_verify_job = _wait_terminal(client, cover_verify.json()["job_id"], headers)
            assert cover_verify_job["status"] == "rejected", cover_verify_job
            assert cover_verify_job["result"] == {"valid": False, "reason": "payload_not_authenticated"}

            embedded = client.post(
                "/api/v1/jobs/embed",
                headers=headers,
                data={
                    "message_b64": base64.b64encode(payload).decode("ascii"),
                    "secret_key_b64": base64.b64encode(key).decode("ascii"),
                },
                files={"video": ("camera-fixture.h264", fixture_bytes, "video/h264")},
            )
            assert embedded.status_code == 202, embedded.text
            embedded_job = _wait_terminal(client, embedded.json()["job_id"], headers)
            assert embedded_job["status"] == "succeeded", embedded_job

            artifact_url = f"/api/v1/jobs/{embedded_job['job_id']}/artifact"
            with ThreadPoolExecutor(max_workers=2) as pool:
                downloads = list(pool.map(
                    lambda _: client.get(artifact_url, headers=headers), range(2),
                ))
            assert sorted(response.status_code for response in downloads) == [200, 404]
            artifact_response = next(response for response in downloads if response.status_code == 200)
            stego = artifact_response.content
            assert len(stego) == len(fixture_bytes)
            decoded = subprocess.run(
                ["ffmpeg", "-v", "error", "-xerror", "-i", "pipe:0", "-f", "null", "-"],
                input=stego, capture_output=True, check=False,
            )
            assert decoded.returncode == 0, decoded.stderr.decode("utf-8", errors="replace")

            extracted = client.post(
                "/api/v1/jobs/extract",
                headers=headers,
                data={
                    "secret_key_b64": base64.b64encode(key).decode("ascii"),
                    "maximum_payload_bytes": "128",
                },
                files={"stego_video": ("stego.h264", stego, "video/h264")},
            )
            assert extracted.status_code == 202, extracted.text
            extracted_job = _wait_terminal(client, extracted.json()["job_id"], headers)
            assert extracted_job["status"] == "succeeded", extracted_job
            payload_response = client.get(
                f"/api/v1/jobs/{extracted_job['job_id']}/artifact", headers=headers,
            )
            assert payload_response.status_code == 200, payload_response.text
            assert payload_response.content == payload
            payload_record = client.get(
                f"/api/v1/jobs/{extracted_job['job_id']}", headers=headers,
            ).json()
            assert payload_record.get("artifact_expired") is True
            assert not (Path(temp_dir) / "files" / extracted_job["job_id"] / "payload.bin").exists()

            wrong_key = bytes([0xA5]) * 32
            rejected = client.post(
                "/api/v1/jobs/extract",
                headers=headers,
                data={
                    "secret_key_b64": base64.b64encode(wrong_key).decode("ascii"),
                    "maximum_payload_bytes": "128",
                },
                files={"stego_video": ("stego.h264", stego, "video/h264")},
            )
            assert rejected.status_code == 202, rejected.text
            rejected_job = _wait_terminal(client, rejected.json()["job_id"], headers)
            assert rejected_job["status"] == "failed", rejected_job
            assert client.get(
                f"/api/v1/jobs/{rejected_job['job_id']}/artifact", headers=headers,
            ).status_code == 404

            for index, tail in enumerate((b"\n", b"f\n", b"f" * 8194 + b"\n")):
                malformed_output = Path(temp_dir) / f"malformed-{index}.h264"
                malformed = subprocess.run(
                    [str(cli), "embed-stream-auth-stdin", str(FIXTURE), str(malformed_output), "64"],
                    input=key.hex().encode("ascii") + b"\n" + tail,
                    capture_output=True, check=False,
                )
                assert malformed.returncode != 0
                # Must fail on the malformed stdin, not because the command is unknown.
                assert b"usage" not in malformed.stderr.lower(), malformed.stderr
                assert not malformed_output.exists()

            overlong_key = subprocess.run(
                [str(cli), "embed-stream-auth-stdin", str(FIXTURE), str(Path(temp_dir) / "overlong-key.h264"), "64"],
                input=(b"1" * 65) + b"\n" + payload.hex().encode("ascii") + b"\n",
                capture_output=True, check=False,
            )
            assert overlong_key.returncode != 0
            assert b"usage" not in overlong_key.stderr.lower(), overlong_key.stderr
            assert not (Path(temp_dir) / "overlong-key.h264").exists()


def t_native_incremental_stdin_stdout_stream_round_trip():
    cli = Path(os.environ.get("ZK_STEGO_NATIVE_CLI", DEFAULT_CLI))
    assert cli.is_file(), f"native CLI missing: {cli}"
    assert FIXTURE.is_file(), f"fixture missing: {FIXTURE}"
    key = bytes(range(32))
    payload = b"incremental-live-proof"
    fixture = FIXTURE.read_bytes()
    process = subprocess.Popen(
        [str(cli), "embed-live-auth-stdin", "64"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    output_parts: list[bytes] = []
    first_output = threading.Event()

    def collect_output() -> None:
        while chunk := process.stdout.read(8192):
            output_parts.append(chunk)
            first_output.set()

    output_reader = threading.Thread(target=collect_output, daemon=True)
    output_reader.start()
    try:
        process.stdin.write(key.hex().encode("ascii") + b"\n" + payload.hex().encode("ascii") + b"\n")
        process.stdin.write(fixture[: len(fixture) // 4])
        process.stdin.flush()
        assert first_output.wait(15), "stream encoder waited for EOF instead of forwarding completed NALs"
        process.stdin.write(fixture[len(fixture) // 4 :])
        process.stdin.close()
        exit_code = process.wait(timeout=120)
        stderr = process.stderr.read()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        output_reader.join(timeout=10)
    assert exit_code == 0, stderr.decode("utf-8", errors="replace")
    live_stego = b"".join(output_parts)
    assert live_stego, "live streaming CLI produced no H.264 output"
    extracted = subprocess.run(
        [str(cli), "extract-live-auth-stdin", "64", "64"],
        input=key.hex().encode("ascii") + b"\n" + live_stego,
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert extracted.returncode == 0, extracted.stderr.decode("utf-8", errors="replace")
    assert bytes.fromhex(extracted.stdout.decode("ascii").strip()) == payload

    wrong_key = bytes([0xA5]) * 32
    rejected = subprocess.run(
        [str(cli), "extract-live-auth-stdin", "64", "64"],
        input=wrong_key.hex().encode("ascii") + b"\n" + live_stego,
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert rejected.returncode != 0, "live streaming extractor accepted a wrong key"
    strict = subprocess.run(
        ["ffmpeg", "-v", "error", "-xerror", "-i", "pipe:0", "-f", "null", "-"],
        input=live_stego,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert strict.returncode == 0, strict.stderr.decode("utf-8", errors="replace")


def t_native_full_stream_capacity_scan():
    cli = Path(os.environ.get("ZK_STEGO_NATIVE_CLI", DEFAULT_CLI))
    assert cli.is_file(), f"native CLI missing: {cli}"
    fixture = FIXTURE.read_bytes()
    result = subprocess.run(
        [str(cli), "measure-live-capacity-stdin", "64"],
        input=fixture,
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    lines = [line for line in result.stdout.decode("ascii").splitlines()
             if line.startswith("ZKSTEG_CAPACITY_METRICS ")]
    assert len(lines) == 1, result.stdout.decode("utf-8", errors="replace")
    metrics = json.loads(lines[0].removeprefix("ZKSTEG_CAPACITY_METRICS "))
    assert metrics["max_bits_per_idr"] == 64
    assert metrics["idr_segments"] > 0
    assert metrics["raw_candidate_signs"] >= metrics["candidate_capacity_bits"] > 0
    assert metrics["candidate_capacity_bits"] <= metrics["idr_segments"] * 64
    no_idr = subprocess.run(
        [str(cli), "measure-live-capacity-stdin", "64"],
        input=b"\x00\x00\x01\x09\xf0",
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert no_idr.returncode != 0, "capacity scan accepted a stream with no IDR pictures"


def t_native_authenticated_websocket_live_round_trip():
    cli = Path(os.environ.get("ZK_STEGO_NATIVE_CLI", DEFAULT_CLI))
    assert cli.is_file(), f"native CLI missing: {cli}"
    fixture = FIXTURE.read_bytes()
    key = bytes(range(32))
    payload = b"ws-proof"
    token = "websocket-e2e-token-0123456789abcdef"
    headers = {"Authorization": f"Bearer {token}"}

    def drain_messages(messages: queue.Queue, terminal: threading.Event) -> tuple[list[bytes], dict]:
        video_parts: list[bytes] = []
        terminal_message: dict = {}
        while not terminal.is_set() or not messages.empty():
            try:
                message = messages.get(timeout=15)
            except queue.Empty as exc:
                raise AssertionError("WebSocket stream did not reach a terminal message") from exc
            if message.get("type") == "websocket.send" and message.get("bytes") is not None:
                video_parts.append(message["bytes"])
            elif message.get("type") == "websocket.send" and message.get("text"):
                terminal_message = json.loads(message["text"])
                if terminal_message.get("type") in {"complete", "payload", "error"}:
                    terminal.set()
        return video_parts, terminal_message

    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_native_app(
            ApiSettings(api_token=token, work_dir=Path(temp_dir), max_workers=1, max_queued_jobs=0),
            cli_path=cli,
        )
        with TestClient(app) as client:
            # Authentication happens before accept(): the handshake itself is refused.
            for bad_headers in ({}, {"Authorization": "Bearer töken".encode("latin-1")}):
                try:
                    with client.websocket_connect("/api/v1/stream", headers=bad_headers):
                        raise AssertionError("unauthenticated WebSocket handshake was accepted")
                except WebSocketDisconnect as exc:
                    assert exc.code == 4401, exc.code

            with client.websocket_connect("/api/v1/stream", headers=headers) as occupied:
                occupied.send_json({
                    "operation": "embed",
                    "secret_key_b64": base64.b64encode(key).decode("ascii"),
                    "message_b64": base64.b64encode(payload).decode("ascii"),
                })
                assert occupied.receive_json() == {"type": "ready", "operation": "embed"}
                with client.websocket_connect("/api/v1/stream", headers=headers) as rejected:
                    busy = rejected.receive_json()
                    assert busy == {"type": "error", "code": "stream_capacity_reached"}

            with client.websocket_connect("/api/v1/stream", headers=headers) as websocket:
                websocket.send_json({
                    "operation": "embed",
                    "secret_key_b64": base64.b64encode(key).decode("ascii"),
                    "message_b64": base64.b64encode(payload).decode("ascii"),
                })
                assert websocket.receive_json() == {"type": "ready", "operation": "embed"}
                messages: queue.Queue = queue.Queue()
                terminal = threading.Event()

                def collect_embed() -> None:
                    while True:
                        message = websocket.receive()
                        messages.put(message)
                        if message.get("type") == "websocket.send" and message.get("text"):
                            if json.loads(message["text"]).get("type") in {"complete", "error"}:
                                return
                        if message.get("type") == "websocket.disconnect":
                            return

                receiver = threading.Thread(target=collect_embed, daemon=True)
                receiver.start()
                websocket.send_bytes(fixture[: len(fixture) // 4])
                first = messages.get(timeout=15)
                assert first.get("type") == "websocket.send" and first.get("bytes"), first
                for offset in range(len(fixture) // 4, len(fixture), 64 * 1024):
                    websocket.send_bytes(fixture[offset : offset + (64 * 1024)])
                websocket.send_json({"type": "end"})
                receiver.join(timeout=60)
                assert not receiver.is_alive(), "embed WebSocket did not terminate after end marker"
                terminal.set()
                stego_parts, final_message = drain_messages(messages, terminal)
                assert final_message.get("type") == "complete", final_message
                flow = final_message.get("flow_control")
                assert isinstance(flow, dict), final_message
                assert flow["input_chunks"] > 0 and flow["input_bytes"] == len(fixture)
                assert 0 < flow["max_input_chunk_bytes"] <= flow["input_chunk_limit_bytes"]
                assert flow["max_native_stdin_buffer_bytes"] <= (
                    flow["native_stdin_high_water_bytes"] + flow["input_chunk_limit_bytes"]
                )
                assert flow["output_chunks"] > 0
                assert flow["max_output_chunk_bytes"] <= flow["output_chunk_limit_bytes"]
                assert flow["input_drain_count"] == flow["input_chunks"]
                assert flow["dropped_input_chunks"] == 0
                metrics = final_message.get("native_metrics")
                assert isinstance(metrics, dict), final_message
                assert metrics["patched_idr_segments"] > 0
                assert metrics["bits_embedded"] == (len(payload) + 19) * 8
                assert metrics["candidate_capacity_bits"] >= metrics["bits_embedded"]
                assert metrics["idr_segment_count"] >= metrics["patched_idr_segments"]
                assert metrics["idr_service_samples"] == min(
                    metrics["idr_segment_count"], metrics["idr_service_sample_limit"],
                )
                assert 0 <= metrics["idr_service_p50_ms"] <= metrics["idr_service_p95_ms"]
                assert metrics["segment_process_samples"] == min(
                    metrics["patched_idr_segments"], metrics["segment_process_sample_limit"],
                )
                assert 0 <= metrics["segment_process_p50_ms"] <= metrics["segment_process_p95_ms"]
                resources = final_message.get("native_resources")
                assert isinstance(resources, dict), final_message
                assert resources["sample_count"] > 0 and resources["peak_rss_bytes"] > 0
                assert resources["cpu_seconds"] >= 0 and resources["wall_seconds"] > 0
                stego = first["bytes"] + b"".join(stego_parts)
                assert stego

            strict = subprocess.run(
                ["ffmpeg", "-v", "error", "-xerror", "-i", "pipe:0", "-f", "null", "-"],
                input=stego,
                capture_output=True,
                check=False,
                timeout=60,
            )
            assert strict.returncode == 0, strict.stderr.decode("utf-8", errors="replace")

            def extract_over_websocket(secret_key: bytes) -> dict:
                from starlette.websockets import WebSocketDisconnect

                responses: queue.Queue = queue.Queue()
                terminal_types = {"payload", "error"}
                with client.websocket_connect("/api/v1/stream", headers=headers) as websocket:
                    websocket.send_json({
                        "operation": "extract",
                        "secret_key_b64": base64.b64encode(secret_key).decode("ascii"),
                        "maximum_payload_bytes": 64,
                    })
                    assert websocket.receive_json() == {"type": "ready", "operation": "extract"}

                    def collect_extract() -> None:
                        while True:
                            message = websocket.receive()
                            if message.get("type") == "websocket.send" and message.get("text"):
                                response_message = json.loads(message["text"])
                                if response_message.get("type") in terminal_types:
                                    responses.put(response_message)
                                    return
                            if message.get("type") == "websocket.disconnect":
                                responses.put({"type": "disconnect"})
                                return

                    receiver = threading.Thread(target=collect_extract, daemon=True)
                    receiver.start()
                    terminal_response = None
                    for offset in range(0, len(stego), 64 * 1024):
                        try:
                            websocket.send_bytes(stego[offset : offset + (64 * 1024)])
                        except (WebSocketDisconnect, RuntimeError):
                            break
                        try:
                            terminal_response = responses.get(timeout=0.01)
                            break
                        except queue.Empty:
                            pass
                    if terminal_response is None:
                        try:
                            websocket.send_json({"type": "end"})
                        except (WebSocketDisconnect, RuntimeError):
                            pass
                        terminal_response = responses.get(timeout=30)
                    receiver.join(timeout=10)
                    assert not receiver.is_alive(), "extract WebSocket receiver did not stop"
                    return terminal_response

            response = extract_over_websocket(key)
            assert response.get("type") == "payload", response
            assert base64.b64decode(response["payload_b64"], validate=True) == payload

            wrong_key = bytes([0xAC]) * 32
            response = extract_over_websocket(wrong_key)
            assert response.get("type") == "error" and response.get("code") == "payload_not_authenticated", response
            assert "key" not in json.dumps(response).lower()


def t_native_websocket_idle_stream_releases_capacity():
    cli = Path(os.environ.get("ZK_STEGO_NATIVE_CLI", DEFAULT_CLI))
    assert cli.is_file(), f"native CLI missing: {cli}"
    token = "websocket-idle-token-0123456789abcdef"
    headers = {"Authorization": f"Bearer {token}"}
    start = {
        "operation": "extract",
        "secret_key_b64": base64.b64encode(bytes(range(32))).decode("ascii"),
        "maximum_payload_bytes": 64,
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_native_app(
            ApiSettings(api_token=token, work_dir=Path(temp_dir), max_workers=1, max_queued_jobs=0),
            cli_path=cli,
            stream_idle_timeout_seconds=0.5,
        )
        with TestClient(app) as client:
            started = time.perf_counter()
            with client.websocket_connect("/api/v1/stream", headers=headers) as idle:
                idle.send_json(start)
                assert idle.receive_json() == {"type": "ready", "operation": "extract"}
                assert idle.receive_json() == {"type": "error", "code": "stream_idle_timeout"}
                closed = idle.receive()
                assert closed.get("type") == "websocket.close" and closed.get("code") == 4408, closed
            assert time.perf_counter() - started < 10.0
            # The slot held by the idle stream must have been released.
            with client.websocket_connect("/api/v1/stream", headers=headers) as follow_up:
                follow_up.send_json(start)
                assert follow_up.receive_json() == {"type": "ready", "operation": "extract"}
                follow_up.send_text(json.dumps({"type": "end"}))
                assert follow_up.receive_json()["type"] == "error"


def t_native_websocket_auth_failures_are_throttled():
    cli = Path(os.environ.get("ZK_STEGO_NATIVE_CLI", DEFAULT_CLI))
    assert cli.is_file(), f"native CLI missing: {cli}"
    token = "websocket-throttle-token-0123456789abcdef"
    headers = {"Authorization": f"Bearer {token}"}
    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_native_app(
            ApiSettings(api_token=token, work_dir=Path(temp_dir), auth_failure_limit=2),
            cli_path=cli,
        )
        with TestClient(app) as client:
            for _ in range(2):
                try:
                    with client.websocket_connect("/api/v1/stream", headers={"Authorization": "Bearer wrong"}):
                        raise AssertionError("unauthenticated WebSocket handshake was accepted")
                except WebSocketDisconnect as exc:
                    assert not isinstance(exc, WebSocketDenialResponse) and exc.code == 4401, exc
            # Throttled before the token is checked, so even the right token is refused until the window ends.
            try:
                with client.websocket_connect("/api/v1/stream", headers=headers):
                    raise AssertionError("throttled WebSocket handshake was accepted")
            except WebSocketDenialResponse as denial:
                assert denial.status_code == 429, denial.status_code
                assert int(denial.headers["retry-after"]) >= 1
            # The limiter is shared with the HTTP guard: the same client is throttled on jobs too.
            throttled = client.get("/api/v1/jobs/" + "a" * 24, headers=headers)
            assert throttled.status_code == 429, throttled.text


def t_native_uvicorn_network_websocket_round_trip():
    import httpx
    import websockets

    cli = Path(os.environ.get("ZK_STEGO_NATIVE_CLI", DEFAULT_CLI))
    assert cli.is_file(), f"native CLI missing: {cli}"
    fixture = FIXTURE.read_bytes()
    key = bytes(range(32))
    payload = b"uvicorn-network-ws-proof"
    token = "uvicorn-network-websocket-e2e-token"
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="zkstego-uvicorn-ws-") as work_dir:
        environment = os.environ.copy()
        environment.update({
            "ZK_STEGO_API_TOKEN": token,
            "ZK_STEGO_NATIVE_CLI": str(cli),
            "ZK_STEGO_API_WORK_DIR": work_dir,
        })
        server = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                "src.api.native_handlers:create_native_app", "--factory",
                "--host", "127.0.0.1", "--port", str(port), "--workers", "1",
                "--ws", "websockets", "--ws-max-size", str(1024 * 1024),
                "--ws-max-queue", "1", "--no-access-log",
            ],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        uri = f"ws://127.0.0.1:{port}/api/v1/stream"
        try:
            for _ in range(100):
                if server.poll() is not None:
                    details = server.stderr.read().decode("utf-8", errors="replace") if server.stderr else ""
                    raise AssertionError(f"Uvicorn exited during startup: {details}")
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.2).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.05)
            else:
                raise AssertionError("real Uvicorn server did not become ready")

            async def network_round_trip() -> tuple[bytes, dict, dict, dict]:
                headers = {"Authorization": f"Bearer {token}"}
                async with websockets.connect(
                    uri, additional_headers=headers, max_size=1024 * 1024, max_queue=1,
                    compression=None, proxy=None,
                ) as websocket:
                    await websocket.send(json.dumps({
                        "operation": "embed",
                        "secret_key_b64": base64.b64encode(key).decode("ascii"),
                        "message_b64": base64.b64encode(payload).decode("ascii"),
                    }))
                    assert json.loads(await websocket.recv()) == {"type": "ready", "operation": "embed"}

                    async def collect_embed() -> tuple[bytes, dict]:
                        output = bytearray()
                        while True:
                            item = await websocket.recv()
                            if isinstance(item, bytes):
                                output.extend(item)
                            else:
                                response = json.loads(item)
                                if response.get("type") in {"complete", "error"}:
                                    return bytes(output), response

                    receiver = asyncio.create_task(collect_embed())
                    for offset in range(0, len(fixture), 64 * 1024):
                        await websocket.send(fixture[offset : offset + 64 * 1024])
                    await websocket.send(json.dumps({"type": "end"}))
                    stego, completion = await asyncio.wait_for(receiver, timeout=60)
                    assert completion.get("type") == "complete", completion

                async def extract_with(secret_key: bytes) -> dict:
                    async with websockets.connect(
                        uri, additional_headers=headers, max_size=1024 * 1024, max_queue=1,
                        compression=None, proxy=None,
                    ) as websocket:
                        await websocket.send(json.dumps({
                            "operation": "extract",
                            "secret_key_b64": base64.b64encode(secret_key).decode("ascii"),
                            "maximum_payload_bytes": 64,
                        }))
                        assert json.loads(await websocket.recv()) == {"type": "ready", "operation": "extract"}

                        async def collect_extract() -> dict:
                            while True:
                                item = await websocket.recv()
                                if isinstance(item, str):
                                    response = json.loads(item)
                                    if response.get("type") in {"payload", "error"}:
                                        return response

                        receiver = asyncio.create_task(collect_extract())
                        for offset in range(0, len(stego), 64 * 1024):
                            if receiver.done():
                                break
                            try:
                                await websocket.send(stego[offset : offset + 64 * 1024])
                            except websockets.ConnectionClosed:
                                break
                        if not receiver.done():
                            await websocket.send(json.dumps({"type": "end"}))
                        return await asyncio.wait_for(receiver, timeout=30)

                correct = await extract_with(key)
                wrong = await extract_with(bytes([0xAC]) * 32)
                return stego, completion, correct, wrong

            try:
                stego, completion, correct, wrong = asyncio.run(network_round_trip())
            except Exception as exc:
                server.terminate()
                server.wait(timeout=10)
                server_log = server.stderr.read().decode("utf-8", errors="replace") if server.stderr else ""
                raise AssertionError(f"real Uvicorn WebSocket request failed ({type(exc).__name__}: {exc!r}): {server_log}") from exc
            assert len(stego) == len(fixture), (len(fixture), len(stego))
            strict = subprocess.run(
                ["ffmpeg", "-v", "error", "-xerror", "-i", "pipe:0", "-f", "null", "-"],
                input=stego, capture_output=True, check=False, timeout=60,
            )
            assert strict.returncode == 0, strict.stderr.decode("utf-8", errors="replace")
            assert correct.get("type") == "payload", correct
            assert base64.b64decode(correct["payload_b64"], validate=True) == payload
            assert wrong.get("type") == "error" and wrong.get("code") == "payload_not_authenticated", wrong
            flow = completion.get("flow_control")
            assert isinstance(flow, dict), completion
            assert flow["input_bytes"] == len(fixture)
            assert 0 < flow["max_input_chunk_bytes"] <= 1024 * 1024
            assert flow["input_drain_count"] == flow["input_chunks"]
            assert flow["dropped_input_chunks"] == 0
            assert flow["native_stdin_write_drain_samples"] == flow["input_chunks"]
            assert flow["native_stdout_to_websocket_send_samples"] == flow["output_chunks"]
            assert flow["native_stdout_read_wait_samples"] == flow["output_chunks"] + 1
            assert 0 <= flow["native_stdin_write_drain_p50_ms"] <= flow["native_stdin_write_drain_p95_ms"]
            assert 0 <= flow["native_stdout_to_websocket_send_p50_ms"] <= flow["native_stdout_to_websocket_send_p95_ms"]
            assert 0 <= flow["native_stdout_read_wait_p50_ms"] <= flow["native_stdout_read_wait_p95_ms"]
        finally:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)
            if server.stderr is not None:
                server.stderr.read()


def main():
    section("Native CAVLC channel fixture E2E")
    results = [
        run_test("native_http_embed_blind_extract_wrong_key_and_strict_decode", t_native_http_embed_blind_extract_wrong_key_and_strict_decode),
        run_test("native_incremental_stdin_stdout_stream_round_trip", t_native_incremental_stdin_stdout_stream_round_trip),
        run_test("native_full_stream_capacity_scan", t_native_full_stream_capacity_scan),
        run_test("native_authenticated_websocket_live_round_trip", t_native_authenticated_websocket_live_round_trip),
        run_test("native_websocket_idle_stream_releases_capacity", t_native_websocket_idle_stream_releases_capacity),
        run_test("native_websocket_auth_failures_are_throttled", t_native_websocket_auth_failures_are_throttled),
        run_test("native_uvicorn_network_websocket_round_trip", t_native_uvicorn_network_websocket_round_trip),
    ]
    sys.exit(summarise(results, "Native channel E2E"))


if __name__ == "__main__":
    main()
