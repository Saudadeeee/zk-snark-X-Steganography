"""Contract tests for the local experimental LNP22 HTTP job API."""

from __future__ import annotations

import http.client
import json
import socket
import sys
import tempfile
import threading
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / "benchmark" / "lnp22_context_probe"
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from http_api import (
    ApiConfig,
    JobManager,
    _LoopbackHttpServer,
    _run_probe_operation,
    create_handler,
    serve,
)
from video_e2e import (
    DEMO_PAYLOAD,
    encode_video_probe_payload,
    make_video_probe_statement,
)

from src.runtest._helpers import run_test, section, summarise


class _InlineExecutor:
    def submit(self, function, *args, **kwargs):
        future = Future()
        future.set_running_or_notify_cancel()
        try:
            future.set_result(function(*args, **kwargs))
        except Exception as error:  # noqa: BLE001 - mirror Future exception capture
            future.set_exception(error)
        return future

    def shutdown(self, **_kwargs):
        return None


def _request(
    server,
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: bytes = b"",
    content_type: str = "application/json",
    decode_json: bool = True,
):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    headers = {"Content-Length": str(len(body))}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if body:
        headers["Content-Type"] = content_type
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    payload = response.read()
    status = response.status
    response_headers = dict(response.getheaders())
    connection.close()
    return status, response_headers, json.loads(payload) if payload and decode_json else payload


def _server_context(
    operation_runner,
    *,
    max_inbox_bytes: int = 1024,
    max_requests_per_minute: int = 120,
    max_jobs_per_minute: int = 1,
    request_timeout_seconds: float = 30.0,
):
    temp = tempfile.TemporaryDirectory(prefix="lnp22-api-test-")
    workspace = Path(temp.name)
    (workspace / "inbox").mkdir()
    (workspace / "output").mkdir()
    (workspace / "reports").mkdir()
    relation = workspace / "relation.json"
    witness = workspace / "witness.json"
    relation.write_text("{}", encoding="utf-8")
    witness.write_text("{}", encoding="utf-8")
    config = ApiConfig(
        workspace=workspace,
        relation_path=relation,
        witness_path=witness,
        trusted_relation_sha256="a" * 64,
        api_token="test-api-token-" + "x" * 32,
        session_database_path=workspace / "sessions.sqlite3",
        session_context_binding=b"s" * 32,
        max_upload_bytes=512,
        max_inbox_bytes=max_inbox_bytes,
        max_jobs_per_minute=max_jobs_per_minute,
        max_requests_per_minute=max_requests_per_minute,
        request_timeout_seconds=request_timeout_seconds,
    )
    manager = JobManager(config, operation_runner=operation_runner, executor=_InlineExecutor())
    server = _LoopbackHttpServer(("127.0.0.1", 0), create_handler(config, manager))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return temp, server, manager, config, thread


def t_http_api_requires_bearer_auth_and_uploads_h264_atomically() -> None:
    def runner(*_args):
        raise AssertionError("no proof job should run")

    temp, server, manager, config, thread = _server_context(runner)
    try:
        assert config.api_token not in repr(config)
        assert str(config.witness_path) not in repr(config)
        status, _headers, body = _request(server, "GET", "/api/v1/health")
        assert status == 401
        assert body["error"]["code"] == "unauthorized"

        status, _headers, body = _request(
            server, "GET", "/api/v1/health", token=config.api_token
        )
        assert status == 200
        assert body["data"]["security_status"].startswith("experimental")

        video = b"\x00\x00\x00\x01\x67test"
        status, _headers, body = _request(
            server,
            "PUT",
            "/api/v1/videos/sample.h264",
            token=config.api_token,
            body=video,
            content_type="video/h264",
        )
        assert status == 201
        assert body["data"]["path"] == "inbox/sample.h264"
        assert (Path(temp.name) / "inbox" / "sample.h264").read_bytes() == video
    finally:
        server.shutdown()
        server.server_close()
        manager.shutdown()
        thread.join(timeout=5)
        temp.cleanup()


