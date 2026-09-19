"""Measured acceptance benchmark for native pixel-domain edge embedding.

The benchmark sends YUV420P frames through the long-lived native QIM process.
It reports only raw-pixel embedding latency and quality. Codec robustness is a
separate acceptance step because it depends on the target H.264 encoder.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from pathlib import Path

import numpy as np


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


def assess_pixel_realtime(
    *, p95_latency_s: float, dropped_frames: int, psnr_db: float,
    max_latency_s: float, min_psnr_db: float,
) -> str:
    result = assess_realtime(
        p95_latency_s=p95_latency_s,
        dropped_segments=dropped_frames,
        max_latency_s=max_latency_s,
    )
    if result != "pass":
        return result
    return "pass" if psnr_db >= min_psnr_db else "fail_quality"


def _default_embedder() -> Path:
    return ROOT / "native" / "edge-build" / "Release" / "zkstego_pixel_embed.exe"


def _synthetic_yuv420p(width: int, height: int, frames: int) -> bytes:
    y = np.arange(width * height, dtype=np.uint32).reshape(height, width)
    luma = ((y * 17 + (y // width) * 11) % 220 + 16).astype(np.uint8)
    chroma = np.full(width * height // 2, 128, dtype=np.uint8)
    frame = luma.tobytes() + chroma.tobytes()
    return frame * frames


def _psnr(reference: np.ndarray, modified: np.ndarray) -> float:
    mse = float(np.mean((reference.astype(np.float32) - modified.astype(np.float32)) ** 2))
    return float("inf") if mse == 0 else 10.0 * math.log10((255.0 * 255.0) / mse)


def measure(
    embedder: Path, *, width: int, height: int, frames: int, payload_hex: str,
    fps: float, max_latency_s: float, min_psnr_db: float,
) -> dict:
    source = _synthetic_yuv420p(width, height, frames)
    started = time.perf_counter()
    result = subprocess.run(
        [str(embedder), "--width", str(width), "--height", str(height),
         "--payload-hex", payload_hex, "--metrics"],
        input=source,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    wall_s = time.perf_counter() - started
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
    if len(result.stdout) != len(source):
        raise RuntimeError("native pixel embedder changed raw frame stream length")
    try:
        metrics = json.loads(result.stderr.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"native pixel metrics were invalid: {result.stderr!r}") from error

    luma_bytes = width * height
    frame_bytes = luma_bytes * 3 // 2
    original_luma = np.frombuffer(source, dtype=np.uint8).reshape(frames, frame_bytes)[:, :luma_bytes]
    stego_luma = np.frombuffer(result.stdout, dtype=np.uint8).reshape(frames, frame_bytes)[:, :luma_bytes]
    psnr_db = _psnr(original_luma, stego_luma)
    p95_s = float(metrics["p95_embed_ms"]) / 1000.0
    frame_interval_s = 1.0 / fps
    acceptance = assess_pixel_realtime(
        p95_latency_s=p95_s,
        dropped_frames=0,
        psnr_db=psnr_db,
        max_latency_s=max_latency_s,
        min_psnr_db=min_psnr_db,
    )
    return {
        "embedder": str(embedder),
        "pixel_domain": "Y luma QIM; no SEI or H.264 metadata payload",
        "width": width,
        "height": height,
        "frames": frames,
        "payload_bytes": len(payload_hex) // 2,
        "input_bytes": len(source),
        "output_bytes": len(result.stdout),
        "wall_s": round(wall_s, 6),
        "stream_mib_per_s": round((len(source) / (1024 * 1024)) / wall_s, 3) if wall_s else None,
        "native_p95_embed_s": round(p95_s, 7),
        "psnr_db_raw_y": round(psnr_db, 4),
        "target_fps": fps,
        "frame_interval_s": round(frame_interval_s, 7),
        "pixel_acceptance": acceptance,
        "scope": "Raw YUV420P pixel embedding; validate after the target H.264 encode before claiming codec robustness.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure native pixel QIM edge embedding")
    parser.add_argument("--embedder", type=Path, default=_default_embedder())
    parser.add_argument("--width", type=int, default=352)
    parser.add_argument("--height", type=int, default=288)
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--payload-hex", default="a5" * 129, help="proof bytes encoded as hex")
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--max-frame-latency-s", type=float)
    parser.add_argument("--min-psnr-db", type=float, default=40.0)
    args = parser.parse_args()
    if args.width <= 0 or args.height <= 0 or args.width % 2 or args.height % 2 or args.frames < 1 or args.fps <= 0:
        parser.error("dimensions must be positive even values; frames and FPS must be positive")
    if not args.embedder.is_file():
        parser.error("native pixel embedder must exist")
    max_latency = args.max_frame_latency_s if args.max_frame_latency_s is not None else 1.0 / args.fps
    report = measure(
        args.embedder, width=args.width, height=args.height, frames=args.frames,
        payload_hex=args.payload_hex, fps=args.fps, max_latency_s=max_latency,
        min_psnr_db=args.min_psnr_db,
    )
    RESULT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["pixel_acceptance"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
