"""Native service steps for terminal_demo.py (skipped with --no-service).

The real ``create_native_app`` (FastAPI) runs in-process behind ``TestClient``:
HTTP jobs embed / extract / verify the session's proof-bearing payload, and the
``/api/v1/stream`` WebSocket embeds the source Annex-B sent in chunks. The
service uses the same segment protocol and ``max_bits_per_idr`` as the CLI.
"""
from __future__ import annotations

import base64
import contextlib
import json
import os
import secrets
import time
from collections.abc import Iterator
from pathlib import Path

from native_io import MAX_PAYLOAD_BYTES, ROOT, native_extract

JOB_POLL_SECONDS = 0.05
JOB_TIMEOUT_SECONDS = 600.0
WS_CHUNK_BYTES = 16 * 1024


@contextlib.contextmanager
def _max_bits_environment(max_bits: int) -> Iterator[None]:
    """create_native_app reads ZK_STEGO_MAX_BITS_PER_IDR once, at construction."""
    previous = os.environ.get("ZK_STEGO_MAX_BITS_PER_IDR")
    os.environ["ZK_STEGO_MAX_BITS_PER_IDR"] = str(max_bits)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("ZK_STEGO_MAX_BITS_PER_IDR", None)
        else:
            os.environ["ZK_STEGO_MAX_BITS_PER_IDR"] = previous


def run_all(session, tools, source: Path, stego: Path, key: bytes, payload: bytes, message: bytes,
            max_bits: int) -> None:
    from fastapi.testclient import TestClient

    from src.api.app import ApiSettings
    from src.api.native_handlers import create_native_app

    token = secrets.token_urlsafe(32)  # 43 chars; the service refuses tokens shorter than 32
    settings = ApiSettings(api_token=token, work_dir=session.folder / "service_work",
                           circuits_dir=ROOT / "circuits", max_workers=1, max_queued_jobs=2)
    with _max_bits_environment(max_bits):
        app = create_native_app(settings, cli_path=tools.native)
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        session.stage("Dich vu native qua HTTP jobs: embed -> extract -> verify (Groth16 phia server)")
        _http_jobs(session, client, headers, source, stego, key, payload, message, max_bits)
        session.stage("Dich vu native qua WebSocket /api/v1/stream: gui Annex-B theo chunk, nhan stego")
        _websocket_stream(session, tools, client, headers, source, stego, key, payload, max_bits)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _wait_job(client, headers: dict, job_id: str) -> dict:
    deadline = time.perf_counter() + JOB_TIMEOUT_SECONDS
    while time.perf_counter() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"job status {job_id}: HTTP {response.status_code} {response.text}")
        record = response.json()
        if record["status"] in {"succeeded", "rejected", "failed"}:
            return record
        time.sleep(JOB_POLL_SECONDS)
    raise RuntimeError(f"HTTP job {job_id} khong ket thuc trong {JOB_TIMEOUT_SECONDS:.0f}s")


def _submit(session, client, headers: dict, label: str, route: str, data: dict, files: dict) -> dict:
    started = time.perf_counter()
    response = client.post(route, headers=headers, data=data, files=files)
    if response.status_code != 202:
        raise RuntimeError(f"{label}: HTTP {response.status_code} {response.text}")
    record = _wait_job(client, headers, response.json()["job_id"])
    elapsed = time.perf_counter() - started
    session.report["timings_seconds"][f"http_{label}"] = elapsed
    detail = record.get("result") or {"error": record.get("error")}
    session.say(f"  POST {route:22} -> 202 queued -> {record['status']:9} {elapsed * 1000:9.1f} ms  {json.dumps(detail)}")
    return record


def _download(client, headers: dict, job_id: str) -> bytes:
    response = client.get(f"/api/v1/jobs/{job_id}/artifact", headers=headers)
    if response.status_code != 200:
        raise RuntimeError(f"artifact {job_id}: HTTP {response.status_code}")
    return response.content


def _http_jobs(session, client, headers: dict, source: Path, stego: Path, key: bytes, payload: bytes,
               message: bytes, max_bits: int) -> None:
    session.say(f"create_native_app(...) that: CLI zkstego_blind_bits, ZK_STEGO_MAX_BITS_PER_IDR={max_bits},")
    session.say("bearer token ngau nhien >= 32 ky tu; key/payload chi di qua form -> stdin cua tien trinh native.")
    health = client.get("/health")
    session.check("GET /health = 200", health.status_code == 200)
    key_field = {"secret_key_b64": _b64(key)}
    embedded = _submit(session, client, headers, "embed_job", "/api/v1/jobs/embed",
                       {**key_field, "message_b64": _b64(payload)},
                       {"video": ("source.h264", source.read_bytes(), "video/h264")})
    session.check("HTTP embed job succeeded", embedded["status"] == "succeeded")
    http_stego = _download(client, headers, embedded["job_id"])
    (session.folder / "http_stego.h264").write_bytes(http_stego)
    session.check("stego tu HTTP = stego tu CLI (byte-for-byte, cung key/payload/cap)", http_stego == stego.read_bytes())
    extract_fields = {**key_field, "maximum_payload_bytes": str(MAX_PAYLOAD_BYTES)}
    stego_file = {"stego_video": ("stego.h264", http_stego, "video/h264")}
    extracted = _submit(session, client, headers, "extract_job", "/api/v1/jobs/extract", extract_fields, stego_file)
    session.check("HTTP extract job succeeded", extracted["status"] == "succeeded")
    session.check("payload tai ve = payload proof-bearing cua phien",
                  _download(client, headers, extracted["job_id"]) == payload)
    verified = _submit(session, client, headers, "verify_job", "/api/v1/jobs/verify", extract_fields, stego_file)
    result = verified.get("result") or {}
    session.check("HTTP verify job succeeded (blind extract + Groth16 verify)",
                  verified["status"] == "succeeded" and result.get("valid") is True)
    session.check("verify job tra dung message da duoc chung minh",
                  base64.b64decode(result.get("message_b64", "")) == message)
    wrong_key = bytes([key[0] ^ 1]) + key[1:]
    rejected = _submit(session, client, headers, "verify_wrong_key", "/api/v1/jobs/verify",
                       {"secret_key_b64": _b64(wrong_key), "maximum_payload_bytes": str(MAX_PAYLOAD_BYTES)}, stego_file)
    session.check("verify job voi sai key -> rejected (payload_not_found)",
                  rejected["status"] == "rejected"
                  and (rejected.get("result") or {}).get("reason") == "payload_not_found")
    session.say("Job ket thuc: succeeded = chap nhan; rejected = khong thay khung hoac proof khong dat; failed = loi ha tang.")
    session.say("Ban ghi job khong luu key hay message; artifact chi tai duoc mot lan roi bi xoa.")


