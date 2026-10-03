"""Hardware-gated live webcam -> authenticated WebSocket -> native CAVLC E2E."""

from __future__ import annotations

import base64
import asyncio
import contextlib
import json
import math
import os
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from contextlib import contextmanager

import numpy as np
import psutil
from skimage.metrics import structural_similarity

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from benchmark.camera_channel_latency import measure_annex_b_channel_latency
from benchmark.realtime_camera_recorder import build_camera_capture_command
from src.runtest._helpers import run_test, section, summarise
from src.zk_proof import ZKSnarkBridge, pack, proof_to_bytes, unpack

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CLI = ROOT / "native" / "build" / "Release" / "zkstego_blind_bits.exe"
CAPTURE_ENCODER_CONFIG = {
    "codec": "libx264",
    "preset": "ultrafast",
    "profile": "baseline",
    "coder": 0,
    "entropy_coding": "CAVLC",
    "pixel_format": "yuv420p",
    "resolution": "352x288",
    "requested_fps": 30,
    "fps_mode": "passthrough",
    "qp": 22,
    "gop": 1,
    "x264_params": "keyint=1:min-keyint=1:scenecut=0:repeat-headers=1",
}
# 16 KiB reduces per-message Python/ASGI overhead while keeping the pipe
# incremental; the chosen value is recorded with each physical-camera run.
CAMERA_PIPE_READ_CHUNK_BYTES = 16 * 1024
CAMERA_DSHOW_RTBUF_SIZE = "256K"
CAMERA_DSHOW_RTBUF_SIZE_BYTES = 256 * 1024


@contextmanager
def _running_native_uvicorn(cli: Path, token: str, work_dir: str):
    import httpx

    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
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
            "--ws-max-queue", "1", "--no-access-log", "--log-level", "warning",
        ],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
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
        yield f"ws://127.0.0.1:{port}/api/v1/stream"
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


class _AsyncWebSocketClientThread:
    """Synchronous test facade with receive timestamps taken in async I/O context."""

    def __init__(self, uri: str, headers: dict[str, str]):
        self._uri = uri
        self._headers = headers
        self._ready = threading.Event()
        self._events: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run_loop, name="camera-async-ws-client", daemon=True)
        self._loop = None
        self._websocket = None
        self._receiver = None

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()
        self._loop.close()

    async def _open(self) -> None:
        from websockets.asyncio.client import connect

        self._websocket = await connect(
            self._uri, additional_headers=self._headers, max_size=1024 * 1024, max_queue=1,
            compression=None, proxy=None,
        )
        self._receiver = asyncio.create_task(self._receive_loop())

    async def _receive_loop(self) -> None:
        from websockets.exceptions import ConnectionClosed

        try:
            while True:
                message = await self._websocket.recv()
                self._events.put((message, time.perf_counter()))
        except ConnectionClosed:
            self._events.put((None, time.perf_counter()))

    def __enter__(self):
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise TimeoutError("WebSocket event loop did not start")
        asyncio.run_coroutine_threadsafe(self._open(), self._loop).result(timeout=15)
        return self

    async def _send_with_timestamp(self, message: bytes | str) -> float:
        send_started_at = time.perf_counter()
        await self._websocket.send(message)
        return send_started_at

    def send(self, message: bytes | str) -> float:
        future = asyncio.run_coroutine_threadsafe(self._send_with_timestamp(message), self._loop)
        return future.result(timeout=30)

    def recv_with_timestamp(self, timeout: float = 30.0):
        return self._events.get(timeout=timeout)

    def recv(self, timeout: float = 30.0):
        message, _arrival = self.recv_with_timestamp(timeout)
        return message

    async def _close(self) -> None:
        if self._websocket is not None:
            await self._websocket.close()
        if self._receiver is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._receiver

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        if self._loop is not None and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._close(), self._loop).result(timeout=15)
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)


def _capture_duration_seconds() -> float:
    raw = os.environ.get("ZK_STEGO_CAMERA_DURATION_SECONDS", "5")
    try:
        duration = float(raw)
    except ValueError as exc:
        raise ValueError("ZK_STEGO_CAMERA_DURATION_SECONDS must be a number") from exc
    if not math.isfinite(duration) or not 1.0 <= duration <= 300.0:
        raise ValueError("ZK_STEGO_CAMERA_DURATION_SECONDS must be between 1 and 300")
    return duration


