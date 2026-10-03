"""Contract tests for the authenticated HTTP service and expiring signing keys."""

import asyncio
import base64
import contextlib
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from src.api.app import (
    TERMINAL_JOB_STATUSES,
    ApiSettings,
    AuthFailureLimiter,
    RequestBodyGuard,
    create_app,
)
from src.api.native_handlers import NativePayloadNotAuthenticated, create_native_app
from src.key_policy import (
    KeyCertificate,
    issue_key_certificate,
    verify_manifest_with_certificate,
)
from src.manifest import StegoManifest
from src.runtest._helpers import SKIP, run_test, section, summarise
from src.zk_proof import ZKSnarkBridge, pack, proof_to_bytes

# Tokens shorter than 32 characters are refused at startup.
TOKEN = "phase7-test-token-0123456789abcdef"
BEARER = f"Bearer {TOKEN}"


def _raw_private(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )


def _raw_public(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )


def t_health_is_public_but_jobs_require_bearer_token():
    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_app(ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir)))
        with TestClient(app) as client:
            health = client.get("/health")
            assert health.status_code == 200
            assert health.json()["status"] == "ok"

            denied = client.get("/api/v1/jobs/not-a-job")
            assert denied.status_code == 401


def t_embed_job_returns_only_safe_public_status():
    def embed_handler(**kwargs):
        assert kwargs["message"] == b"contract-message"
        assert kwargs["secret_key"] == b"k" * 32
        Path(kwargs["output_path"]).write_bytes(b"stego")
        return {"valid": True, "bits_embedded": 160, "output_file": "stego.h264"}

    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_app(
            ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir)),
            embed_handler=embed_handler,
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/jobs/embed",
                headers={"Authorization": BEARER},
                data={
                    "message_b64": base64.b64encode(b"contract-message").decode("ascii"),
                    "secret_key_b64": base64.b64encode(b"k" * 32).decode("ascii"),
                },
                files={"video": ("cover.h264", b"\x00\x00\x00\x01cover", "video/h264")},
            )
            assert response.status_code == 202, response.text
            job_id = response.json()["job_id"]

            for _ in range(30):
                status = client.get(
                    f"/api/v1/jobs/{job_id}",
                    headers={"Authorization": BEARER},
                )
                assert status.status_code == 200
                body = status.json()
                if body["status"] in TERMINAL_JOB_STATUSES:
                    break
                time.sleep(0.02)
            assert body["status"] == "succeeded", body
            assert body["result"]["bits_embedded"] == 160
            assert "secret_key" not in repr(body).lower()
            assert "contract-message" not in repr(body)


def _verify_request(stego: bytes = b"\x00\x00\x00\x01stego", key: bytes = b"v" * 32) -> dict:
    return {
        "headers": {"Authorization": BEARER},
        "data": {"secret_key_b64": base64.b64encode(key).decode("ascii"), "maximum_payload_bytes": "512"},
        "files": {"stego_video": ("stego.h264", stego, "video/h264")},
    }


def t_verify_job_forwards_single_stego_and_filters_result():
    def verify_handler(**kwargs):
        assert set(kwargs) == {"stego_video_path", "secret_key", "maximum_payload_bytes"}, kwargs
        assert Path(kwargs["stego_video_path"]).read_bytes().endswith(b"stego")
        assert kwargs["secret_key"] == b"v" * 32
        assert kwargs["maximum_payload_bytes"] == 512
        return {"valid": True, "message_b64": "cHJvdmVu", "payload_bytes": 139, "secret": "x"}

    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_app(
            ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir)),
            verify_handler=verify_handler,
        )
        with TestClient(app) as client:
            response = client.post("/api/v1/jobs/verify", **_verify_request())
            assert response.status_code == 202, response.text
            job_id = response.json()["job_id"]
            body = _wait_job(client, job_id)
            assert body["status"] == "succeeded", body
            assert body["result"] == {"valid": True, "message_b64": "cHJvdmVu", "payload_bytes": 139}
            assert not (Path(temp_dir) / "files" / job_id / "stego.h264").exists()


def t_unconfigured_handlers_answer_501_without_creating_jobs():
    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_app(ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir)))
        with TestClient(app) as client:
            assert client.post("/api/v1/jobs/embed", **_embed_request()).status_code == 501
            assert client.post("/api/v1/jobs/verify", **_verify_request()).status_code == 501
            extract = _verify_request()
            assert client.post("/api/v1/jobs/extract", **extract).status_code == 501
            assert list((Path(temp_dir) / "jobs").glob("*.json")) == []


