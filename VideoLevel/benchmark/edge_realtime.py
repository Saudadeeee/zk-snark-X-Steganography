"""Measured acceptance benchmark for the edge camera transport path.

It measures native Annex-B relay throughput and Python segmenter ingress cost.
It does not claim CAVLC proof embedding is real-time; that path remains
separately measured by SEC6/SEC8 until a native CAVLC patcher is available.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

from src.edge.realtime import AnnexBSegmenter


ROOT = Path(__file__).resolve().parent.parent
RESULT = ROOT / "benchmark" / "results" / "edge_realtime_data.json"


def percentile(samples: list[float], percent: float) -> float:
    if not samples:
        raise ValueError("samples must not be empty")
    if not 0 < percent <= 100:
        raise ValueError("percent must be in (0, 100]")
    ordered = sorted(float(value) for value in samples)
    return ordered[max(0, math.ceil(percent / 100 * len(ordered)) - 1)]


def assess_realtime(*, p95_latency_s: float, dropped_segments: int, max_latency_s: float) -> str:
    if dropped_segments:
        return "fail_drops"
    if p95_latency_s > max_latency_s:
        return "fail_latency"
    return "pass"


def _default_relay() -> Path:
    candidate = ROOT / "native" / "edge-build" / "Release" / "zkstego_annexb_relay.exe"
    if candidate.exists():
        return candidate
    return ROOT / "native" / "build" / "Release" / "zkstego_annexb_relay.exe"


def measure(input_path: Path, relay: Path, *, chunk_bytes: int, fps: float, max_latency_s: float) -> dict:
    source = input_path.read_bytes()
    started = time.perf_counter()
    result = subprocess.run(
        [str(relay), "--sei-payload-hex", "5a4b535445474f"],
        input=source,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    relay_s = time.perf_counter() - started
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())

    segmenter = AnnexBSegmenter()
    ingress: list[float] = []
    emitted = 0
    for offset in range(0, len(source), chunk_bytes):
        t0 = time.perf_counter()
        emitted += len(segmenter.feed(source[offset:offset + chunk_bytes]))
        ingress.append(time.perf_counter() - t0)

    ingress_p95_s = percentile(ingress, 95)
    frame_interval_s = 1.0 / fps
    return {
        "input": str(input_path),
        "relay": str(relay),
        "input_bytes": len(source),
        "output_bytes": len(result.stdout),
        "relay_wall_s": round(relay_s, 6),
        "relay_mib_per_s": round((len(source) / (1024 * 1024)) / relay_s, 3) if relay_s else None,
        "ingress_chunks": len(ingress),
        "ingress_p95_s": round(ingress_p95_s, 7),
        "segment_count": emitted,
        "target_fps": fps,
        "frame_interval_s": round(frame_interval_s, 7),
        "transport_acceptance": assess_realtime(
            p95_latency_s=ingress_p95_s,
            dropped_segments=0,
            max_latency_s=max_latency_s,
        ),
        "scope": "Annex-B transport only; CAVLC proof embedding is not included in this acceptance result.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure edge native relay and segmenter latency")
    parser.add_argument("--input", type=Path, required=True, help="Raw Annex-B H.264 input")
    parser.add_argument("--relay", type=Path, default=_default_relay())
    parser.add_argument("--chunk-bytes", type=int, default=4096)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--max-latency-s", type=float, default=1.0)
    args = parser.parse_args()
    if args.chunk_bytes < 1 or args.fps <= 0 or args.max_latency_s <= 0:
        parser.error("chunk size, FPS, and max latency must be positive")
    if not args.input.is_file() or not args.relay.is_file():
        parser.error("input and relay must exist")
    report = measure(args.input, args.relay, chunk_bytes=args.chunk_bytes, fps=args.fps, max_latency_s=args.max_latency_s)
    RESULT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["transport_acceptance"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
