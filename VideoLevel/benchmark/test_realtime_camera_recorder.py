"""Unit tests for preserving physical-camera benchmark runs."""

import hashlib
import json
import math
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark.realtime_camera_recorder import (
    build_camera_capture_command,
    collect_run_environment,
    persist_camera_run,
)


def valid_metrics() -> dict:
    return {
        "capture_source": "physical-camera-test",
        "capture_duration_seconds": 5.0,
        "camera_input_buffer_bytes": 67_108_864,
        "camera_pipe_read_chunk_bytes": 1_024,
        "active_stream_seconds": 151 / 29.7,
        "captured_frames": 151,
        "stego_frames": 151,
        "source_bytes": 216_202,
        "stego_bytes": 216_202,
        "resolution": "352x288",
        "active_stream_frame_rate_fps": 29.7,
        "ffmpeg_strict_decode_exit": 0,
        "capacity_scan_seconds": 0.6,
        "correct_key_payload_match": True,
        "wrong_key_rejected": True,
        "groth16_proof_verified": True,
        "groth16_other_registry_rejected": True,
        "groth16_changed_message_rejected": True,
        "first_output_before_camera_eof": True,
        "capture_device_name": "physical-camera-test-device",
        "capture_encoder": {
            "codec": "libx264",
            "preset": "ultrafast",
            "profile": "baseline",
            "coder": 0,
            "entropy_coding": "CAVLC",
            "pixel_format": "yuv420p",
            "resolution": "352x288",
            "requested_fps": 30,
            "qp": 22,
            "gop": 1,
            "x264_params": "keyint=1:min-keyint=1:scenecut=0:repeat-headers=1",
            "fps_mode": "passthrough",
        },
        "run_environment": {
            "hostname": "benchmark-host",
            "os": "Windows-10",
            "architecture": "AMD64",
            "cpu_model": "test CPU",
            "logical_cpu_count": 8,
            "ram_total_bytes": 16_000_000_000,
            "python_version": "3.12.10",
            "ffmpeg_path": "C:/ffmpeg/bin/ffmpeg.exe",
            "ffmpeg_version": "ffmpeg version 8.0.1",
            "native_cli_path": "native/build/Release/zkstego_blind_bits.exe",
            "native_cli_sha256": "a" * 64,
        },
        "decoded_quality": {
            "decoded_frame_count": 151,
            "yuv420_psnr_full_video_db": 57.5,
            "yuv420_psnr_min_modified_frame_db": 42.0,
            "luma_ssim_mean": 0.995,
            "luma_ssim_min": 0.98,
            "identical_decoded_frames": 129,
        },
        "native_metrics": {
            "bits_embedded": 1_352,
            "candidate_capacity_bits": 2_944,
            "patched_idr_segments": 22,
            "idr_segment_count": 151,
            "idr_service_samples": 151,
            "idr_service_sample_limit": 4_096,
            "idr_service_p50_ms": 2.2,
            "idr_service_p95_ms": 4.0,
            "segment_process_p50_ms": 2.2,
            "segment_process_p95_ms": 3.0,
            "segment_process_samples": 22,
            "segment_process_sample_limit": 4_096,
        },
        "camera_pipe_to_client_nal_latency": {
            "measurement": "ffmpeg_stdout_nal_completion_to_websocket_testclient_nal_completion",
            "nal_count": 151,
            "p50_ms": 11.0,
            "p95_ms": 28.0,
            "camera_read_to_send_start_p50_ms": 0.2,
            "camera_read_to_send_start_p95_ms": 0.4,
            "send_start_to_client_receive_p50_ms": 10.8,
            "send_start_to_client_receive_p95_ms": 27.6,
            "input_nal_completion_interarrival_p50_ms": 29.0,
            "input_nal_completion_interarrival_p95_ms": 36.0,
            "output_nal_completion_interarrival_p50_ms": 30.0,
            "output_nal_completion_interarrival_p95_ms": 39.0,
        },
        "full_stream_capacity": {
            "idr_segments": 151,
            "raw_candidate_signs": 12_000,
            "candidate_capacity_bits": 9_664,
            "max_bits_per_idr": 64,
        },
        "native_resources": {
            "sample_count": 101, "sample_interval_ms": 100, "peak_rss_bytes": 6_000_000,
            "cpu_seconds": 0.125, "wall_seconds": 11.0,
        },
        "capture_process_tree_resources": {
            "sample_count": 100, "sample_interval_ms": 100, "peak_rss_bytes": 140_000_000,
            "cpu_seconds": 1.64, "wall_seconds": 11.0,
        },
        "flow_control": {
            "dropped_input_chunks": 0, "input_chunks": 101, "input_bytes": 216_202,
            "input_chunk_limit_bytes": 1_048_576, "max_input_chunk_bytes": 4_943,
            "input_drain_count": 101, "input_drain_wait_ms_total": 1.5,
            "max_native_stdin_buffer_bytes": 0,
            "native_stdin_write_drain_samples": 101,
            "native_stdin_write_drain_p50_ms": 0.01,
            "native_stdin_write_drain_p95_ms": 0.03,
            "native_stdin_high_water_bytes": 65_536, "output_chunks": 104,
            "output_chunk_limit_bytes": 65_536, "max_output_chunk_bytes": 5_633,
            "native_stdout_to_websocket_send_samples": 104,
            "native_stdout_to_websocket_send_p50_ms": 0.02,
            "native_stdout_to_websocket_send_p95_ms": 0.04,
            "native_stdout_read_wait_samples": 105,
            "native_stdout_read_wait_p50_ms": 0.8,
            "native_stdout_read_wait_p95_ms": 1.3,
        },
    }


class RealtimeCameraRecorderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self._temporary_artifact = Path(self._temporary_directory.name) / "runs.json"

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def test_capture_command_disables_synthetic_frame_duplication(self) -> None:
        metrics = valid_metrics()

        command = build_camera_capture_command(
            camera_device_name="test UVC camera",
            duration_seconds=60,
            camera_input_buffer_bytes=262_144,
            encoder=metrics["capture_encoder"],
        )

        self.assertEqual(command[command.index("-fps_mode") + 1], "passthrough")
        self.assertEqual(command[command.index("-framerate") + 1], "30")
        self.assertEqual(command[-3:], ["-f", "h264", "pipe:1"])

    def test_recorder_rejects_non_passthrough_capture_encoder_mode(self) -> None:
        metrics = valid_metrics()
        metrics["capture_encoder"]["fps_mode"] = "cfr"

        with self.assertRaisesRegex(ValueError, "fps_mode"):
            persist_camera_run(self._temporary_artifact, metrics)

    def test_rejects_missing_or_nonpositive_camera_input_buffer_size(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            metrics = valid_metrics()
            del metrics["camera_input_buffer_bytes"]
            with self.assertRaisesRegex(ValueError, "camera_input_buffer_bytes"):
                persist_camera_run(Path(directory) / "missing.json", metrics)

        with tempfile.TemporaryDirectory() as directory:
            metrics = valid_metrics()
            metrics["camera_input_buffer_bytes"] = 0
            with self.assertRaisesRegex(ValueError, "camera_input_buffer_bytes"):
                persist_camera_run(Path(directory) / "zero.json", metrics)

    def test_accepts_bounded_stdin_buffer_with_one_pending_input_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "runs.json"
            metrics = valid_metrics()
            metrics["flow_control"]["max_input_chunk_bytes"] = 16_384
            metrics["flow_control"]["max_native_stdin_buffer_bytes"] = 65_536 + 16_384

            record = persist_camera_run(destination, metrics)

            self.assertEqual(record["flow_control"]["max_native_stdin_buffer_bytes"], 81_920)

    def test_rejects_stdin_buffer_above_high_water_plus_one_input_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "runs.json"
            metrics = valid_metrics()
            metrics["flow_control"]["max_input_chunk_bytes"] = 16_384
            metrics["flow_control"]["max_native_stdin_buffer_bytes"] = 65_536 + 16_385

            with self.assertRaisesRegex(ValueError, "flow-control measurements"):
                persist_camera_run(destination, metrics)

            self.assertFalse(destination.exists())

    def test_collects_hardware_toolchain_and_native_binary_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cli_path = Path(directory) / "native-cli"
            cli_path.write_bytes(b"native executable fixture")
            ffmpeg_output = "ffmpeg version 8.0.1-full_build\nCopyright (c) FFmpeg developers\n"
            with patch("benchmark.realtime_camera_recorder.shutil.which", return_value="C:/ffmpeg/ffmpeg.exe"), \
                    patch(
                        "benchmark.realtime_camera_recorder.subprocess.run",
                        return_value=subprocess.CompletedProcess(
                            args=["ffmpeg", "-version"], returncode=0,
                            stdout=ffmpeg_output, stderr="",
                        ),
                    ):
                metadata = collect_run_environment(cli_path, camera_device_name="UVC camera")

            self.assertEqual(metadata["camera_device_name"], "UVC camera")
            self.assertEqual(metadata["ffmpeg_version"], "ffmpeg version 8.0.1-full_build")
            self.assertEqual(metadata["native_cli_path"], str(cli_path.resolve()))
            self.assertEqual(
                metadata["native_cli_sha256"],
                hashlib.sha256(b"native executable fixture").hexdigest(),
            )
            self.assertGreater(metadata["logical_cpu_count"], 0)
            self.assertGreater(metadata["ram_total_bytes"], 0)

    def test_appends_next_run_without_replacing_existing_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "runs.json"
            destination.write_text(json.dumps({"runs": [{"run": 4, "sentinel": "keep"}]}), encoding="utf-8")

            record = persist_camera_run(destination, valid_metrics())

            stored = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(stored["runs"][0], {"run": 4, "sentinel": "keep"})
            self.assertEqual(stored["runs"][1], record)
            self.assertEqual(record["run"], 5)
            self.assertEqual(record["captured_frames"], 151)
            self.assertEqual(record["native_metrics"]["bits_embedded"], 1_352)
            self.assertGreaterEqual(
                record["native_metrics"]["candidate_capacity_bits"],
                record["native_metrics"]["bits_embedded"],
            )
            self.assertEqual(record["full_stream_capacity"]["idr_segments"], 151)
            self.assertEqual(record["capture_device_name"], "physical-camera-test-device")
            self.assertEqual(record["capture_encoder"]["entropy_coding"], "CAVLC")
            self.assertEqual(record["run_environment"]["ffmpeg_version"], "ffmpeg version 8.0.1")
            self.assertGreater(
                record["full_stream_capacity"]["candidate_capacity_bits"],
                record["native_metrics"]["candidate_capacity_bits"],
            )

    def test_persisted_functional_run_marks_below_target_fps_as_realtime_gate_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            record = persist_camera_run(Path(directory) / "runs.json", valid_metrics())

        self.assertEqual(record["active_fps_gate"]["minimum_active_stream_fps"], 30)
        self.assertAlmostEqual(record["active_fps_gate"]["measured_active_stream_fps"], 29.7)
        self.assertFalse(record["active_fps_gate"]["passed"])

    def test_persisted_functional_run_passes_fps_gate_at_exact_threshold(self) -> None:
        metrics = valid_metrics()
        metrics["active_stream_frame_rate_fps"] = 30.0
        metrics["active_stream_seconds"] = metrics["stego_frames"] / 30.0

        with tempfile.TemporaryDirectory() as directory:
            record = persist_camera_run(Path(directory) / "runs.json", metrics)

        self.assertTrue(record["active_fps_gate"]["passed"])

    def test_fps_gate_uses_frame_count_when_reported_rate_rounding_crosses_threshold(self) -> None:
        metrics = valid_metrics()
        metrics["active_stream_seconds"] = 5.076
        metrics["active_stream_frame_rate_fps"] = 30.0

        with tempfile.TemporaryDirectory() as directory:
            record = persist_camera_run(Path(directory) / "runs.json", metrics)

        self.assertEqual(record["active_fps_gate"]["reported_active_stream_frame_rate_fps"], 30.0)
        self.assertAlmostEqual(record["active_fps_gate"]["measured_active_stream_fps"], 151 / 5.076)
        self.assertFalse(record["active_fps_gate"]["passed"])

    def test_rejects_capacity_smaller_than_embedded_bits_without_mutating_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "runs.json"
            original = '{"runs": [{"run": 1}]}'
            destination.write_text(original, encoding="utf-8")
            metrics = valid_metrics()
            metrics["native_metrics"]["candidate_capacity_bits"] = 1_000

            with self.assertRaises(ValueError):
                persist_camera_run(destination, metrics)

            self.assertEqual(destination.read_text(encoding="utf-8"), original)

    def test_rejects_full_stream_capacity_above_candidate_bound(self) -> None:
        metrics = valid_metrics()
        metrics["full_stream_capacity"]["candidate_capacity_bits"] = 9_665

        with self.assertRaises(ValueError):
            persist_camera_run(self._temporary_artifact, metrics)

    def test_rejects_failed_camera_run_without_mutating_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "runs.json"
            original = '{"runs": [{"run": 1}]}'
            destination.write_text(original, encoding="utf-8")
            metrics = valid_metrics()
            metrics["ffmpeg_strict_decode_exit"] = 1

            with self.assertRaises(ValueError):
                persist_camera_run(destination, metrics)

            self.assertEqual(destination.read_text(encoding="utf-8"), original)

    def test_rejects_quality_record_missing_required_psnr_ssim_and_frame_counts(self) -> None:
        metrics = valid_metrics()
        del metrics["decoded_quality"]["luma_ssim_mean"]
        with self.assertRaisesRegex(ValueError, "decoded_quality"):
            persist_camera_run(self._temporary_artifact, metrics)

    def test_rejects_missing_payload_patch_latency_percentiles(self) -> None:
        metrics = valid_metrics()
        del metrics["native_metrics"]["segment_process_p50_ms"]
        with self.assertRaisesRegex(ValueError, "segment_process_p50_ms"):
            persist_camera_run(self._temporary_artifact, metrics)

    def test_rejects_non_finite_fps_and_resource_measurements(self) -> None:
        metrics = valid_metrics()
        metrics["active_stream_frame_rate_fps"] = math.nan
        with self.assertRaisesRegex(ValueError, "active_stream_frame_rate_fps"):
            persist_camera_run(self._temporary_artifact, metrics)

        metrics = valid_metrics()
        metrics["native_resources"]["cpu_seconds"] = math.inf
        with self.assertRaisesRegex(ValueError, "native_resources.cpu_seconds"):
            persist_camera_run(self._temporary_artifact, metrics)

    def test_rejects_fps_inconsistent_with_active_stream_duration(self) -> None:
        metrics = valid_metrics()
        metrics["active_stream_frame_rate_fps"] = 60.0
        with self.assertRaisesRegex(ValueError, "inconsistent with frame count and active duration"):
            persist_camera_run(self._temporary_artifact, metrics)

    def test_rejects_missing_encoded_byte_counts(self) -> None:
        metrics = valid_metrics()
        del metrics["stego_bytes"]
        with self.assertRaisesRegex(ValueError, "stego_bytes"):
            persist_camera_run(self._temporary_artifact, metrics)

    def test_rejects_missing_camera_channel_latency_distribution(self) -> None:
        metrics = valid_metrics()
        del metrics["camera_pipe_to_client_nal_latency"]["p95_ms"]
        with self.assertRaisesRegex(ValueError, "camera_pipe_to_client_nal_latency.p95_ms"):
            persist_camera_run(self._temporary_artifact, metrics)

    def test_rejects_missing_native_stdout_wait_percentiles(self) -> None:
        metrics = valid_metrics()
        del metrics["flow_control"]["native_stdout_read_wait_p95_ms"]
        with self.assertRaisesRegex(ValueError, "native_stdout_read_wait_p95_ms"):
            persist_camera_run(self._temporary_artifact, metrics)

    def test_maps_annex_b_nal_completion_latency_across_different_chunks(self) -> None:
        from benchmark.camera_channel_latency import measure_annex_b_channel_latency

        source = b"\x00\x00\x01\x67A\x00\x00\x00\x01\x65B\x00\x00\x01\x41C"
        stego = b"\x00\x00\x01\x67a\x00\x00\x00\x01\x65b\x00\x00\x01\x41c"
        input_chunks = [(source[:4], 1.0), (source[4:9], 1.1), (source[9:14], 1.2), (source[14:], 1.3)]
        output_chunks = [(stego[:3], 2.0), (stego[3:10], 2.04), (stego[10:14], 2.1), (stego[14:], 2.2)]

        metrics = measure_annex_b_channel_latency(input_chunks, output_chunks)

        self.assertEqual(metrics["nal_count"], 3)
        self.assertAlmostEqual(metrics["p50_ms"], 900.0, places=6)
        self.assertAlmostEqual(metrics["p95_ms"], 940.0, places=6)

    def test_labels_loopback_tcp_channel_latency_explicitly(self) -> None:
        from benchmark.camera_channel_latency import measure_annex_b_channel_latency

        stream = b"\x00\x00\x01\x67A\x00\x00\x01\x65B"
        metrics = measure_annex_b_channel_latency(
            [(stream, 1.0)], [(stream, 1.01)], output_transport="loopback_tcp",
        )

        self.assertEqual(
            metrics["measurement"],
            "ffmpeg_stdout_nal_completion_to_websocket_loopback_tcp_nal_completion",
        )

    def test_splits_camera_read_send_and_output_receive_latency(self) -> None:
        from benchmark.camera_channel_latency import measure_annex_b_channel_latency

        stream = b"\x00\x00\x01\x67A\x00\x00\x01\x65B"
        metrics = measure_annex_b_channel_latency(
            [(stream, 1.0)], [(stream, 1.11)],
            send_started_chunks=[(stream, 1.01)], output_transport="loopback_tcp",
        )

        self.assertEqual(metrics["camera_read_to_send_start_p50_ms"], 10.0)
        self.assertEqual(metrics["send_start_to_client_receive_p50_ms"], 100.0)

    def test_measures_input_and_output_nal_completion_interarrival(self) -> None:
        from benchmark.camera_channel_latency import measure_annex_b_channel_latency

        stream = b"\x00\x00\x01\x67A\x00\x00\x01\x65B\x00\x00\x01\x41C"
        input_chunks = [(stream[:8], 1.0), (stream[8:13], 1.1), (stream[13:], 1.2)]
        output_chunks = [(stream[:8], 2.0), (stream[8:13], 2.02), (stream[13:], 2.04)]

        metrics = measure_annex_b_channel_latency(input_chunks, output_chunks)

        self.assertEqual(metrics["input_nal_completion_interarrival_p50_ms"], 100.0)
        self.assertEqual(metrics["output_nal_completion_interarrival_p50_ms"], 20.0)

    def test_rejects_mismatched_input_and_output_nal_sequences(self) -> None:
        from benchmark.camera_channel_latency import measure_annex_b_channel_latency

        source = b"\x00\x00\x01\x67A\x00\x00\x01\x65B"
        wrong_output = b"\x00\x00\x01\x67A\x00\x00\x01\x41B"
        with self.assertRaisesRegex(ValueError, "NAL count or type"):
            measure_annex_b_channel_latency([(source, 1.0)], [(wrong_output, 2.0)])


if __name__ == "__main__":
    unittest.main()
