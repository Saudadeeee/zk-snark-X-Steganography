"""Hardware-gated webcam -> locked CAVLC encode -> native HTTP blind E2E."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from fastapi.testclient import TestClient

from src.api.app import ApiSettings
from src.api.native_handlers import create_native_app
from src.runtest._helpers import run_test, section, summarise

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CLI = ROOT / "native" / "build" / "Release" / "zkstego_blind_bits.exe"


def _wait_terminal(client: TestClient, job_id: str, headers: dict[str, str]) -> dict:
    for _ in range(600):
        response = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
        assert response.status_code == 200, response.text
        record = response.json()
        if record["status"] in {"succeeded", "failed"}:
            return record
        time.sleep(0.05)
    raise AssertionError(f"camera job {job_id} did not finish within 30 seconds")


def t_physical_camera_http_blind_round_trip():
    camera_name = os.environ.get("ZK_STEGO_CAMERA_NAME")
    assert camera_name, "set ZK_STEGO_CAMERA_NAME to an FFmpeg DirectShow video device"
    cli = Path(os.environ.get("ZK_STEGO_NATIVE_CLI", DEFAULT_CLI))
    assert cli.is_file(), f"native CLI missing: {cli}"
    payload = b"cam-proof-v1"
    key = bytes(range(32, 64))
    headers = {"Authorization": "Bearer camera-e2e-token"}

    with tempfile.TemporaryDirectory(prefix="zkstego-camera-e2e-") as temp_dir:
        root = Path(temp_dir)
        camera_video = root / "camera.h264"
        capture_started = time.perf_counter()
        capture = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "dshow", "-rtbufsize", "64M", "-video_size", "352x288",
                "-framerate", "30", "-i", f"video={camera_name}",
                "-t", "3", "-an", "-c:v", "libx264", "-preset", "ultrafast",
                "-profile:v", "baseline", "-coder", "0", "-pix_fmt", "yuv420p",
                "-x264-params", "keyint=1:min-keyint=1:scenecut=0:repeat-headers=1",
                "-g", "1", "-qp", "22", "-f", "h264", str(camera_video),
            ],
            capture_output=True,
            check=False,
            timeout=30,
        )
        capture_seconds = time.perf_counter() - capture_started
        assert capture.returncode == 0, capture.stderr.decode("utf-8", errors="replace")
        camera_bytes = camera_video.read_bytes()
        assert camera_bytes, "camera capture produced an empty H.264 stream"
        ffprobe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-f", "h264", "-count_frames",
                "-select_streams", "v:0", "-show_entries",
                "stream=width,height,avg_frame_rate,nb_read_frames", "-of", "json", str(camera_video),
            ],
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert ffprobe.returncode == 0, ffprobe.stderr.decode("utf-8", errors="replace")
        stream_info = json.loads(ffprobe.stdout)["streams"][0]
        assert (stream_info["width"], stream_info["height"]) == (352, 288), stream_info
        frame_count = int(stream_info["nb_read_frames"])
        assert frame_count > 0, stream_info

        with tempfile.TemporaryDirectory() as work_dir:
            app = create_native_app(
                ApiSettings(api_token="camera-e2e-token", work_dir=Path(work_dir)),
                cli_path=cli,
            )
            with TestClient(app) as client:
                embed_started = time.perf_counter()
                submitted = client.post(
                    "/api/v1/jobs/embed",
                    headers=headers,
                    data={
                        "message_b64": base64.b64encode(payload).decode("ascii"),
                        "secret_key_b64": base64.b64encode(key).decode("ascii"),
                    },
                    files={"video": ("camera.h264", camera_bytes, "video/h264")},
                )
                assert submitted.status_code == 202, submitted.text
                embedded = _wait_terminal(client, submitted.json()["job_id"], headers)
                embed_seconds = time.perf_counter() - embed_started
                assert embedded["status"] == "succeeded", embedded
                stego_response = client.get(
                    f"/api/v1/jobs/{embedded['job_id']}/artifact", headers=headers,
                )
                assert stego_response.status_code == 200, stego_response.text
                stego = stego_response.content
                assert len(stego) == len(camera_bytes), (len(camera_bytes), len(stego))

                strict = subprocess.run(
                    ["ffmpeg", "-v", "error", "-xerror", "-i", "pipe:0", "-f", "null", "-"],
                    input=stego,
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                assert strict.returncode == 0, strict.stderr.decode("utf-8", errors="replace")

                extract_started = time.perf_counter()
                extracted_response = client.post(
                    "/api/v1/jobs/extract",
                    headers=headers,
                    data={
                        "secret_key_b64": base64.b64encode(key).decode("ascii"),
                        "maximum_payload_bytes": "128",
                    },
                    files={"stego_video": ("camera-stego.h264", stego, "video/h264")},
                )
                assert extracted_response.status_code == 202, extracted_response.text
                extracted = _wait_terminal(client, extracted_response.json()["job_id"], headers)
                extract_seconds = time.perf_counter() - extract_started
                assert extracted["status"] == "succeeded", extracted
                recovered = client.get(
                    f"/api/v1/jobs/{extracted['job_id']}/artifact", headers=headers,
                )
                assert recovered.status_code == 200, recovered.text
                assert recovered.content == payload

                wrong_key = bytes([0xD7]) * 32
                wrong_response = client.post(
                    "/api/v1/jobs/extract",
                    headers=headers,
                    data={
                        "secret_key_b64": base64.b64encode(wrong_key).decode("ascii"),
                        "maximum_payload_bytes": "128",
                    },
                    files={"stego_video": ("camera-stego.h264", stego, "video/h264")},
                )
                assert wrong_response.status_code == 202, wrong_response.text
                wrong_result = _wait_terminal(client, wrong_response.json()["job_id"], headers)
                assert wrong_result["status"] == "failed", wrong_result
                assert client.get(
                    f"/api/v1/jobs/{wrong_result['job_id']}/artifact", headers=headers,
                ).status_code == 404

        print(
            "CAMERA_E2E_METRICS "
            + json.dumps(
                {
                    "capture_source": "DirectShow webcam",
                    "resolution": "352x288",
                    "configured_fps": 30,
                    "ffprobe_avg_frame_rate": stream_info.get("avg_frame_rate"),
                    "captured_frames": frame_count,
                    "camera_h264_bytes": len(camera_bytes),
                    "capture_wall_seconds": round(capture_seconds, 3),
                    "http_embed_wall_seconds": round(embed_seconds, 3),
                    "http_extract_wall_seconds": round(extract_seconds, 3),
                    "strict_decoder_exit": strict.returncode,
                    "correct_key_payload_match": recovered.content == payload,
                    "wrong_key_status": wrong_result["status"],
                },
                sort_keys=True,
            )
        )


def main():
    section("Physical camera -> native CAVLC HTTP E2E")
    if not os.environ.get("ZK_STEGO_CAMERA_NAME"):
        print("  [SKIP] set ZK_STEGO_CAMERA_NAME to run this hardware integration test")
        return 0
    results = [run_test("physical_camera_http_blind_round_trip", t_physical_camera_http_blind_round_trip)]
    return summarise(results, "Physical camera E2E")


if __name__ == "__main__":
    sys.exit(main())