def t_http_job_queue_is_bounded_and_rejects_overload():
    started = threading.Event()
    release = threading.Event()

    def slow_embed(**kwargs):
        started.set()
        assert release.wait(timeout=5)
        Path(kwargs["output_path"]).write_bytes(b"stego")
        return {"valid": True, "bits_embedded": 8, "capacity_bits": 8}

    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_app(
            ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir), max_workers=1, max_queued_jobs=1),
            embed_handler=slow_embed,
        )
        with TestClient(app) as client:
            request = {
                "headers": {"Authorization": BEARER},
                "data": {
                    "message_b64": base64.b64encode(b"x").decode("ascii"),
                    "secret_key_b64": base64.b64encode(b"k" * 32).decode("ascii"),
                },
                "files": {"video": ("cover.h264", b"\x00\x00\x00\x01cover", "video/h264")},
            }
            first = client.post("/api/v1/jobs/embed", **request)
            assert first.status_code == 202, first.text
            assert started.wait(timeout=2)

            second = client.post("/api/v1/jobs/embed", **request)
            assert second.status_code == 202, second.text
            third = client.post("/api/v1/jobs/embed", **request)
            assert third.status_code == 503, third.text
            assert third.json()["detail"] == "job capacity reached; retry later"
            assert len(list((Path(temp_dir) / "jobs").glob("*.json"))) == 2
            release.set()

            accepted_ids = (first.json()["job_id"], second.json()["job_id"])
            for job_id in accepted_ids:
                for _ in range(100):
                    body = client.get(f"/api/v1/jobs/{job_id}", headers=request["headers"]).json()
                    if body["status"] in TERMINAL_JOB_STATUSES:
                        break
                    time.sleep(0.01)
                assert body["status"] == "succeeded", body

            recovered = client.post("/api/v1/jobs/embed", **request)
            assert recovered.status_code == 202, recovered.text
            recovered_id = recovered.json()["job_id"]
            for _ in range(100):
                body = client.get(f"/api/v1/jobs/{recovered_id}", headers=request["headers"]).json()
                if body["status"] in TERMINAL_JOB_STATUSES:
                    break
                time.sleep(0.01)
            assert body["status"] == "succeeded", body


def t_failed_upload_removes_orphan_job_and_releases_capacity():
    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_app(
            ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir), max_upload_bytes=1, max_queued_jobs=0),
            embed_handler=lambda **kwargs: {"valid": True, "bits_embedded": 8, "capacity_bits": 8},
        )
        with TestClient(app) as client:
            request = {
                "headers": {"Authorization": BEARER},
                "data": {
                    "message_b64": base64.b64encode(b"x").decode("ascii"),
                    "secret_key_b64": base64.b64encode(b"k" * 32).decode("ascii"),
                },
                "files": {"video": ("cover.h264", b"too-large", "video/h264")},
            }
            failed = client.post("/api/v1/jobs/embed", **request)
            assert failed.status_code == 413, failed.text
            assert list((Path(temp_dir) / "jobs").glob("*.json")) == []
            assert list((Path(temp_dir) / "files").iterdir()) == []

            request["files"] = {"video": ("cover.h264", b"x", "video/h264")}
            accepted = client.post("/api/v1/jobs/embed", **request)
            assert accepted.status_code == 202, accepted.text


def t_http_body_guard_rejects_oversized_multipart_before_job_admission():
    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_app(
            ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir), max_upload_bytes=512 * 1024),
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/jobs/embed",
                headers={"Authorization": BEARER},
                data={
                    "message_b64": base64.b64encode(b"x").decode("ascii"),
                    "secret_key_b64": base64.b64encode(b"k" * 32).decode("ascii"),
                },
                files={"video": ("oversized.h264", b"x" * 1_600_000, "video/h264")},
            )
            assert response.status_code == 413, response.text
            assert list((Path(temp_dir) / "jobs").glob("*.json")) == []


def t_http_body_guard_times_out_slow_request_body():
    async def exercise():
        emitted = []
        pending = asyncio.Event()

        async def inner(scope, receive, send):
            await receive()

        async def receive():
            await pending.wait()
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            emitted.append(message)

        guard = RequestBodyGuard(
            inner,
            maximum_bytes={"/api/v1/jobs/extract": 1024},
            timeout_seconds=0.02,
        )
        await guard(
            {"type": "http", "method": "POST", "path": "/api/v1/jobs/extract", "headers": []},
            receive,
            send,
        )
        return emitted

    emitted = asyncio.run(exercise())
    assert emitted[0]["status"] == 408