def t_http_api_creates_and_reads_video_only_verification_jobs() -> None:
    def runner(operation, arguments, _config):
        assert operation == "verify"
        assert arguments["video"].name == "sample.h264"
        return {
            "valid": True,
            "proof_format": "LNPF-v2",
            "proof_bytes": 33_803,
            "security_status": "experimental LNP22 probe",
        }

    temp, server, manager, config, thread = _server_context(runner)
    try:
        (Path(temp.name) / "inbox" / "sample.h264").write_bytes(b"video")
        request = json.dumps({"operation": "verify", "video": "inbox/sample.h264"}).encode()
        status, headers, created = _request(
            server, "POST", "/api/v1/jobs", token=config.api_token, body=request
        )
        assert status == 202
        job_id = created["data"]["id"]
        assert headers["Location"] == f"/api/v1/jobs/{job_id}"

        status, _headers, job = _request(
            server, "GET", f"/api/v1/jobs/{job_id}", token=config.api_token
        )
        assert status == 200
        assert job["data"]["status"] == "succeeded"
        assert job["data"]["result"]["valid"] is True
        assert job["data"]["result"]["proof_format"] == "LNPF-v2"
        assert "witness" not in json.dumps(job).lower()
    finally:
        server.shutdown()
        server.server_close()
        manager.shutdown()
        thread.join(timeout=5)
        temp.cleanup()


def t_http_api_runs_embed_job_and_downloads_video_and_report() -> None:
    def runner(operation, arguments, _config):
        assert operation == "embed"
        assert arguments["proof_mode"] == "compact"
        arguments["output"].write_bytes(b"stego-h264")
        arguments["report"].write_text('{"verification_result":{"valid":true}}', encoding="utf-8")
        return {
            "proof_mode": "compact",
            "proof_format": "LNPF-v2",
            "output_video_sha256": "b" * 64,
            "proof_bytes": 123,
            "embedded_payload_bytes": 456,
            "carriers_used": 789,
            "strict_h264_decode": True,
            "blind_video_only_extraction": True,
            "proof_verification": True,
            "session_replay_protected": False,
            "security_status": "experimental only",
        }

    temp, server, manager, config, thread = _server_context(runner)
    try:
        (Path(temp.name) / "inbox" / "sample.h264").write_bytes(b"cover")
        status, _headers, grant_response = _request(
            server,
            "POST",
            "/api/v1/zkp/sessions",
            token=config.api_token,
        )
        assert status == 201
        session_challenge = grant_response["data"]["challenge"]
        request = json.dumps(
            {
                "operation": "embed",
                "video": "inbox/sample.h264",
                "output": "output/stego.h264",
                "report": "reports/stego.json",
                "proof_mode": "compact",
                "session_challenge_hex": session_challenge,
            }
        ).encode()
        status, _headers, created = _request(
            server, "POST", "/api/v1/jobs", token=config.api_token, body=request
        )
        assert status == 202
        job = created["data"]
        assert job["status"] == "succeeded"
        assert job["result"]["output"] == "output/stego.h264"
        assert job["result"]["proof_mode"] == "compact"
        assert job["result"]["proof_format"] == "LNPF-v2"
        assert job["result"]["session_replay_protected"] is False

        invalid_request = json.dumps(
            {
                "operation": "embed",
                "video": "inbox/sample.h264",
                "output": "output/other.h264",
                "report": "reports/other.json",
                "proof_mode": "unknown",
                "session_challenge_hex": "c" * 64,
            }
        ).encode()
        status, _headers, invalid_body = _request(
            server,
            "POST",
            "/api/v1/jobs",
            token=config.api_token,
            body=invalid_request,
        )
        assert status == 422
        assert invalid_body["error"]["code"] == "invalid_request"

        status, headers, video = _request(
            server,
            "GET",
            "/api/v1/videos/stego.h264",
            token=config.api_token,
            decode_json=False,
        )
        assert status == 200
        assert headers["Content-Type"].startswith("video/h264")
        assert video == b"stego-h264"

        status, _headers, report = _request(
            server,
            "GET",
            "/api/v1/reports/stego.json",
            token=config.api_token,
            decode_json=False,
        )
        assert status == 200
        assert json.loads(report)["verification_result"]["valid"] is True
    finally:
        server.shutdown()
        server.server_close()
        manager.shutdown()
        thread.join(timeout=5)
        temp.cleanup()