def _ws_exchange(client, headers: dict, start: dict, data: bytes) -> tuple[bytes, list[dict], int, float]:
    """Send a control message and ``data`` in chunks; collect binary output and JSON messages."""
    started = time.perf_counter()
    output, messages, chunks = bytearray(), [], 0
    with client.websocket_connect("/api/v1/stream", headers=headers) as websocket:
        websocket.send_text(json.dumps(start))
        ready = websocket.receive_json()
        if ready.get("type") != "ready":
            raise RuntimeError(f"WebSocket khong san sang: {ready}")
        messages.append(ready)
        for offset in range(0, len(data), WS_CHUNK_BYTES):
            websocket.send_bytes(data[offset:offset + WS_CHUNK_BYTES])
            chunks += 1
        websocket.send_text(json.dumps({"type": "end"}))
        while True:
            event = websocket.receive()
            if event.get("type") == "websocket.close":
                break
            if event.get("bytes") is not None:
                output.extend(event["bytes"])
                continue
            message = json.loads(event["text"])
            messages.append(message)
            if message.get("type") in {"complete", "payload", "error"}:
                break
    return bytes(output), messages, chunks, time.perf_counter() - started


def _websocket_stream(session, tools, client, headers: dict, source: Path, stego: Path, key: bytes,
                      payload: bytes, max_bits: int) -> None:
    data = source.read_bytes()
    session.say(f"Gui source.h264 ({len(data):,} B) thanh chunk {WS_CHUNK_BYTES // 1024} KiB; server pipe vao"
                f" 'zkstego_blind_bits embed-live-auth-stdin {max_bits}' va day NAL da patch nguoc lai ngay.")
    start = {"operation": "embed", "secret_key_b64": _b64(key), "message_b64": _b64(payload)}
    ws_stego, messages, chunks, elapsed = _ws_exchange(client, headers, start, data)
    session.report["timings_seconds"]["ws_embed_stream"] = elapsed
    complete = messages[-1]
    session.say(f"  ready -> {chunks} chunk vao -> {len(ws_stego):,} B ra -> {complete.get('type')} trong {elapsed * 1000:.1f} ms")
    metrics = complete.get("native_metrics") or {}
    if metrics:
        session.say(f"  native: {metrics['patched_idr_segments']}/{metrics['idr_segment_count']} IDR duoc patch,"
                    f" {metrics['bits_embedded']} bit, IDR service p50={metrics['idr_service_p50_ms']:.3f} ms"
                    f" p95={metrics['idr_service_p95_ms']:.3f} ms")
    flow = complete.get("flow_control") or {}
    if flow:
        session.say(f"  flow control: {flow.get('input_chunks')} chunk vao, {flow.get('output_chunks')} chunk ra,"
                    f" stdin buffer max {flow.get('max_native_stdin_buffer_bytes')} B")
    session.check("WebSocket embed complete", complete.get("type") == "complete" and len(ws_stego) > 0)
    ws_path = session.folder / "ws_stego.h264"
    ws_path.write_bytes(ws_stego)
    # Live mode patches NAL by NAL yet must equal the file-mode output: same segments, same schedule.
    session.check("stego WebSocket = stego CLI tung byte (live va file cung giao thuc segment)",
                  ws_stego == stego.read_bytes())
    decode = session.run("decode_ws_stego", ["ffmpeg", "-v", "error", "-xerror", "-nostdin", "-i", ws_path,
                                             "-f", "null", "-"], allow_failure=True)
    session.check("FFmpeg decode stego WebSocket khong loi", decode.returncode == 0)
    result = native_extract(session, tools, ws_path, key, max_bits, "extract_ws_stego")
    session.check("extract-stream-auth(ws_stego) = payload", bytes.fromhex(result.stdout.decode().strip()) == payload)
    start = {"operation": "extract", "secret_key_b64": _b64(key), "maximum_payload_bytes": MAX_PAYLOAD_BYTES}
    _, messages, chunks, elapsed = _ws_exchange(client, headers, start, ws_stego)
    session.report["timings_seconds"]["ws_extract_stream"] = elapsed
    reply = messages[-1]
    session.say(f"  extract qua WebSocket: {chunks} chunk -> {reply.get('type')} trong {elapsed * 1000:.1f} ms"
                " (native dung ngay khi du frame)")
    session.check("WebSocket extract tra dung payload",
                  reply.get("type") == "payload" and base64.b64decode(reply.get("payload_b64", "")) == payload)