def t_restart_recovery_fails_stale_job_and_removes_uploaded_media():
    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_app(ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir)))
        with TestClient(app):
            record = app.state.store.create("extract")
            job_dir = Path(temp_dir) / "files" / record["job_id"]
            job_dir.mkdir(parents=True)
            (job_dir / "stego.h264").write_bytes(b"uploaded video")
            (job_dir / "payload.bin").write_bytes(b"partial plaintext")
            app.state.store.update(record["job_id"], status="running")

            app.state.recover_interrupted_jobs()
            recovered = app.state.store.get(record["job_id"])
            assert recovered["status"] == "failed", recovered
            assert recovered["error"] == "job interrupted by service restart"
            assert list(job_dir.iterdir()) == []

            no_media_record = app.state.store.create("embed")
            app.state.store.update(no_media_record["job_id"], status="queued")
            assert not (Path(temp_dir) / "files" / no_media_record["job_id"]).exists()
            app.state.recover_interrupted_jobs()
            recovered_without_media = app.state.store.get(no_media_record["job_id"])
            assert recovered_without_media["status"] == "failed", recovered_without_media

            sentinel = Path(temp_dir) / "cover.h264"
            sentinel.write_bytes(b"outside job directory")
            malformed_id = Path(temp_dir) / "jobs" / "...json"
            malformed_id.write_text(
                json.dumps({"job_id": "..", "operation": "embed", "status": "running"}),
                encoding="utf-8",
            )

            malformed_operation = app.state.store.create("embed")
            malformed_dir = Path(temp_dir) / "files" / malformed_operation["job_id"]
            malformed_dir.mkdir(parents=True)
            keep_file = malformed_dir / "cover.h264"
            keep_file.write_bytes(b"do not touch invalid operation")
            app.state.store.update(
                malformed_operation["job_id"], operation={"invalid": True}, status="running",
            )
            app.state.recover_interrupted_jobs()
            assert sentinel.read_bytes() == b"outside job directory"
            assert keep_file.read_bytes() == b"do not touch invalid operation"


def t_api_work_dir_rejects_a_second_live_instance():
    with tempfile.TemporaryDirectory() as temp_dir:
        settings = ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir))
        first_app = create_app(settings)
        second_app = create_app(settings)
        with TestClient(first_app) as first_client:
            assert first_client.get("/health").status_code == 200
            try:
                with TestClient(second_app):
                    raise AssertionError("second API instance unexpectedly acquired the work-dir lease")
            except RuntimeError as exc:
                assert "another API process" in str(exc)

        with TestClient(second_app) as second_client:
            assert second_client.get("/health").status_code == 200


def t_expiring_certificate_rejects_key_after_deadline():
    issuer = Ed25519PrivateKey.generate()
    signer = Ed25519PrivateKey.generate()
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    certificate = issue_key_certificate(
        subject_public_key=_raw_public(signer),
        issuer_private_key=_raw_private(issuer),
        key_id="signer-2029",
        not_before=now - timedelta(days=1),
        expires_at=now + timedelta(hours=1),
    )
    manifest = StegoManifest()
    manifest.sign(_raw_private(signer), signer_id="signer-2029")

    assert verify_manifest_with_certificate(manifest, certificate, _raw_public(issuer), now=now)
    assert not verify_manifest_with_certificate(
        manifest,
        certificate,
        _raw_public(issuer),
        now=now + timedelta(hours=2),
    )


def t_certificate_serialization_is_canonical_and_tamper_evident():
    issuer = Ed25519PrivateKey.generate()
    signer = Ed25519PrivateKey.generate()
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    certificate = issue_key_certificate(
        subject_public_key=_raw_public(signer),
        issuer_private_key=_raw_private(issuer),
        key_id="signer-2029",
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=1),
    )
    loaded = KeyCertificate.from_json(certificate.to_json())
    assert loaded.verify(_raw_public(issuer), now=now)
    loaded.key_id = "substituted"
    assert not loaded.verify(_raw_public(issuer), now=now)


def t_unauthenticated_upload_rejected_before_body_is_read():
    async def exercise(headers, root_path=""):
        emitted, receive_calls, inner_calls = [], [], []

        async def inner(scope, receive, send):
            inner_calls.append(scope["path"])

        async def receive():
            receive_calls.append(1)
            return {"type": "http.request", "body": b"x" * 1024, "more_body": True}

        async def send(message):
            emitted.append(message)

        guard = RequestBodyGuard(
            inner, maximum_bytes={"/api/v1/jobs/embed": 200 * 1024 * 1024}, timeout_seconds=5.0,
            api_token=TOKEN,
        )
        # uvicorn --root-path prefixes scope["path"] with root_path; the guard must still apply.
        await guard(
            {"type": "http", "method": "POST", "path": root_path + "/api/v1/jobs/embed", "root_path": root_path,
             "headers": [(b"content-length", b"150000000"), *headers]},
            receive, send,
        )
        return emitted, receive_calls, inner_calls

    for root_path in ("", "/gateway"):
        for headers in ([], [(b"authorization", b"Bearer wrong")], [(b"authorization", "Bearer töken".encode("latin-1"))]):
            emitted, receive_calls, inner_calls = asyncio.run(exercise(headers, root_path))
            assert emitted[0]["status"] == 401, (root_path, emitted)
            assert receive_calls == [] and inner_calls == [], (root_path, receive_calls, inner_calls)

    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_app(ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir)))
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/jobs/embed",
                data={"message_b64": "eA==", "secret_key_b64": base64.b64encode(b"k" * 32).decode("ascii")},
                files={"video": ("cover.h264", b"\x00" * (2 * 1024 * 1024), "video/h264")},
            )
            assert response.status_code == 401, response.text
            assert response.headers.get("www-authenticate") == "Bearer"
            assert list((Path(temp_dir) / "jobs").glob("*.json")) == []