def t_http_api_rejects_workspace_escape_and_hides_worker_errors() -> None:
    def runner(*_args):
        raise RuntimeError("private witness path must not leave the server")

    temp, server, manager, config, thread = _server_context(runner)
    try:
        malformed_operation = json.dumps(
            {"operation": ["verify"], "video": "inbox/sample.h264"}
        ).encode()
        status, _headers, body = _request(
            server, "POST", "/api/v1/jobs", token=config.api_token, body=malformed_operation
        )
        assert status == 422
        assert body["error"]["code"] == "invalid_request"

        bad_request = json.dumps(
            {"operation": "verify", "video": "../../outside.h264"}
        ).encode()
        status, _headers, body = _request(
            server, "POST", "/api/v1/jobs", token=config.api_token, body=bad_request
        )
        assert status == 422
        assert body["error"]["code"] == "invalid_request"

        (Path(temp.name) / "inbox" / "sample.h264").write_bytes(b"video")
        bad_output = json.dumps(
            {
                "operation": "embed",
                "video": "inbox/sample.h264",
                "output": "output/stego video.h264",
                "report": "reports/stego.json",
                "session_challenge_hex": "c" * 64,
            }
        ).encode()
        status, _headers, body = _request(
            server, "POST", "/api/v1/jobs", token=config.api_token, body=bad_output
        )
        assert status == 422
        assert body["error"]["code"] == "invalid_request"

        valid_request = json.dumps(
            {"operation": "verify", "video": "inbox/sample.h264"}
        ).encode()
        status, _headers, created = _request(
            server, "POST", "/api/v1/jobs", token=config.api_token, body=valid_request
        )
        assert status == 202
        status, _headers, job = _request(
            server,
            "GET",
            f"/api/v1/jobs/{created['data']['id']}",
            token=config.api_token,
        )
        serialized = json.dumps(job).lower()
        assert status == 200
        assert job["data"]["status"] == "failed"
        assert job["data"]["error"]["code"] == "job_failed"
        assert "private witness path" not in serialized
    finally:
        server.shutdown()
        server.server_close()
        manager.shutdown()
        thread.join(timeout=5)
        temp.cleanup()


def t_http_api_contracts_are_in_the_full_test_runner() -> None:
    from src.runtest.run_all import PHASES

    assert any(filename == "test_lnp22_http_api.py" for _, _, filename in PHASES)


def t_http_api_issues_sessions_and_requires_the_grant_for_embedding() -> None:
    observed = []

    def runner(operation, arguments, _config):
        observed.append((operation, arguments))
        return {
            "session_replay_protected": False,
            "security_status": "experimental only",
        }

    temp, server, manager, config, thread = _server_context(runner)
    try:
        status, _headers, grant_response = _request(
            server,
            "POST",
            "/api/v1/zkp/sessions",
            token=config.api_token,
        )
        assert status == 201
        grant = grant_response["data"]
        assert len(grant["challenge"]) == 64
        assert grant["expires_at"] > grant["issued_at"]
        assert config.session_store.is_active(
            bytes.fromhex(grant["challenge"]),
            context_binding=config.session_context_binding,
        )

        (Path(temp.name) / "inbox" / "cover.h264").write_bytes(b"cover")
        missing_session = json.dumps(
            {
                "operation": "embed",
                "video": "inbox/cover.h264",
                "output": "output/stego.h264",
                "report": "reports/stego.json",
            }
        ).encode()
        status, _headers, error = _request(
            server,
            "POST",
            "/api/v1/jobs",
            token=config.api_token,
            body=missing_session,
        )
        assert status == 422
        assert error["error"]["code"] == "invalid_request"

        unknown_session = json.dumps(
            {
                "operation": "embed",
                "video": "inbox/cover.h264",
                "output": "output/unknown-session.h264",
                "report": "reports/unknown-session.json",
                "session_challenge_hex": "f" * 64,
            }
        ).encode()
        status, _headers, error = _request(
            server,
            "POST",
            "/api/v1/jobs",
            token=config.api_token,
            body=unknown_session,
        )
        assert status == 409
        assert error["error"]["code"] == "invalid_session"

        with_session = json.dumps(
            {
                "operation": "embed",
                "video": "inbox/cover.h264",
                "output": "output/stego.h264",
                "report": "reports/stego.json",
                "session_challenge_hex": grant["challenge"],
            }
        ).encode()
        status, _headers, created = _request(
            server,
            "POST",
            "/api/v1/jobs",
            token=config.api_token,
            body=with_session,
        )
        assert status == 202
        assert created["data"]["status"] == "succeeded"
        operation, arguments = observed[0]
        assert operation == "embed"
        assert arguments["session_challenge"] == bytes.fromhex(grant["challenge"])
    finally:
        server.shutdown()
        server.server_close()
        manager.shutdown()
        thread.join(timeout=5)
        temp.cleanup()


def t_http_api_verifier_operation_uses_its_pinned_session_store() -> None:
    temp, _server, manager, config, _thread = _server_context(lambda *_args: {})
    try:
        observed = {}

        def fake_verify(*args, **kwargs):
            observed.update(args=args, kwargs=kwargs)
            return {"valid": True, "session_replay_protected": True}

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr("http_api._verify_from_video", fake_verify)
            monkeypatch.setattr(
                "http_api._sync_key_from_environment", lambda: b"k" * 32
            )
            result = _run_probe_operation(
                "verify",
                {"video": Path(temp.name) / "inbox" / "received.h264"},
                config,
            )
        assert result["session_replay_protected"] is True
        assert observed["kwargs"]["session_store"] is config.session_store
        assert (
            observed["kwargs"]["session_context_binding"]
            == config.session_context_binding
        )
    finally:
        manager.shutdown()
        temp.cleanup()


