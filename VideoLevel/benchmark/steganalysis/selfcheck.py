"""End-to-end self-check: tiny CIF dataset, all four detectors, feature timings.

    py -3.12 -m benchmark.steganalysis.selfcheck [--frames 30] [--caps 2000,64]
        [--sources hall_monitor_cif,container_cif,akiyo_cif] [--detectors cavlc,spam,srmlite,cnn]

Covers are libx264 baseline all-intra (QP 22) encodes; every cover receives a
random keyed payload filling its capacity at each per-IDR cap. Sources are
assigned to train / val / test in the order given (one source per split for
three sources). Everything is written below the git-ignored cache directory.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np

from .cavlc_trace import load_trace
from .common import BLIND_BITS_EXE, DEFAULT_CACHE_DIR, INSPECT_EXE, REPO_ROOT, decode_luma, load_manifest
from .evaluate import parse_args as evaluate_args
from .evaluate import run as evaluate_run
from .features_cavlc import extract_cavlc_features
from .features_pixel import spam686, srm_lite

MAX_PAYLOAD_BYTES = 4096
FRAME_HEADER_BYTES = 3
X264_ARGS = ["-c:v", "libx264", "-preset", "medium", "-profile:v", "baseline", "-qp", "22", "-g", "1",
             "-bf", "0", "-x264-params", "keyint=1:min-keyint=1:scenecut=0:slices=1", "-f", "h264"]


def encode_cover(source: Path, target: Path, frames: int, scale: str | None = None) -> None:
    filters = ["-vf", f"scale={scale}"] if scale else []
    command = ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-frames:v", str(frames), *filters,
               *X264_ARGS, str(target)]
    subprocess.run(command, check=True)


def segment_capacities(stream: Path, cap: int) -> list[int]:
    result = subprocess.run([str(INSPECT_EXE), str(stream), "--segments", str(cap)], check=True,
                            capture_output=True, text=True)
    return [int(segment["capacity"]) for segment in json.loads(result.stdout)["segments"]]


def embed(cover: Path, stego: Path, cap: int, rng: np.random.Generator) -> list[int]:
    """Embed a capacity-filling random payload; return the frame indices carrying bits."""
    capacities = segment_capacities(cover, cap)
    payload_bytes = min(MAX_PAYLOAD_BYTES, sum(capacities) // 8 - FRAME_HEADER_BYTES)
    if payload_bytes < 1:
        raise RuntimeError(f"{cover}: capacity {sum(capacities)} bits is too small")
    key = rng.bytes(32).hex()
    payload = rng.bytes(payload_bytes).hex()
    subprocess.run([str(BLIND_BITS_EXE), "embed-stream-auth-stdin", str(cover), str(stego), str(cap)],
                   input=f"{key}\n{payload}\n", check=True, capture_output=True, text=True)
    needed, carried = (payload_bytes + FRAME_HEADER_BYTES) * 8, []
    for frame, capacity in enumerate(capacities):
        if needed <= 0:
            break
        carried.append(frame)
        needed -= capacity
    return carried


def changed_sign_share(cover: Path, stego: Path) -> float:
    """Share of first-T1 candidates whose sign differs between cover and stego."""
    a, b = load_trace(cover), load_trace(stego)
    if a.count != b.count or not np.array_equal(a.mb, b.mb):
        raise RuntimeError("cover and stego traces are not aligned")
    return float(np.mean(a.bit != b.bit))


def build_dataset(root: Path, sources: Sequence[str], frames: int, caps: Sequence[int], seed: int
                  ) -> tuple[Path, list[dict]]:
    rng = np.random.default_rng(seed)
    root.mkdir(parents=True, exist_ok=True)
    splits = ("train", "val", "test")
    entries, stats = [], []
    for position, source in enumerate(sources):
        split = splits[min(position, 2)] if len(sources) >= 3 else ("train", "test")[min(position, 1)]
        cover = root / f"{source}_cover.h264"
        encode_cover(REPO_ROOT / "data" / "raw" / f"{source}.y4m", cover, frames)
        for cap in caps:
            stego = root / f"{source}_cap{cap}.h264"
            carried = embed(cover, stego, cap, rng)
            stats.append({"source": source, "cap": cap, "frames_with_bits": len(carried),
                          "changed_first_t1_share": changed_sign_share(cover, stego)})
            entries.append({"pair_id": f"{source}_cap{cap}", "source": source, "split": split,
                            "method": "t1sign", "rate": f"cap{cap}", "cover": cover.name, "stego": stego.name,
                            "width": 352, "height": 288, "frames": carried})
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return manifest, stats


def _per_frame(function: Callable[[], object], repeats: int) -> float:
    started = time.perf_counter()
    for _ in range(repeats):
        function()
    return (time.perf_counter() - started) / repeats


def _resolution_timing(stream: Path, size: tuple[int, int], frames: int) -> dict[str, float]:
    indices = list(range(frames))
    timing = {
        "decode_luma": _per_frame(lambda: decode_luma(stream, size[0], size[1], indices), 1) / frames,
        "cavlc_trace_and_features": _per_frame(
            lambda: extract_cavlc_features(load_trace(stream), indices), 1) / frames,
    }
    plane = decode_luma(stream, size[0], size[1], [0])[0]
    timing["spam686"] = _per_frame(lambda: spam686(plane), 3)
    timing["srmlite"] = _per_frame(lambda: srm_lite(plane), 3)
    timing.update(_cnn_timing(plane))
    return timing


def feature_timings(root: Path, frames: int = 3) -> dict[str, dict[str, float]]:
    """Seconds per frame of each feature extractor at CIF and (upscaled) 1080p."""
    source = REPO_ROOT / "data" / "raw" / "foreman_cif.y4m"
    timings: dict[str, dict[str, float]] = {}
    for label, scale, size in (("cif", None, (352, 288)), ("1080p", "1920:1080", (1920, 1080))):
        stream = root / f"timing_{label}.h264"
        encode_cover(source, stream, frames, scale)
        timings[label] = _resolution_timing(stream, size, frames)
    return timings


def _cnn_timing(plane: np.ndarray) -> dict[str, float]:
    try:
        import torch

        from .cnn import CnnConfig, XuNet, cut_tiles, tile_scores
    except ImportError:
        return {}
    config = CnnConfig()
    model = XuNet().to(config.device)
    tiles = cut_tiles(plane, 256, config.max_tiles)
    tile_scores(model, tiles, config)
    if config.device == "cuda":
        torch.cuda.synchronize()
    return {"cnn_inference_8_tiles" if tiles.shape[0] == 8 else f"cnn_inference_{tiles.shape[0]}_tiles":
            _per_frame(lambda: tile_scores(model, tiles, config), 5)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sources", default="hall_monitor_cif,container_cif,akiyo_cif")
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--caps", default="2000,64")
    parser.add_argument("--detectors", default="cavlc,spam,srmlite,cnn")
    parser.add_argument("--root", type=Path, default=DEFAULT_CACHE_DIR / "selfcheck")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--skip-timing", action="store_true")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    caps = [int(c) for c in args.caps.split(",")]
    manifest, stats = build_dataset(args.root, args.sources.split(","), args.frames, caps, args.seed)
    for row in stats:
        print(f"{row['source']:<16} cap {row['cap']:>5}: {row['frames_with_bits']:>3} frames carry bits, "
              f"{100 * row['changed_first_t1_share']:.2f}% of first-T1 signs changed")
    results: dict = {"manifest": str(manifest), "embedding": stats, "detectors": {}}
    for detector in args.detectors.split(","):
        started = time.perf_counter()
        reports = evaluate_run(load_manifest(manifest), evaluate_args(["--manifest", str(manifest), "--detector", detector,
                                                                "--seed", str(args.seed % 1000)]))
        results["detectors"][detector] = reports
        for r in reports:
            print(f"{detector:<8} {r['rate']:<8} test pairs {r['n_test_pairs']} frames {r['n_test_frames']:>3}  "
                  f"AUC {r['frame_auc']:.3f}  P_E {r['frame_p_e']:.3f}  "
                  f"(stream AUC {r['stream_auc']:.2f})  [{time.perf_counter() - started:.1f}s]")
    if not args.skip_timing:
        results["seconds_per_frame"] = feature_timings(args.root)
        for label, values in results["seconds_per_frame"].items():
            print(label, {k: round(v * 1000, 1) for k, v in values.items()}, "ms/frame")
    out = args.root / "selfcheck_results.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