def t_non_ascii_authorization_header_is_401_not_500():
    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_app(ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir)))
        with TestClient(app, raise_server_exceptions=False) as client:
            for value in ("Bearer töken".encode("latin-1"), b"Bearer \xff\xfe"):
                response = client.get("/api/v1/jobs/" + "a" * 24, headers={"Authorization": value})
                assert response.status_code == 401, response.text
    with tempfile.TemporaryDirectory() as temp_dir:
        unicode_token = "töken-" + "u" * 26
        unicode_app = create_app(ApiSettings(api_token=unicode_token, work_dir=Path(temp_dir)))
        with TestClient(unicode_app) as client:
            ok = client.get("/api/v1/jobs/" + "a" * 24,
                            headers={"Authorization": f"Bearer {unicode_token}".encode("utf-8")})
            assert ok.status_code == 404, ok.text  # authenticated in both layers; job simply absent
            bad = client.get("/api/v1/jobs/" + "a" * 24,
                             headers={"Authorization": f"Bearer {unicode_token.replace('ö', 'ä')}".encode("utf-8")})
            assert bad.status_code == 401, bad.text


def t_invalid_job_id_is_404_without_filesystem_access():
    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_app(ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir)))
        headers = {"Authorization": BEARER}
        sentinel = Path(temp_dir) / "secret.json"
        sentinel.write_text(json.dumps({"job_id": "..\\secret", "status": "succeeded"}), encoding="utf-8")
        with TestClient(app) as client:
            for job_id in ("not-a-job", "..%5Csecret", "a" * 25, "a" * 23 + "!"):
                assert client.get(f"/api/v1/jobs/{job_id}", headers=headers).status_code == 404
                assert client.get(f"/api/v1/jobs/{job_id}/artifact", headers=headers).status_code == 404
            assert app.state.store.get("../secret") is None


def t_concurrent_upload_cap_returns_503():
    async def exercise():
        release = asyncio.Event()
        statuses = []

        async def inner(scope, receive, send):
            await release.wait()
            await send({"type": "http.response.start", "status": 202, "headers": []})
            await send({"type": "http.response.body", "body": b"", "more_body": False})

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        def sender():
            async def send(message):
                if message["type"] == "http.response.start":
                    statuses.append(message["status"])
            return send

        guard = RequestBodyGuard(
            inner, maximum_bytes={"/api/v1/jobs/extract": 1024}, timeout_seconds=5.0,
            api_token=TOKEN, max_concurrent_uploads=1,
        )
        scope = {"type": "http", "method": "POST", "path": "/api/v1/jobs/extract",
                 "headers": [(b"authorization", BEARER.encode("ascii"))]}
        first = asyncio.create_task(guard(scope, receive, sender()))
        await asyncio.sleep(0.01)
        await guard(scope, receive, sender())
        release.set()
        await first
        await guard(scope, receive, sender())
        return statuses

    assert asyncio.run(exercise()) == [503, 202, 202]


def t_retention_purges_old_terminal_jobs_but_keeps_active_ones():
    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_app(ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir), job_retention_seconds=60.0))
        store = app.state.store
        with TestClient(app) as client:
            done = store.create("embed")
            store.update(done["job_id"], status="succeeded")
            (Path(temp_dir) / "files" / done["job_id"]).mkdir(parents=True)
            busy = store.create("embed")
            store.update(busy["job_id"], status="running")
            holding = store.create("extract")
            store.update(holding["job_id"], status="failed")
            holding_dir = Path(temp_dir) / "files" / holding["job_id"]
            holding_dir.mkdir(parents=True)
            (holding_dir / "payload.bin").write_bytes(b"not yet swept")
            fresh = store.create("verify")
            store.update(fresh["job_id"], status="failed")

            assert app.state.purge_expired_jobs() == 0
            # Past retention (60 s) but inside the artifact TTL (600 s): a live artifact is never removed.
            assert app.state.purge_expired_jobs(now=time.time() + 120.0) == 0
            assert (holding_dir / "payload.bin").exists()
            # Past both: every terminal job goes with its whole directory; the active job stays.
            purged = app.state.purge_expired_jobs(now=time.time() + 1200.0)
            assert purged == 3, purged  # "done", "holding" and "fresh"; "busy" is active
            headers = {"Authorization": BEARER}
            assert client.get(f"/api/v1/jobs/{done['job_id']}", headers=headers).status_code == 404
            for job in (done, holding):
                assert not (Path(temp_dir) / "files" / job["job_id"]).exists()
            assert not (Path(temp_dir) / "jobs" / f"{done['job_id']}.json").exists()
            assert store.get(busy["job_id"])["status"] == "running"


