"""Contract tests for the authenticated HTTP service and expiring signing keys."""

import base64
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from src.api.app import ApiSettings, create_app
from src.key_policy import KeyCertificate, issue_key_certificate, verify_manifest_with_certificate
from src.manifest import StegoManifest
from src.runtest._helpers import run_test, section, summarise


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
        app = create_app(ApiSettings(api_token="test-token", work_dir=Path(temp_dir)))
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
            ApiSettings(api_token="test-token", work_dir=Path(temp_dir)),
            embed_handler=embed_handler,
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/jobs/embed",
                headers={"Authorization": "Bearer test-token"},
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
                    headers={"Authorization": "Bearer test-token"},
                )
                assert status.status_code == 200
                body = status.json()
                if body["status"] in {"succeeded", "failed"}:
                    break
                time.sleep(0.02)
            assert body["status"] == "succeeded", body
            assert body["result"]["bits_embedded"] == 160
            assert "secret_key" not in repr(body).lower()
            assert "contract-message" not in repr(body)


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


def main():
    section("Phase 7 — HTTP Service and Expiring Keys")
    results = [
        run_test("health_is_public_but_jobs_require_bearer_token", t_health_is_public_but_jobs_require_bearer_token),
        run_test("embed_job_returns_only_safe_public_status", t_embed_job_returns_only_safe_public_status),
        run_test("expiring_certificate_rejects_key_after_deadline", t_expiring_certificate_rejects_key_after_deadline),
        run_test("certificate_serialization_is_canonical_and_tamper_evident", t_certificate_serialization_is_canonical_and_tamper_evident),
    ]
    sys.exit(summarise(results, "Phase 7"))


if __name__ == "__main__":
    main()
