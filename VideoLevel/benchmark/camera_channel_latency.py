"""Measure Annex-B NAL completion latency across the camera WebSocket channel."""

from __future__ import annotations

import math
from bisect import bisect_left
from typing import Sequence


ChunkArrival = tuple[bytes, float]


def _flatten_chunks(chunks: Sequence[ChunkArrival], label: str) -> tuple[bytes, list[int], list[float]]:
    if not chunks:
        raise ValueError(f"{label} chunks must not be empty")
    data = bytearray()
    cumulative_ends: list[int] = []
    arrival_times: list[float] = []
    previous_time = -math.inf
    for chunk, arrival_time in chunks:
        if not isinstance(chunk, bytes) or not chunk:
            raise ValueError(f"{label} chunks must contain non-empty bytes")
        if (not isinstance(arrival_time, (int, float)) or isinstance(arrival_time, bool)
                or not math.isfinite(arrival_time) or arrival_time < previous_time):
            raise ValueError(f"{label} chunk arrival times must be finite and monotonic")
        data.extend(chunk)
        cumulative_ends.append(len(data))
        arrival_times.append(float(arrival_time))
        previous_time = float(arrival_time)
    return bytes(data), cumulative_ends, arrival_times


def _nal_completion_offsets(data: bytes) -> list[tuple[int, int]]:
    """Return (NAL type, byte offset when that NAL's end is observable)."""
    starts: list[tuple[int, int]] = []
    offset = 0
    while offset + 3 <= len(data):
        if data[offset:offset + 4] == b"\x00\x00\x00\x01":
            starts.append((offset, 4))
            offset += 4
        elif data[offset:offset + 3] == b"\x00\x00\x01":
            starts.append((offset, 3))
            offset += 3
        else:
            offset += 1
    if not starts:
        raise ValueError("Annex-B stream contains no start codes")

    nals: list[tuple[int, int]] = []
    for index, (start, prefix_size) in enumerate(starts):
        header_offset = start + prefix_size
        if header_offset >= len(data) or (index + 1 < len(starts) and header_offset >= starts[index + 1][0]):
            raise ValueError("Annex-B stream contains an empty NAL unit")
        nal_type = data[header_offset] & 0x1F
        if index + 1 < len(starts):
            next_start, next_prefix_size = starts[index + 1]
            completion_offset = next_start + next_prefix_size
        else:
            completion_offset = len(data)
        nals.append((nal_type, completion_offset))
    return nals


def _arrival_at_offset(offset: int, cumulative_ends: list[int], arrival_times: list[float]) -> float:
    chunk_index = bisect_left(cumulative_ends, offset)
    if chunk_index >= len(arrival_times):
        raise ValueError("chunk arrival metadata does not cover the complete Annex-B stream")
    return arrival_times[chunk_index]