def t_http_api_blind_verification_consumes_the_issued_video_session() -> None:
    temp, server, manager, config, thread = _server_context(
        _run_probe_operation,
        max_jobs_per_minute=5,
    )
    relation_pin = config.trusted_relation_sha256
    try:
        status, _headers, grant_response = _request(
            server,
            "POST",
            "/api/v1/zkp/sessions",
            token=config.api_token,
        )
        assert status == 201
        challenge = bytes.fromhex(grant_response["data"]["challenge"])
        positions_hash = "21" * 32
        canonical_video_hash = "32" * 32
        statement = make_video_probe_statement(
            session_id=challenge,
            payload=DEMO_PAYLOAD,
            canonical_video_sha256=canonical_video_hash,
            positions_hash=positions_hash,
            relation_sha256=relation_pin,
        )
        encoded = encode_video_probe_payload(
            statement,
            b"LNPF\x01" + b"\0" * 6,
            DEMO_PAYLOAD,
        )
        video = Path(temp.name) / "inbox" / "session-bound.h264"
        video.write_bytes(b"synthetic bytes; extractor is instrumented in this test")
        go_calls = []

        def fake_go(*_args, **_kwargs):
            go_calls.append(True)
            return {"valid": True, "verify_ms": 2.5}

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(
                "http_api._sync_key_from_environment", lambda: b"k" * 32
            )
            monkeypatch.setattr(
                "video_e2e.extract_chunked_video_payload",
                lambda *_args, **_kwargs: SimpleNamespace(
                    payload=encoded,
                    positions_hash=positions_hash,
                    canonical_video_sha256=canonical_video_hash,
                    carriers_used=123,
                ),
            )
            monkeypatch.setattr("video_e2e._run_go", fake_go)
            request = json.dumps(
                {"operation": "verify", "video": "inbox/session-bound.h264"}
            ).encode()
            status, _headers, created = _request(
                server,
                "POST",
                "/api/v1/jobs",
                token=config.api_token,
                body=request,
            )
            replay_status, _replay_headers, replay_created = _request(
                server,
                "POST",
                "/api/v1/jobs",
                token=config.api_token,
                body=request,
            )

        assert status == 202
        assert created["data"]["status"] == "succeeded"
        assert created["data"]["result"]["valid"] is True
        assert created["data"]["result"]["session_replay_protected"] is True
        assert replay_status == 202
        assert replay_created["data"]["status"] == "failed"
        assert replay_created["data"]["error"]["code"] == "job_failed"
        assert len(go_calls) == 1
        assert not config.session_store.is_active(
            challenge,
            context_binding=config.session_context_binding,
        )
    finally:
        server.shutdown()
        server.server_close()
        manager.shutdown()
        thread.join(timeout=5)
        temp.cleanup()


def t_http_api_bounds_total_upload_storage_and_job_rate() -> None:
    def runner(operation, _arguments, _config):
        return {"valid": True, "proof_bytes": 1, "security_status": "experimental"}

    temp, server, manager, config, thread = _server_context(
        runner, max_inbox_bytes=10
    )
    try:
        status, _headers, _body = _request(
            server,
            "PUT",
            "/api/v1/videos/first.h264",
            token=config.api_token,
            body=b"12345678",
            content_type="video/h264",
        )
        assert status == 201
        status, _headers, body = _request(
            server,
            "PUT",
            "/api/v1/videos/second.h264",
            token=config.api_token,
            body=b"123",
            content_type="video/h264",
        )
        assert status == 413
        assert body["error"]["code"] == "storage_quota_exceeded"

        first_job = json.dumps(
            {"operation": "verify", "video": "inbox/first.h264"}
        ).encode()
        status, _headers, _body = _request(
            server, "POST", "/api/v1/jobs", token=config.api_token, body=first_job
        )
        assert status == 202
        status, _headers, body = _request(
            server, "POST", "/api/v1/jobs", token=config.api_token, body=first_job
        )
        assert status == 429
        assert body["error"]["code"] == "job_rate_limit"
    finally:
        server.shutdown()
        server.server_close()
        manager.shutdown()
        thread.join(timeout=5)
        temp.cleanup()


