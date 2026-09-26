"""Carry this session's actual proof payload through native HTTP job routes."""

from __future__ import annotations

import argparse
import base64
import time
from pathlib import Path

from common import native_tool, read_key, require_artifact, require_session, run_python_logged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    session, state = require_session(args.session)
    source = Path(state["input_video"])
    payload = require_artifact(session, "packed_payload.bin").read_bytes()
    key = read_key(session)

    def exercise_http() -> None:
        from fastapi.testclient import TestClient

        from src.api.app import ApiSettings
        from src.api.native_handlers import create_native_app

        token = "demo-http-token-not-for-production"
        headers = {"Authorization": f"Bearer {token}"}
        app = create_native_app(
            ApiSettings(api_token=token, work_dir=session / "http_work", max_workers=1,
                        max_queued_jobs=1),
            cli_path=native_tool("zkstego_blind_bits"),
        )

        def wait_job(client: TestClient, job_id: str) -> dict:
            for _ in range(300):
                response = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
                if response.status_code != 200:
                    raise AssertionError(response.text)
                record = response.json()
                if record["status"] in {"succeeded", "failed"}:
                    return record
                time.sleep(0.05)
            raise TimeoutError(f"HTTP job {job_id} did not finish")

        with TestClient(app) as client:
            health = client.get("/health")
            if health.status_code != 200:
                raise AssertionError(f"health endpoint returned {health.status_code}")
            submitted = client.post(
                "/api/v1/jobs/embed",
                headers=headers,
                data={
                    "message_b64": base64.b64encode(payload).decode("ascii"),
                    "secret_key_b64": base64.b64encode(key).decode("ascii"),
                },
                files={"video": (source.name, source.read_bytes(), "video/h264")},
            )
            if submitted.status_code != 202:
                raise AssertionError(f"embed job returned {submitted.status_code}: {submitted.text}")
            embedded = wait_job(client, submitted.json()["job_id"])
            if embedded["status"] != "succeeded":
                raise AssertionError(f"HTTP embed failed: {embedded}")
            artifact = client.get(
                f"/api/v1/jobs/{embedded['job_id']}/artifact", headers=headers,
            )
            if artifact.status_code != 200:
                raise AssertionError(f"stego artifact download returned {artifact.status_code}")
            (session / "http_stego_video.h264").write_bytes(artifact.content)

            submitted_extract = client.post(
                "/api/v1/jobs/extract",
                headers=headers,
                data={
                    "secret_key_b64": base64.b64encode(key).decode("ascii"),
                    "maximum_payload_bytes": "4096",
                },
                files={"stego_video": ("http_stego.h264", artifact.content, "video/h264")},
            )
            if submitted_extract.status_code != 202:
                raise AssertionError(
                    f"extract job returned {submitted_extract.status_code}: {submitted_extract.text}"
                )
            extracted = wait_job(client, submitted_extract.json()["job_id"])
            if extracted["status"] != "succeeded":
                raise AssertionError(f"HTTP extraction failed: {extracted}")
            recovered = client.get(
                f"/api/v1/jobs/{extracted['job_id']}/artifact", headers=headers,
            )
            if recovered.status_code != 200 or recovered.content != payload:
                raise AssertionError("HTTP extraction artifact differs from the proof-bearing session payload")
            verify_response = client.post(
                "/api/v1/jobs/verify", headers=headers,
                data={
                    "secret_key_b64": base64.b64encode(key).decode("ascii"),
                    "message_length": "1",
                },
                files={
                    "stego_video": ("stego.h264", artifact.content, "video/h264"),
                    "original_video": (source.name, source.read_bytes(), "video/h264"),
                },
            )
            if verify_response.status_code != 501:
                raise AssertionError(
                    "native verify endpoint must remain disabled: it does not verify Groth16 proofs"
                )
            print("health=200; embed_job=succeeded; extract_job=succeeded")
            print("proof_bearing_payload_round_trip=True")
            print("native_verify_endpoint=501 (Groth16 verification is client-side after extraction)")

    run_python_logged(session, "11_http_transport.log", "HTTP embed/extract proof-payload round trip", exercise_http)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