def t_api_docs_are_opt_in():
    with tempfile.TemporaryDirectory() as temp_dir:
        with TestClient(create_app(ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir)))) as client:
            assert client.get("/docs").status_code == 404
            assert client.get("/openapi.json").status_code == 404
    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_app(ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir), enable_docs=True))
        with TestClient(app) as client:
            assert client.get("/docs").status_code == 200
            assert client.get("/openapi.json").status_code == 200


@contextlib.contextmanager
def _environment(**values):
    saved = {name: os.environ.get(name) for name in values}
    try:
        for name, value in values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _wait_job(client, job_id: str) -> dict:
    for _ in range(200):
        body = client.get(f"/api/v1/jobs/{job_id}", headers={"Authorization": BEARER}).json()
        if body["status"] in TERMINAL_JOB_STATUSES:
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach a terminal status")


def _embed_request(video: bytes = b"\x00\x00\x00\x01cover") -> dict:
    return {
        "headers": {"Authorization": BEARER},
        "data": {
            "message_b64": base64.b64encode(b"x").decode("ascii"),
            "secret_key_b64": base64.b64encode(b"k" * 32).decode("ascii"),
        },
        "files": {"video": ("cover.h264", video, "video/h264")},
    }


def t_verify_job_with_invalid_proof_is_rejected_not_succeeded():
    def verify_handler(**kwargs):
        # A rejected result must never leak a message, even if a handler returns one.
        return {"valid": False, "reason": "proof_invalid", "message_b64": "bGVhaw=="}

    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_app(
            ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir), job_retention_seconds=60.0),
            verify_handler=verify_handler,
        )
        with TestClient(app) as client:
            response = client.post("/api/v1/jobs/verify", **_verify_request())
            assert response.status_code == 202, response.text
            job_id = response.json()["job_id"]
            body = _wait_job(client, job_id)
            assert body["status"] == "rejected", body
            assert body["result"] == {"valid": False, "reason": "proof_invalid"}, body
            assert "rejected" in TERMINAL_JOB_STATUSES
            artifact = client.get(f"/api/v1/jobs/{job_id}/artifact", headers={"Authorization": BEARER})
            assert artifact.status_code == 404
            # Terminal for retention too: past retention and artifact TTL the record and directory go.
            assert app.state.purge_expired_jobs(now=time.time() + 1200.0) == 1
            assert app.state.store.get(job_id) is None
            assert not (Path(temp_dir) / "files" / job_id).exists()


def t_short_api_token_is_refused_at_startup():
    with tempfile.TemporaryDirectory() as temp_dir:
        for short in ("", "t", "x" * 31):
            try:
                create_app(ApiSettings(api_token=short, work_dir=Path(temp_dir)))
            except ValueError as exc:
                assert "at least 32 characters" in str(exc)
            else:
                raise AssertionError(f"token of {len(short)} characters was accepted")
        create_app(ApiSettings(api_token="x" * 32, work_dir=Path(temp_dir)))
    with _environment(ZK_STEGO_API_TOKEN="short-token"):
        try:
            ApiSettings.from_environment()
        except RuntimeError as exc:
            assert "ZK_STEGO_API_TOKEN" in str(exc) and "32" in str(exc)
            assert "short-token" not in str(exc)
        else:
            raise AssertionError("short ZK_STEGO_API_TOKEN was accepted")


def t_upload_timeout_is_configurable_from_environment():
    with _environment(ZK_STEGO_API_TOKEN=TOKEN, ZK_STEGO_API_UPLOAD_TIMEOUT_SECONDS=None):
        assert ApiSettings.from_environment().upload_timeout_seconds == 120.0
    with _environment(ZK_STEGO_API_TOKEN=TOKEN, ZK_STEGO_API_UPLOAD_TIMEOUT_SECONDS="7.5"):
        assert ApiSettings.from_environment().upload_timeout_seconds == 7.5
    for invalid in ("abc", "0", "0.5", "-3", "nan", "inf", ""):
        with _environment(ZK_STEGO_API_TOKEN=TOKEN, ZK_STEGO_API_UPLOAD_TIMEOUT_SECONDS=invalid):
            try:
                ApiSettings.from_environment()
            except ValueError as exc:
                assert "ZK_STEGO_API_UPLOAD_TIMEOUT_SECONDS" in str(exc)
            else:
                raise AssertionError(f"invalid upload timeout {invalid!r} was accepted")