def t_http_api_rate_limits_requests_and_refuses_public_bind() -> None:
    def runner(*_args):
        return {"valid": True}

    temp, server, manager, config, thread = _server_context(
        runner, max_requests_per_minute=2
    )
    try:
        for _ in range(2):
            status, _headers, _body = _request(
                server, "GET", "/api/v1/health", token=config.api_token
            )
            assert status == 200
        status, _headers, body = _request(
            server, "GET", "/api/v1/health", token=config.api_token
        )
        assert status == 429
        assert body["error"]["code"] == "rate_limit_exceeded"

        try:
            serve(host="0.0.0.0", port=8765, config=config)
        except ValueError as error:
            assert "loopback" in str(error)
        else:
            raise AssertionError("public network bind was accepted")
    finally:
        server.shutdown()
        server.server_close()
        manager.shutdown()
        thread.join(timeout=5)
        temp.cleanup()


def t_http_api_closes_incomplete_requests_after_configured_timeout() -> None:
    def runner(*_args):
        raise AssertionError("no proof job should run")

    temp, server, manager, config, thread = _server_context(
        runner, request_timeout_seconds=0.15
    )
    client = None
    upload_client = None
    try:
        assert config.request_timeout_seconds == 0.15
        client = socket.create_connection(("127.0.0.1", server.server_port), timeout=3)
        client.settimeout(3)
        client.sendall(b"GET /api/v1/health HTTP/1.1\r\nHost: localhost\r\n")
        response = bytearray()
        while True:
            try:
                chunk = client.recv(1024)
            except (ConnectionResetError, TimeoutError):
                break
            if not chunk:
                break
            response.extend(chunk)
        assert not response, response.decode("latin-1", errors="replace")

        upload_client = socket.create_connection(
            ("127.0.0.1", server.server_port), timeout=3
        )
        upload_client.settimeout(3)
        upload_client.sendall(
            (
                "PUT /api/v1/videos/incomplete.h264 HTTP/1.1\r\n"
                "Host: localhost\r\n"
                f"Authorization: Bearer {config.api_token}\r\n"
                "Content-Type: video/h264\r\n"
                "Content-Length: 1024\r\n\r\n"
            ).encode("ascii")
            + b"partial"
        )
        while True:
            try:
                if not upload_client.recv(1024):
                    break
            except (ConnectionResetError, TimeoutError):
                break
        assert list((Path(temp.name) / "inbox").iterdir()) == []
    finally:
        if client is not None:
            client.close()
        if upload_client is not None:
            upload_client.close()
        server.shutdown()
        server.server_close()
        manager.shutdown()
        thread.join(timeout=5)
        temp.cleanup()


def main() -> None:
    section("LNP22 local HTTP API")
    results = [
        run_test(
            "http_api_requires_bearer_auth_and_uploads_h264_atomically",
            t_http_api_requires_bearer_auth_and_uploads_h264_atomically,
        ),
        run_test(
            "http_api_creates_and_reads_video_only_verification_jobs",
            t_http_api_creates_and_reads_video_only_verification_jobs,
        ),
        run_test(
            "http_api_runs_embed_job_and_downloads_video_and_report",
            t_http_api_runs_embed_job_and_downloads_video_and_report,
        ),
        run_test(
            "http_api_rejects_workspace_escape_and_hides_worker_errors",
            t_http_api_rejects_workspace_escape_and_hides_worker_errors,
        ),
        run_test(
            "http_api_contracts_are_in_the_full_test_runner",
            t_http_api_contracts_are_in_the_full_test_runner,
        ),
        run_test(
            "http_api_issues_sessions_and_requires_the_grant_for_embedding",
            t_http_api_issues_sessions_and_requires_the_grant_for_embedding,
        ),
        run_test(
            "http_api_verifier_operation_uses_its_pinned_session_store",
            t_http_api_verifier_operation_uses_its_pinned_session_store,
        ),
        run_test(
            "http_api_blind_verification_consumes_the_issued_video_session",
            t_http_api_blind_verification_consumes_the_issued_video_session,
        ),
        run_test(
            "http_api_bounds_total_upload_storage_and_job_rate",
            t_http_api_bounds_total_upload_storage_and_job_rate,
        ),
        run_test(
            "http_api_rate_limits_requests_and_refuses_public_bind",
            t_http_api_rate_limits_requests_and_refuses_public_bind,
        ),
        run_test(
            "http_api_closes_incomplete_requests_after_configured_timeout",
            t_http_api_closes_incomplete_requests_after_configured_timeout,
        ),
    ]
    raise SystemExit(summarise(results, "LNP22 local HTTP API"))


if __name__ == "__main__":
    main()