def _decode_raw_yuv420(stream: bytes, width: int, height: int) -> np.ndarray:
    decoded = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-xerror", "-f", "h264", "-i", "pipe:0",
            "-f", "rawvideo", "-pix_fmt", "yuv420p", "pipe:1",
        ],
        input=stream,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert decoded.returncode == 0, decoded.stderr.decode("utf-8", errors="replace")
    samples_per_frame = width * height * 3 // 2
    assert len(decoded.stdout) % samples_per_frame == 0
    return np.frombuffer(decoded.stdout, dtype=np.uint8).reshape(-1, samples_per_frame)


def _decoded_quality(source: bytes, stego: bytes, width: int, height: int) -> dict:
    source_frames = _decode_raw_yuv420(source, width, height)
    stego_frames = _decode_raw_yuv420(stego, width, height)
    assert source_frames.shape == stego_frames.shape and source_frames.shape[0] > 0
    luma_samples = width * height
    frame_psnr = []
    frame_ssim = []
    total_squared_error = 0.0
    for original, modified in zip(source_frames, stego_frames):
        difference = original.astype(np.int16) - modified.astype(np.int16)
        squared_error = difference.astype(np.float64) ** 2
        total_squared_error += float(np.sum(squared_error))
        mse = float(np.mean(squared_error))
        frame_psnr.append(None if mse == 0.0 else 10.0 * math.log10((255.0 * 255.0) / mse))
        frame_ssim.append(float(structural_similarity(
            original[:luma_samples].reshape(height, width),
            modified[:luma_samples].reshape(height, width),
            data_range=255,
        )))
    finite_psnr = [value for value in frame_psnr if value is not None]
    total_mse = total_squared_error / (source_frames.size)
    return {
        "decoded_frame_count": int(source_frames.shape[0]),
        "yuv420_psnr_full_video_db": round(10.0 * math.log10((255.0 * 255.0) / total_mse), 4)
        if total_mse else None,
        "yuv420_psnr_min_modified_frame_db": round(min(finite_psnr), 4) if finite_psnr else None,
        "luma_ssim_mean": round(sum(frame_ssim) / len(frame_ssim), 8),
        "luma_ssim_min": round(min(frame_ssim), 8),
        "identical_decoded_frames": sum(value is None for value in frame_psnr),
    }


def _ffprobe_frame_timing(stream_bytes: bytes) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-f", "h264", "-select_streams", "v:0",
            "-show_frames", "-show_entries", "frame=best_effort_timestamp_time,pkt_duration_time",
            "-of", "json", "pipe:0",
        ],
        input=stream_bytes,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    frames = json.loads(result.stdout).get("frames", [])
    timestamps = [
        float(frame["best_effort_timestamp_time"])
        for frame in frames
        if frame.get("best_effort_timestamp_time") not in (None, "N/A")
    ]
    deltas = [right - left for left, right in zip(timestamps, timestamps[1:]) if right > left]
    median_delta = float(np.median(deltas)) if deltas else None
    return {
        "timestamped_frames": len(timestamps),
        "first_timestamp_seconds": timestamps[0] if timestamps else None,
        "last_timestamp_seconds": timestamps[-1] if timestamps else None,
        "median_positive_pts_delta_seconds": round(median_delta, 8) if median_delta else None,
        "median_pts_derived_fps": round(1.0 / median_delta, 6) if median_delta else None,
        "non_increasing_pts_pairs": sum(right <= left for left, right in zip(timestamps, timestamps[1:])),
    }


def _measure_full_stream_capacity(cli: Path, stream_bytes: bytes) -> tuple[dict, float]:
    maximum_bits_per_idr = int(os.environ.get("ZK_STEGO_MAX_BITS_PER_IDR", "64"))
    assert maximum_bits_per_idr > 0
    started = time.perf_counter()
    result = subprocess.run(
        [str(cli), "measure-live-capacity-stdin", str(maximum_bits_per_idr)],
        input=stream_bytes,
        capture_output=True,
        check=False,
        timeout=300,
    )
    elapsed = time.perf_counter() - started
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    records = [line.removeprefix("ZKSTEG_CAPACITY_METRICS ")
               for line in result.stdout.decode("ascii").splitlines()
               if line.startswith("ZKSTEG_CAPACITY_METRICS ")]
    assert len(records) == 1, result.stdout.decode("utf-8", errors="replace")
    metrics = json.loads(records[0])
    assert metrics["max_bits_per_idr"] == maximum_bits_per_idr
    assert metrics["idr_segments"] > 0
    assert metrics["raw_candidate_signs"] >= metrics["candidate_capacity_bits"] > 0
    assert metrics["candidate_capacity_bits"] <= metrics["idr_segments"] * maximum_bits_per_idr
    return metrics, round(elapsed, 6)