def measure_annex_b_channel_latency(
    input_chunks: Sequence[ChunkArrival], output_chunks: Sequence[ChunkArrival],
    *, output_transport: str = "testclient", send_started_chunks: Sequence[ChunkArrival] | None = None,
) -> dict[str, float | int | str]:
    """Pair NALs by order/type and measure input completion to client receipt.

    Input timestamps should be sampled immediately after reading camera-encoded
    bytes from FFmpeg stdout. Output timestamps should be sampled immediately
    after the corresponding WebSocket output message is received. This is not
    sensor-exposure latency.
    """
    input_data, input_ends, input_times = _flatten_chunks(input_chunks, "input")
    output_data, output_ends, output_times = _flatten_chunks(output_chunks, "output")
    send_started_ends: list[int] | None = None
    send_started_times: list[float] | None = None
    if send_started_chunks is not None:
        send_started_data, send_started_ends, send_started_times = _flatten_chunks(
            send_started_chunks, "send_started",
        )
        if send_started_data != input_data:
            raise ValueError("send-start chunks must contain the same bytes as input chunks")
    input_nals = _nal_completion_offsets(input_data)
    output_nals = _nal_completion_offsets(output_data)
    if (len(input_nals) != len(output_nals)
            or [nal_type for nal_type, _ in input_nals] != [nal_type for nal_type, _ in output_nals]):
        raise ValueError("input/output NAL count or type differs; cannot pair channel latency samples")

    latencies_ms = [
        (_arrival_at_offset(output_offset, output_ends, output_times)
         - _arrival_at_offset(input_offset, input_ends, input_times)) * 1000.0
        for (_, input_offset), (_, output_offset) in zip(input_nals, output_nals)
    ]
    if any(not math.isfinite(value) or value < 0 for value in latencies_ms):
        raise ValueError("measured NAL channel latency must be finite and non-negative")
    ordered = sorted(latencies_ms)

    def summarize(values: list[float], prefix: str) -> dict[str, float]:
        ordered_values = sorted(values)

        def percentile(percent: int) -> float:
            rank = math.ceil(percent * len(ordered_values) / 100)
            return round(ordered_values[max(rank - 1, 0)], 4)

        return {
            f"{prefix}_p50_ms": percentile(50),
            f"{prefix}_p95_ms": percentile(95),
        }

    def percentile(percent: int) -> float:
        rank = math.ceil(percent * len(ordered) / 100)
        return round(ordered[max(rank - 1, 0)], 4)

    measurement_by_transport = {
        "testclient": "ffmpeg_stdout_nal_completion_to_websocket_testclient_nal_completion",
        "loopback_tcp": "ffmpeg_stdout_nal_completion_to_websocket_loopback_tcp_nal_completion",
    }
    if output_transport not in measurement_by_transport:
        raise ValueError("output_transport must be 'testclient' or 'loopback_tcp'")
    result: dict[str, float | int | str] = {
        "measurement": measurement_by_transport[output_transport],
        "nal_count": len(ordered),
        "p50_ms": percentile(50),
        "p95_ms": percentile(95),
    }
    input_nal_times = [
        _arrival_at_offset(offset, input_ends, input_times) for _, offset in input_nals
    ]
    output_nal_times = [
        _arrival_at_offset(offset, output_ends, output_times) for _, offset in output_nals
    ]
    input_interarrivals = [
        (later - earlier) * 1000.0 for earlier, later in zip(input_nal_times, input_nal_times[1:])
    ]
    output_interarrivals = [
        (later - earlier) * 1000.0 for earlier, later in zip(output_nal_times, output_nal_times[1:])
    ]
    if any(not math.isfinite(value) or value < 0 for value in input_interarrivals + output_interarrivals):
        raise ValueError("NAL completion interarrival samples must be finite and non-negative")
    result.update(summarize(input_interarrivals or [0.0], "input_nal_completion_interarrival"))
    result.update(summarize(output_interarrivals or [0.0], "output_nal_completion_interarrival"))
    if send_started_ends is not None and send_started_times is not None:
        read_to_send_start_ms: list[float] = []
        send_start_to_receive_ms: list[float] = []
        for (_, input_offset), (_, output_offset) in zip(input_nals, output_nals):
            input_time = _arrival_at_offset(input_offset, input_ends, input_times)
            send_start_time = _arrival_at_offset(input_offset, send_started_ends, send_started_times)
            output_time = _arrival_at_offset(output_offset, output_ends, output_times)
            read_to_send_start_ms.append((send_start_time - input_time) * 1000.0)
            send_start_to_receive_ms.append((output_time - send_start_time) * 1000.0)
        if any(not math.isfinite(value) or value < 0 for value in read_to_send_start_ms + send_start_to_receive_ms):
            raise ValueError("measured NAL send-start decomposition must be finite and non-negative")
        result.update(summarize(read_to_send_start_ms, "camera_read_to_send_start"))
        result.update(summarize(send_start_to_receive_ms, "send_start_to_client_receive"))
    return result
