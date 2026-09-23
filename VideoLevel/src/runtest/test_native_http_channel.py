"""Real-fixture E2E for HTTP jobs backed by the native authenticated CAVLC CLI."""

from __future__ import annotations

import base64
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from fastapi.testclient import TestClient

from src.api.app import ApiSettings
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
        if record["status"] in {"succeeded", "failed"}:
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
    headers = {"Authorization": "Bearer integration-test-token"}

    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_native_app(
            ApiSettings(api_token="integration-test-token", work_dir=Path(temp_dir), max_workers=1, max_queued_jobs=1),
            cli_path=cli,
        )
        with TestClient(app) as client:
            unsupported_verify = client.post(
                "/api/v1/jobs/verify",
                headers=headers,
                data={
                    "secret_key_b64": base64.b64encode(key).decode("ascii"),
                    "message_length": "1",
                },
                files={
                    "stego_video": ("stego.h264", fixture_bytes, "video/h264"),
                    "original_video": ("original.h264", fixture_bytes, "video/h264"),
                },
            )
            assert unsupported_verify.status_code == 501, unsupported_verify.text
            assert list((Path(temp_dir) / "jobs").glob("*.json")) == []

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
                    [str(cli), "embed-auth-stdin", str(FIXTURE), str(malformed_output)],
                    input=key.hex().encode("ascii") + b"\n" + tail,
                    capture_output=True, check=False,
                )
                assert malformed.returncode != 0
                assert not malformed_output.exists()

            overlong_key = subprocess.run(
                [str(cli), "embed-auth-stdin", str(FIXTURE), str(Path(temp_dir) / "overlong-key.h264")],
                input=(b"1" * 65) + b"\n" + payload.hex().encode("ascii") + b"\n",
                capture_output=True, check=False,
            )
            assert overlong_key.returncode != 0
            assert not (Path(temp_dir) / "overlong-key.h264").exists()


def main():
    section("Native CAVLC HTTP fixture E2E")
    results = [run_test("native_http_embed_blind_extract_wrong_key_and_strict_decode", t_native_http_embed_blind_extract_wrong_key_and_strict_decode)]
    sys.exit(summarise(results, "Native HTTP E2E"))


if __name__ == "__main__":
    main()