class _ProcessTreeSampler:
    """Sample test/API, native CLI and FFmpeg child resources during capture only."""

    def __init__(self, root_pid: int, interval_seconds: float = 0.1):
        self._root = psutil.Process(root_pid)
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._previous_cpu: dict[int, float] = {}
        self._cpu_seconds = 0.0
        self._peak_rss_bytes = 0
        self._sample_count = 0
        self._started_at = 0.0

    def _sample(self, *, baseline: bool = False) -> None:
        try:
            processes = [self._root, *self._root.children(recursive=True)]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            processes = [self._root]
        rss_total = 0
        for process in processes:
            try:
                cpu = process.cpu_times()
                current_cpu = cpu.user + cpu.system
                previous_cpu = self._previous_cpu.get(process.pid, current_cpu if baseline else 0.0)
                self._cpu_seconds += max(0.0, current_cpu - previous_cpu)
                self._previous_cpu[process.pid] = current_cpu
                rss_total += process.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        self._peak_rss_bytes = max(self._peak_rss_bytes, rss_total)
        if not baseline:
            self._sample_count += 1

    def start(self) -> None:
        self._started_at = time.perf_counter()
        self._sample(baseline=True)

        def monitor() -> None:
            while not self._stop.wait(self._interval):
                self._sample()

        self._thread = threading.Thread(target=monitor, name="camera-process-tree-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> dict:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._sample()
        return {
            "sample_count": self._sample_count,
            "sample_interval_ms": int(self._interval * 1000),
            "cpu_seconds": round(self._cpu_seconds, 6),
            "peak_rss_bytes": self._peak_rss_bytes,
            "wall_seconds": round(time.perf_counter() - self._started_at, 6),
        }


def t_physical_camera_tcp_websocket_live_round_trip():
    capture_duration_seconds = _capture_duration_seconds()
    camera_name = os.environ.get("ZK_STEGO_CAMERA_NAME")
    assert camera_name, "set ZK_STEGO_CAMERA_NAME to an FFmpeg DirectShow video device"
    cli = Path(os.environ.get("ZK_STEGO_NATIVE_CLI", DEFAULT_CLI))
    assert cli.is_file(), f"native CLI missing: {cli}"
    key = bytes(range(32, 64))
    payload = b"live-camera-proof"
    proof_bridge = ZKSnarkBridge(str(ROOT / "circuits"))
    proof_started = time.perf_counter()
    proof_dict, _public_signals = proof_bridge.generate_proof_for_payload(payload, key)
    proof_generation_ms = (time.perf_counter() - proof_started) * 1000.0
    proof_payload = pack(payload, proof_to_bytes(proof_dict))
    token = "live-camera-websocket-token-for-tests-only"
    headers = {"Authorization": f"Bearer {token}"}
    temporary_work_dir = tempfile.TemporaryDirectory(prefix="zkstego-live-camera-ws-")
    camera_process = None
    from websockets.exceptions import ConnectionClosed

    with _running_native_uvicorn(cli, token, temporary_work_dir.name) as uri, contextlib.ExitStack() as stack:
        websocket = stack.enter_context(_AsyncWebSocketClientThread(uri, headers))
        websocket.send(json.dumps({
                "operation": "embed",
                "secret_key_b64": base64.b64encode(key).decode("ascii"),
                "message_b64": base64.b64encode(proof_payload).decode("ascii"),
            }))
        assert json.loads(websocket.recv()) == {"type": "ready", "operation": "embed"}
        process_tree_sampler = _ProcessTreeSampler(os.getpid())
        process_tree_sampler.start()
        camera_process = subprocess.Popen(
                build_camera_capture_command(
                    camera_device_name=camera_name,
                    duration_seconds=capture_duration_seconds,
                    camera_input_buffer_bytes=CAMERA_DSHOW_RTBUF_SIZE_BYTES,
                    encoder=CAPTURE_ENCODER_CONFIG,
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
        )
        assert camera_process.stdout is not None and camera_process.stderr is not None
        stego_parts: list[bytes] = []
        stego_part_arrivals: list[float] = []
        completion: queue.Queue = queue.Queue()
        first_output_at: list[float] = []
        capture_started = time.perf_counter()

        def collect_video() -> None:
            try:
                while True:
                    message, output_arrival = websocket.recv_with_timestamp()
                    if message is None:
                        completion.put({"type": "disconnect"})
                        return
                    if isinstance(message, bytes):
                        stego_parts.append(message)
                        stego_part_arrivals.append(output_arrival)
                        if not first_output_at:
                            first_output_at.append(output_arrival)
                    else:
                        response = json.loads(message)
                        if response.get("type") in {"complete", "error"}:
                            completion.put(response)
                            return
            except ConnectionClosed:
                completion.put({"type": "disconnect"})

        output_reader = threading.Thread(target=collect_video, daemon=True)
        output_reader.start()
        source_parts: list[bytes] = []
        source_part_arrivals: list[float] = []
        source_send_start_arrivals: list[float] = []
        first_input_at: list[float] = []
        try:
            while chunk := os.read(camera_process.stdout.fileno(), CAMERA_PIPE_READ_CHUNK_BYTES):
                input_arrival = time.perf_counter()
                if not first_input_at:
                    first_input_at.append(input_arrival)
                source_parts.append(chunk)
                source_part_arrivals.append(input_arrival)
                send_started_at = websocket.send(chunk)
                source_send_start_arrivals.append(send_started_at)
            camera_eof_at = time.perf_counter()
            capture_return_code = camera_process.wait(timeout=30)
            camera_stderr = camera_process.stderr.read()
        finally:
            if camera_process.poll() is None:
                camera_process.kill()
                camera_process.wait(timeout=10)
        websocket.send(json.dumps({"type": "end"}))
        output_reader.join(timeout=30)
        assert not output_reader.is_alive(), "live camera WebSocket did not terminate"
        terminal = completion.get(timeout=5)
        assert capture_return_code == 0, camera_stderr.decode("utf-8", errors="replace")
        assert terminal.get("type") == "complete", {
            **terminal,
            "camera_input_bytes": sum(map(len, source_parts)),
            "camera_encoder_exit": capture_return_code,
        }
        flow_control = terminal.get("flow_control")
        assert isinstance(flow_control, dict), terminal
        assert flow_control["input_bytes"] == sum(map(len, source_parts))
        assert 0 < flow_control["max_input_chunk_bytes"] <= flow_control["input_chunk_limit_bytes"]
        assert flow_control["max_native_stdin_buffer_bytes"] <= (
            flow_control["native_stdin_high_water_bytes"] + flow_control["max_input_chunk_bytes"]
        )
        assert flow_control["input_drain_count"] == flow_control["input_chunks"]
        assert flow_control["output_chunks"] > 0 and flow_control["dropped_input_chunks"] == 0
        source = b"".join(source_parts)
        stego = b"".join(stego_parts)
        channel_latency = measure_annex_b_channel_latency(
            list(zip(source_parts, source_part_arrivals)),
            list(zip(stego_parts, stego_part_arrivals)), output_transport="loopback_tcp",
            send_started_chunks=list(zip(source_parts, source_send_start_arrivals)),
        )
        pipeline_finished_at = time.perf_counter()
        capture_process_tree_resources = process_tree_sampler.stop()
        assert source and stego
        assert terminal.get("media_bytes") == len(source), terminal
        assert first_output_at and first_output_at[0] < camera_eof_at, (
            "server emitted no H.264 before the live camera stream ended"
        )

        full_stream_capacity, capacity_scan_seconds = _measure_full_stream_capacity(cli, source)
        assert terminal["native_metrics"]["idr_segment_count"] == full_stream_capacity["idr_segments"]
        assert terminal["native_metrics"]["idr_service_samples"] == min(
            full_stream_capacity["idr_segments"],
            terminal["native_metrics"]["idr_service_sample_limit"],
        )
        strict = subprocess.run(
            ["ffmpeg", "-v", "error", "-xerror", "-i", "pipe:0", "-f", "null", "-"],
            input=stego,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert strict.returncode == 0, strict.stderr.decode("utf-8", errors="replace")

        def extract_from_stream(secret_key: bytes) -> dict:
            result_queue: queue.Queue = queue.Queue()
            with _AsyncWebSocketClientThread(uri, headers) as websocket:
                websocket.send(json.dumps({
                    "operation": "extract",
                    "secret_key_b64": base64.b64encode(secret_key).decode("ascii"),
                    "maximum_payload_bytes": 4096,
                }))
                assert json.loads(websocket.recv()) == {"type": "ready", "operation": "extract"}

                def collect_result() -> None:
                    try:
                        while True:
                            event = websocket.recv()
                            if event is None:
                                result_queue.put({"type": "disconnect"})
                                return
                            if isinstance(event, str):
                                response = json.loads(event)
                                if response.get("type") in {"payload", "error"}:
                                    result_queue.put(response)
                                    return
                    except ConnectionClosed:
                        result_queue.put({"type": "disconnect"})

                reader = threading.Thread(target=collect_result, daemon=True)
                reader.start()
                for offset in range(0, len(stego), 64 * 1024):
                    try:
                        websocket.send(stego[offset : offset + 64 * 1024])
                    except ConnectionClosed:
                        break
                    try:
                        return result_queue.get(timeout=0.01)
                    except queue.Empty:
                        continue
                try:
                    websocket.send(json.dumps({"type": "end"}))
                except ConnectionClosed:
                    pass
                reader.join(timeout=20)
                assert not reader.is_alive(), "live camera extraction did not terminate"
                return result_queue.get(timeout=5)

        extraction = extract_from_stream(key)
        assert extraction.get("type") == "payload", extraction
        extracted_proof_payload = base64.b64decode(extraction["payload_b64"], validate=True)
        extracted_message, extracted_proof_bytes = unpack(extracted_proof_payload)
        assert extracted_message == payload
        assert extracted_proof_bytes == proof_to_bytes(proof_dict)
        stream_metrics = terminal.get("native_metrics")
        assert isinstance(stream_metrics, dict), terminal
        assert stream_metrics["bits_embedded"] == (len(extracted_proof_payload) + 19) * 8
        assert stream_metrics["candidate_capacity_bits"] >= stream_metrics["bits_embedded"]
        verify_started = time.perf_counter()
        extracted_proof = proof_bridge.bytes_to_proof(extracted_proof_bytes)
        proof_valid = proof_bridge.verify_proof_for_payload(extracted_proof, extracted_message, key)
        proof_verification_ms = (time.perf_counter() - verify_started) * 1000.0
        assert proof_valid, "Groth16 proof recovered from camera video did not verify"
        wrong_key = bytes([0x93]) * 32
        wrong_key_proof_rejected = not proof_bridge.verify_proof_for_payload(
            extracted_proof, extracted_message, wrong_key,
        )
        changed_message = extracted_message + b"!"
        changed_message_proof_rejected = not proof_bridge.verify_proof_for_payload(
            extracted_proof, changed_message, key,
        )
        assert wrong_key_proof_rejected, "Groth16 proof unexpectedly verified against a different key"
        assert changed_message_proof_rejected, "Groth16 proof unexpectedly verified against a changed message"
        wrong_key_result = extract_from_stream(wrong_key)
        assert wrong_key_result.get("type") == "error" and wrong_key_result.get("code") == "payload_not_authenticated", wrong_key_result

        ffprobe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-f", "h264", "-count_frames", "-select_streams", "v:0",
                "-show_entries",
                "stream=width,height,r_frame_rate,avg_frame_rate,time_base,duration,nb_read_frames",
                "-of", "json", "pipe:0",
            ],
            input=source,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert ffprobe.returncode == 0, ffprobe.stderr.decode("utf-8", errors="replace")
        stream = json.loads(ffprobe.stdout)["streams"][0]
        frame_count = int(stream["nb_read_frames"])
        frame_timing = _ffprobe_frame_timing(source)
        quality = _decoded_quality(source, stego, int(stream["width"]), int(stream["height"]))
        assert quality["decoded_frame_count"] == frame_count, quality
        assert quality["yuv420_psnr_full_video_db"] is not None, quality
        assert -1.0 <= quality["luma_ssim_min"] <= quality["luma_ssim_mean"] <= 1.0, quality
        stego_probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-f", "h264", "-count_frames", "-select_streams", "v:0",
                "-show_entries", "stream=nb_read_frames", "-of", "json", "pipe:0",
            ],
            input=stego,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert stego_probe.returncode == 0, stego_probe.stderr.decode("utf-8", errors="replace")
        stego_frame_count = int(json.loads(stego_probe.stdout)["streams"][0]["nb_read_frames"])
        assert stego_frame_count == frame_count, (frame_count, stego_frame_count)
        assert capture_process_tree_resources["sample_count"] > 0
        assert capture_process_tree_resources["peak_rss_bytes"] >= terminal["native_resources"]["peak_rss_bytes"]
        assert capture_process_tree_resources["cpu_seconds"] >= terminal["native_resources"]["cpu_seconds"]
        pipeline_elapsed = max(pipeline_finished_at - capture_started, 1e-6)
        capture_elapsed = max(camera_eof_at - capture_started, 1e-6)
        camera_startup_elapsed = max(first_input_at[0] - capture_started, 1e-6)
        active_stream_elapsed = max(camera_eof_at - first_input_at[0], 1e-6)
        print(
            "LIVE_CAMERA_WS_METRICS "
            + json.dumps({
                "capture_source": "DirectShow UVC webcam -> FFmpeg pipe -> Uvicorn WebSocket loopback TCP -> native CAVLC",
                "capture_device_name": camera_name,
                "capture_encoder": CAPTURE_ENCODER_CONFIG,
                "resolution": f"{stream['width']}x{stream['height']}",
                "capture_duration_seconds": capture_duration_seconds,
                "camera_input_buffer_bytes": CAMERA_DSHOW_RTBUF_SIZE_BYTES,
                "camera_pipe_read_chunk_bytes": CAMERA_PIPE_READ_CHUNK_BYTES,
                "ffprobe_average_fps": stream.get("avg_frame_rate"),
                "ffprobe_nominal_fps": stream.get("r_frame_rate"),
                "ffprobe_time_base": stream.get("time_base"),
                "ffprobe_media_duration_seconds": stream.get("duration"),
                "ffprobe_frame_timing": frame_timing,
                "captured_frames": frame_count,
                "stego_frames": stego_frame_count,
                "decoded_quality": quality,
                "camera_pipe_to_client_nal_latency": channel_latency,
                "source_bytes": len(source),
                "stego_bytes": len(stego),
                "native_metrics": terminal.get("native_metrics"),
                "full_stream_capacity": full_stream_capacity,
                "capacity_scan_seconds": capacity_scan_seconds,
                "native_resources": terminal.get("native_resources"),
                "capture_process_tree_resources": capture_process_tree_resources,
                "flow_control": flow_control,
                "capture_wall_seconds": round(capture_elapsed, 3),
                "camera_startup_seconds": round(camera_startup_elapsed, 3),
                "active_stream_seconds": round(active_stream_elapsed, 3),
                "pipeline_wall_seconds": round(pipeline_elapsed, 3),
                "launch_to_eof_fps_including_camera_startup": round(frame_count / capture_elapsed, 3),
                "active_stream_frame_rate_fps": round(frame_count / active_stream_elapsed, 3),
                "time_to_first_output_ms": round((first_output_at[0] - capture_started) * 1000, 3),
                "first_input_to_output_ms": round((first_output_at[0] - first_input_at[0]) * 1000, 3),
                "first_output_before_camera_eof": first_output_at[0] < camera_eof_at,
                "ffmpeg_strict_decode_exit": strict.returncode,
                "correct_key_payload_match": True,
                "wrong_key_rejected": wrong_key_result.get("type") == "error",
                "groth16_proof_bytes": len(extracted_proof_bytes),
                "groth16_proof_verified": proof_valid,
                "groth16_wrong_key_rejected": wrong_key_proof_rejected,
                "groth16_changed_message_rejected": changed_message_proof_rejected,
                "proof_generation_ms_off_capture_path": round(proof_generation_ms, 3),
                "proof_verification_ms_after_extraction": round(proof_verification_ms, 3),
            }, sort_keys=True)
        )
    temporary_work_dir.cleanup()


def main():
    section("Physical camera -> native CAVLC channel E2E")
    if not os.environ.get("ZK_STEGO_CAMERA_NAME"):
        print("  [SKIP] set ZK_STEGO_CAMERA_NAME to run this hardware integration test")
        return 0
    results = [run_test("physical_camera_tcp_websocket_live_round_trip", t_physical_camera_tcp_websocket_live_round_trip)]
    return summarise(results, "Physical camera E2E")


if __name__ == "__main__":
    sys.exit(main())
