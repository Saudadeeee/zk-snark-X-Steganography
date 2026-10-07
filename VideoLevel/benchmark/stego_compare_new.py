"""Quality comparison of selection methods on CIF and native HD material, several QPs and GOPs.

    py -3.12 -m benchmark.stego_compare_new --dataset cif|hd [--qps 18 22 28 34] [--gops 1 30]
        [--methods random low-drift sequential ...] [--frames 60] [--workers 4] [--keep-stego DIR]

For each cover (x264 medium, Baseline, given QP and GOP) every method embeds random
bits at two rates per IDR: the system default of 64 bits and 5% of the IDR's
candidates. Measured per run: candidates, changed signs, PSNR-Y and SSIM-Y of every
decoded frame against the cover (P frames included: drift from the IDR propagates),
and the size change. Rows append to benchmark/results/stego_compare/<dataset>.jsonl.
"""
from __future__ import annotations

import argparse
import json
import math
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from benchmark.distortion_model_new import _run, decode_planes, psnr_from_sse
from benchmark.media_benchmark_new import _tool
from benchmark.stego_embed_new import candidates, embed
from benchmark.stego_methods_new import METHODS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "benchmark" / "results" / "stego_compare"
CACHE = ROOT / "benchmark" / "results" / "stego_cache"
CIF_SOURCES = ("akiyo", "city", "coastguard", "container", "deadline", "football", "foreman", "hall_monitor")
RATES = {"cap64": lambda n: 64, "rate5": lambda n: max(1, round(0.05 * n))}


def sources(dataset: str) -> list[Path]:
    if dataset == "cif":
        return [ROOT / "data" / "raw" / f"{name}_cif.y4m" for name in CIF_SOURCES]
    manifest = json.loads((ROOT / "data" / "raw_hd" / "manifest.json").read_text(encoding="utf-8"))
    return [ROOT / entry["file"] for entry in manifest if "error" not in entry]


def encode_cover(source: Path, qp: int, gop: int, frames: int, preset: str = "medium") -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / f"{source.stem}__{preset}_qp{qp}_g{gop}_{frames}f.h264"
    if not target.is_file():
        partial = target.with_suffix(".part.h264")
        _run([_tool("ffmpeg"), "-v", "error", "-y", "-i", str(source), "-frames:v", str(frames), "-c:v", "libx264",
              "-preset", preset, "-profile:v", "baseline", "-qp", str(qp), "-g", str(gop), "-bf", "0",
              "-threads", "1", "-pix_fmt", "yuv420p", "-an", "-x264-params",
              f"keyint={gop}:min-keyint={gop}:scenecut=0:slices=1:threads=1", "-f", "h264", str(partial)])
        partial.replace(target)
    return target


def ssim(a: np.ndarray, b: np.ndarray) -> float:
    """Single-scale SSIM of two 8-bit planes (Gaussian window 11, sigma 1.5)."""
    a, b = a.astype(np.float64), b.astype(np.float64)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    blur = lambda x: cv2.GaussianBlur(x, (11, 11), 1.5)  # noqa: E731
    mu_a, mu_b = blur(a), blur(b)
    var_a, var_b, cov = blur(a * a) - mu_a ** 2, blur(b * b) - mu_b ** 2, blur(a * b) - mu_a * mu_b
    value = ((2 * mu_a * mu_b + c1) * (2 * cov + c2)) / ((mu_a ** 2 + mu_b ** 2 + c1) * (var_a + var_b + c2))
    return float(value.mean())


def _dimensions(source: Path) -> tuple[int, int]:
    header = source.open("rb").readline().decode("ascii").split()
    tags = {item[0]: item[1:] for item in header[1:]}
    return int(tags["W"]), int(tags["H"])


def run_cover(job: tuple) -> list[dict]:
    dataset, source, qp, gop, frames, methods, keep = job
    width, height = _dimensions(source)
    cover = encode_cover(source, qp, gop, frames)
    cands = candidates(cover, workers=2)
    base = decode_planes(cover, width, height)
    rows = []
    with tempfile.TemporaryDirectory() as folder:
        for method in methods:
            for rate, bits in RATES.items():
                key = f"{source.stem}|{qp}|{gop}|{method}|{rate}".encode()
                name = f"{source.stem}__qp{qp}_g{gop}__{method}__{rate}.h264"
                out = (Path(keep) / name) if keep else Path(folder) / name
                stats = embed(cover, out, cands, METHODS[method], bits, key.ljust(32, b"\0")[:32])
                planes = decode_planes(out, width, height)
                sse = ((planes[0] - base[0]) ** 2).reshape(planes[0].shape[0], -1).sum(axis=1)
                psnr = [psnr_from_sse(float(v), width * height) for v in sse]
                idr = sorted(stats["frames"])
                rows.append({
                    "dataset": dataset, "source": source.stem, "width": width, "height": height, "qp": qp,
                    "gop": gop, "frames": len(psnr), "method": method, "rate": rate,
                    "candidates_per_idr": float(np.mean([stats["frames"][f]["candidates"] for f in idr])),
                    "embedded": stats["embedded"], "changed": stats["changed"],
                    "bytes_delta": stats["stego_bytes"] - stats["cover_bytes"],
                    "psnr_y": psnr, "psnr_y_min": min(psnr),
                    "psnr_y_mean_mse": psnr_from_sse(float(sse.mean()), width * height),
                    # SSIM of the three lowest-PSNR frames (where the minimum lies; all frames is too slow at 1080p)
                    "ssim_y_min": min(ssim(planes[0][i], base[0][i])
                                      for i in sorted(range(len(psnr)), key=psnr.__getitem__)[:3]),
                })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", choices=("cif", "hd"), required=True)
    parser.add_argument("--qps", type=int, nargs="+", default=[18, 22, 28, 34])
    parser.add_argument("--gops", type=int, nargs="+", default=[1, 30])
    parser.add_argument("--methods", nargs="+", default=list(METHODS))
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--keep-stego", default="")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    results = OUT / f"{args.dataset}.jsonl"
    done: dict[tuple[str, int, int], set[tuple[str, str]]] = {}
    if results.is_file():  # resume: skip covers whose rows are all present
        for line in results.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            done.setdefault((row["source"], row["qp"], row["gop"]), set()).add((row["method"], row["rate"]))
    wanted = {(method, rate) for method in args.methods for rate in RATES}
    jobs = [(args.dataset, src, qp, gop, args.frames, args.methods, args.keep_stego)
            for src in sources(args.dataset) for qp in args.qps for gop in args.gops
            if not wanted <= done.get((src.stem, qp, gop), set())]
    with (OUT / f"{args.dataset}.jsonl").open("a", encoding="utf-8") as sink, \
            ProcessPoolExecutor(max_workers=args.workers) as pool:
        for rows in pool.map(run_cover, jobs):
            for row in rows:
                sink.write(json.dumps(row) + "\n")
            sink.flush()
            first = rows[0]
            print(f"{first['source']} qp{first['qp']} g{first['gop']}: " + ", ".join(
                f"{r['method']}/{r['rate']} {r['psnr_y_mean_mse']:.1f}" for r in rows if math.isfinite(r['psnr_y_min'])),
                flush=True)


if __name__ == "__main__":
    main()