def t_repeated_auth_failures_are_throttled_with_429():
    now = [1000.0]
    limiter = AuthFailureLimiter(max_failures=3, window_seconds=60.0, clock=lambda: now[0])

    async def exercise(client_ip: str, authorization: bytes):
        emitted, inner_calls = [], []

        async def inner(scope, receive, send):
            inner_calls.append(1)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"", "more_body": False})

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            emitted.append(message)

        guard = RequestBodyGuard(
            inner, maximum_bytes={}, timeout_seconds=5.0, api_token=TOKEN, auth_limiter=limiter,
        )
        await guard(
            {"type": "http", "method": "GET", "path": "/api/v1/jobs/" + "a" * 24,
             "client": (client_ip, 50000), "headers": [(b"authorization", authorization)]},
            receive, send,
        )
        return emitted[0], inner_calls

    good, bad = BEARER.encode("ascii"), b"Bearer wrong-secret-guess"
    captured: list[logging.LogRecord] = []
    handler = logging.Handler(level=logging.WARNING)
    handler.emit = captured.append
    api_logger = logging.getLogger("src.api.app")
    api_logger.addHandler(handler)
    try:
        for _ in range(3):
            start, inner_calls = asyncio.run(exercise("10.0.0.1", bad))
            assert start["status"] == 401 and inner_calls == [], start
    finally:
        api_logger.removeHandler(handler)
    assert len(captured) == 3 and all(record.levelno == logging.WARNING for record in captured)
    assert all("wrong-secret-guess" not in record.getMessage() for record in captured)
    assert all("10.0.0.1" in record.getMessage() for record in captured)

    for authorization in (bad, good):  # Throttled regardless of the token offered.
        start, inner_calls = asyncio.run(exercise("10.0.0.1", authorization))
        assert start["status"] == 429 and inner_calls == [], start
        assert dict(start["headers"])[b"retry-after"] == b"60", start
    start, inner_calls = asyncio.run(exercise("10.0.0.2", good))  # Other clients are unaffected.
    assert start["status"] == 200 and inner_calls == [1], start
    now[0] += 30.0
    assert dict(asyncio.run(exercise("10.0.0.1", good))[0]["headers"])[b"retry-after"] == b"30"
    now[0] += 31.0  # Window over: the client may authenticate again.
    start, inner_calls = asyncio.run(exercise("10.0.0.1", good))
    assert start["status"] == 200 and inner_calls == [1], start

    # Memory stays bounded: the oldest tracked client is evicted first.
    bounded = AuthFailureLimiter(max_failures=1, window_seconds=60.0, max_tracked_clients=2)
    for client_ip in ("a", "b", "c"):
        bounded.record_failure(client_ip)
    assert bounded.retry_after("a") == 0
    assert bounded.retry_after("b") > 0 and bounded.retry_after("c") > 0

    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_app(ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir), auth_failure_limit=2))
        with TestClient(app) as client:
            path = "/api/v1/jobs/" + "a" * 24
            for _ in range(2):
                assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
            throttled = client.get(path, headers={"Authorization": BEARER})
            assert throttled.status_code == 429, throttled.text
            assert int(throttled.headers["retry-after"]) >= 1
            assert client.get("/health").status_code == 200


def t_running_status_write_failure_fails_job_and_releases_capacity():
    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_app(
            ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir), max_workers=1, max_queued_jobs=0),
            embed_handler=lambda **kwargs: {"valid": True, "bits_embedded": 8, "capacity_bits": 8},
        )
        store = app.state.store
        original_update = store.update
        failures = {"remaining": 1}

        def flaky_update(job_id, **changes):
            if changes.get("status") == "running" and failures["remaining"]:
                failures["remaining"] -= 1
                raise OSError("No space left on device")
            original_update(job_id, **changes)

        store.update = flaky_update
        with TestClient(app) as client:
            first = client.post("/api/v1/jobs/embed", **_embed_request())
            assert first.status_code == 202, first.text
            body = _wait_job(client, first.json()["job_id"])
            assert body["status"] == "failed" and body["error"] == "embed could not be started", body
            assert not (Path(temp_dir) / "files" / first.json()["job_id"] / "cover.h264").exists()
            second = client.post("/api/v1/jobs/embed", **_embed_request())
            assert second.status_code == 202, second.text  # The capacity slot was released.
            assert _wait_job(client, second.json()["job_id"])["status"] == "succeeded"


# A well-formed (on-curve) Groth16 proof: G1/G2 generators. It parses, but proves nothing,
# so the deterministic tests below decide validity with an injected verifier.
_G2_GENERATOR = [
    ["10857046999023057135944570762232829481370756359578518086990519993285655852781",
     "11559732032986387107991004021392285783925812861821192530917403151452391805634"],
    ["8495653923123431417604973247489272438418190587263600148770280649306958101930",
     "4082367875863433681332203403145435568316851327593401208105741076214120093531"],
    ["1", "0"],
]
_WELL_FORMED_PROOF = {
    "pi_a": ["1", "2", "1"], "pi_b": _G2_GENERATOR, "pi_c": ["1", "2", "1"],
    "protocol": "groth16", "curve": "bn128",
}


def _native_verify_app(temp_dir: str, extractor, verifier):
    # The injected extractor replaces the native CLI call; any existing file satisfies cli_path.
    return create_native_app(
        ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir)),
        cli_path=sys.executable, payload_extractor=extractor, proof_verifier=verifier,
    )


def _run_verify_job(app, key: bytes = b"v" * 32) -> dict:
    with TestClient(app) as client:
        response = client.post("/api/v1/jobs/verify", **_verify_request(key=key))
        assert response.status_code == 202, response.text
        return _wait_job(client, response.json()["job_id"])


def t_native_verify_job_succeeds_only_for_verified_proof():
    key, message = b"v" * 32, b"proven-message"
    blob = pack(message, proof_to_bytes(_WELL_FORMED_PROOF))
    calls = []

    def extractor(stego_video_path, secret_key, maximum_payload_bytes):
        assert Path(stego_video_path).read_bytes().endswith(b"stego")
        assert secret_key == key and maximum_payload_bytes == 512
        return blob

    def verifier(proof, proven_message, secret_key):
        calls.append((proof, proven_message, secret_key))
        return proven_message == message and secret_key == key

    with tempfile.TemporaryDirectory() as temp_dir:
        body = _run_verify_job(_native_verify_app(temp_dir, extractor, verifier), key)
    assert body["status"] == "succeeded", body
    assert body["result"] == {
        "valid": True, "message_b64": base64.b64encode(message).decode("ascii"), "payload_bytes": len(blob),
    }, body
    assert calls == [(_WELL_FORMED_PROOF, message, key)]

    with tempfile.TemporaryDirectory() as temp_dir:  # The verifier says no: rejected, no message.
        body = _run_verify_job(_native_verify_app(temp_dir, extractor, lambda *_: False), key)
    assert body["status"] == "rejected" and body["result"] == {"valid": False, "reason": "proof_invalid"}, body


def t_native_verify_job_rejects_malformed_or_absent_proof_and_fails_on_infrastructure():
    proof_bytes = proof_to_bytes(_WELL_FORMED_PROOF)
    off_curve = bytes([0xFF] * 32) + proof_bytes[32:]

    def rejected_extract(*_):
        raise NativePayloadNotAuthenticated("native CAVLC operation failed")

    def broken_extract(*_):
        raise RuntimeError("native CAVLC operation timed out")

    def must_not_verify(*_):
        raise AssertionError("verifier must not run for a malformed payload")

    cases = (
        ("payload_not_authenticated", rejected_extract),
        ("malformed_proof_payload", lambda *_: b"\x00\x00\x00\x05short"),      # truncated blob
        ("malformed_proof_payload", lambda *_: pack(b"msg", off_curve)),       # proof not on curve
        ("malformed_proof_payload", lambda *_: pack(b"msg", proof_bytes) + b"trailing"),
        ("malformed_proof_payload", lambda *_: pack(b"", proof_bytes)),        # empty message
    )
    for reason, extractor in cases:
        with tempfile.TemporaryDirectory() as temp_dir:
            body = _run_verify_job(_native_verify_app(temp_dir, extractor, must_not_verify))
        assert body["status"] == "rejected", (reason, body)
        assert body["result"] == {"valid": False, "reason": reason}, (reason, body)

    with tempfile.TemporaryDirectory() as temp_dir:
        body = _run_verify_job(_native_verify_app(temp_dir, broken_extract, must_not_verify))
    assert body["status"] == "failed" and body["error"] == "verify failed: RuntimeError", body

    def verifier_crashes(*_):
        raise RuntimeError("Node.js is required")

    with tempfile.TemporaryDirectory() as temp_dir:
        body = _run_verify_job(_native_verify_app(
            temp_dir, lambda *_: pack(b"msg", proof_bytes), verifier_crashes,
        ))
    assert body["status"] == "failed", body
    assert "result" not in body


def t_native_verify_job_with_real_groth16_proof():
    circuits = Path(__file__).resolve().parents[2] / "circuits"
    if shutil.which("node") is None or not (circuits / "build" / "verification_key.json").is_file():
        SKIP("native_verify_job_with_real_groth16_proof", "node or circuits/build missing")
    key, message = bytes(range(32)), b"real-groth16-verify-job"
    bridge = ZKSnarkBridge(str(circuits))
    proof, _public = bridge.generate_proof_for_payload(message, key)
    good = pack(message, proof_to_bytes(proof))
    forged = pack(b"real-groth16-verify-jo!", proof_to_bytes(proof))  # Same proof, other message.

    for blob, expected in ((good, "succeeded"), (forged, "rejected")):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_native_app(
                ApiSettings(api_token=TOKEN, work_dir=Path(temp_dir), circuits_dir=circuits),
                cli_path=sys.executable, payload_extractor=lambda *_, data=blob: data,
            )
            body = _run_verify_job(app, key)
        assert body["status"] == expected, body
        if expected == "succeeded":
            assert base64.b64decode(body["result"]["message_b64"]) == message
        else:
            assert body["result"] == {"valid": False, "reason": "proof_invalid"}, body


def main():
    section("Service API and expiring keys")
    results = [
        run_test("health_is_public_but_jobs_require_bearer_token", t_health_is_public_but_jobs_require_bearer_token),
        run_test("embed_job_returns_only_safe_public_status", t_embed_job_returns_only_safe_public_status),
        run_test("verify_job_forwards_single_stego_and_filters_result", t_verify_job_forwards_single_stego_and_filters_result),
        run_test("unconfigured_handlers_answer_501_without_creating_jobs", t_unconfigured_handlers_answer_501_without_creating_jobs),
        run_test("http_job_queue_is_bounded_and_rejects_overload", t_http_job_queue_is_bounded_and_rejects_overload),
        run_test("failed_upload_removes_orphan_job_and_releases_capacity", t_failed_upload_removes_orphan_job_and_releases_capacity),
        run_test("http_body_guard_rejects_oversized_multipart_before_job_admission", t_http_body_guard_rejects_oversized_multipart_before_job_admission),
        run_test("http_body_guard_times_out_slow_request_body", t_http_body_guard_times_out_slow_request_body),
        run_test("restart_recovery_fails_stale_job_and_removes_uploaded_media", t_restart_recovery_fails_stale_job_and_removes_uploaded_media),
        run_test("api_work_dir_rejects_a_second_live_instance", t_api_work_dir_rejects_a_second_live_instance),
        run_test("expiring_certificate_rejects_key_after_deadline", t_expiring_certificate_rejects_key_after_deadline),
        run_test("certificate_serialization_is_canonical_and_tamper_evident", t_certificate_serialization_is_canonical_and_tamper_evident),
        run_test("unauthenticated_upload_rejected_before_body_is_read", t_unauthenticated_upload_rejected_before_body_is_read),
        run_test("non_ascii_authorization_header_is_401_not_500", t_non_ascii_authorization_header_is_401_not_500),
        run_test("invalid_job_id_is_404_without_filesystem_access", t_invalid_job_id_is_404_without_filesystem_access),
        run_test("concurrent_upload_cap_returns_503", t_concurrent_upload_cap_returns_503),
        run_test("retention_purges_old_terminal_jobs_but_keeps_active_ones", t_retention_purges_old_terminal_jobs_but_keeps_active_ones),
        run_test("api_docs_are_opt_in", t_api_docs_are_opt_in),
        run_test("verify_job_with_invalid_proof_is_rejected_not_succeeded", t_verify_job_with_invalid_proof_is_rejected_not_succeeded),
        run_test("short_api_token_is_refused_at_startup", t_short_api_token_is_refused_at_startup),
        run_test("upload_timeout_is_configurable_from_environment", t_upload_timeout_is_configurable_from_environment),
        run_test("repeated_auth_failures_are_throttled_with_429", t_repeated_auth_failures_are_throttled_with_429),
        run_test("running_status_write_failure_fails_job_and_releases_capacity", t_running_status_write_failure_fails_job_and_releases_capacity),
        run_test("native_verify_job_succeeds_only_for_verified_proof", t_native_verify_job_succeeds_only_for_verified_proof),
        run_test("native_verify_job_rejects_malformed_or_absent_proof_and_fails_on_infrastructure",
                 t_native_verify_job_rejects_malformed_or_absent_proof_and_fails_on_infrastructure),
        run_test("native_verify_job_with_real_groth16_proof", t_native_verify_job_with_real_groth16_proof),
    ]
    sys.exit(summarise(results, "Service API"))


if __name__ == "__main__":
    main()
