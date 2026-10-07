"""End-to-end check of the native channel parameters (--select, --key-mode) on real covers.

    py -3.12 -m benchmark.channel_options_new [--dataset cif|hd] [--limit N]

For each cover (x264 medium, QP 22, all-intra, 60 frames) and each of the four
parameter combinations the native codec embeds a 201-byte payload (the size of a
68-byte message with its proof) at 64 bits per IDR, then: PSNR-Y of the carrying
frames, extraction with the master key, and in per-video mode the verification token:
extraction and video digest with the token must equal those with the key, and the
token of one video must fail on the next one. Writes
benchmark/results/stego_compare/channel_options_<dataset>.jsonl.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

from benchmark.distortion_model_new import decode_planes, psnr_from_sse
from benchmark.media_benchmark_new import _native_binary
from benchmark.stego_compare_new import OUT, _dimensions, encode_cover, sources

PAYLOAD_BYTES = 201
CAP = 64
FRAME_BITS = 8 * (3 + PAYLOAD_BYTES)


def _native(args: list[str], stdin: str) -> tuple[subprocess.CompletedProcess[bytes], float]:
    started = time.perf_counter()
    result = subprocess.run([str(_native_binary()), *args], input=stdin.encode(), capture_output=True,
                            check=False, timeout=1800)
    return result, time.perf_counter() - started


def _flags(select: str, key_mode: str) -> list[str]:
    return ["--select", select, "--key-mode", key_mode]


def run_cover(cover: Path, width: int, height: int, folder: Path, key: bytes, payload: bytes) -> tuple[list[dict], dict[str, Path]]:
    base = decode_planes(cover, width, height)
    rows, stegos = [], {}
    for select in ("random", "low-drift"):
        for key_mode in ("master", "per-video"):
            flags = _flags(select, key_mode)
            stego = folder / f"{cover.stem}_{select}_{key_mode}.h264"
            embed, embed_s = _native(["embed-stream-auth-stdin", str(cover), str(stego), str(CAP), *flags],
                                     f"{key.hex()}\n{payload.hex()}\n")
            if embed.returncode:
                raise RuntimeError(embed.stderr.decode(errors="replace"))
            stegos[f"{select}/{key_mode}"] = stego
            extract, extract_s = _native(["extract-stream-auth", str(stego), "-", "4096", str(CAP), *flags], key.hex() + "\n")
            planes = decode_planes(stego, width, height)
            sse = ((planes[0] - base[0]) ** 2).reshape(planes[0].shape[0], -1).sum(axis=1)
            carrying = [float(v) for v in sse if v > 0]
            row = {"cover": cover.stem, "width": width, "height": height, "select": select, "key_mode": key_mode,
                   "embed_s": embed_s, "extract_s": extract_s,
                   "extract_ok": extract.returncode == 0 and extract.stdout.decode().strip() == payload.hex(),
                   "carrying_frames": len(carrying),
                   "psnr_y_carrying_mean_mse": psnr_from_sse(float(np.mean(carrying)), width * height) if carrying else None,
                   "psnr_y_carrying_min": min(psnr_from_sse(v, width * height) for v in carrying) if carrying else None,
                   "size_equal": stego.stat().st_size == cover.stat().st_size}
            if key_mode == "per-video":
                token, token_s = _native(["video-token", str(stego)], key.hex() + "\n")
                token_line = "token:" + token.stdout.decode().strip() + "\n"
                by_token, _ = _native(["extract-stream-auth", str(stego), "-", "4096", str(CAP), *flags], token_line)
                digest_key, digest_s = _native(["video-digest", str(stego), str(FRAME_BITS), str(CAP), *flags],
                                               key.hex() + "\n")
                digest_token, _ = _native(["video-digest", str(stego), str(FRAME_BITS), str(CAP), *flags], token_line)
                row.update({"token_s": token_s, "digest_s": digest_s,
                            "token_extract_ok": by_token.returncode == 0
                            and by_token.stdout.decode().strip() == payload.hex(),
                            "token_digest_equal": digest_key.returncode == 0 and digest_key.stdout == digest_token.stdout})
            rows.append(row)
    return rows, stegos


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", choices=("cif", "hd"), default="cif")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    rng = np.random.default_rng(20261006)
    covers = sources(args.dataset)[: args.limit or None]
    out = OUT / f"channel_options_{args.dataset}.jsonl"
    with tempfile.TemporaryDirectory() as tmp, out.open("w", encoding="utf-8") as sink:
        folder = Path(tmp)
        previous: dict[str, Path] | None = None
        encoded = [(encode_cover(src, 22, 1, 60), *_dimensions(src)) for src in covers]
        for cover, width, height in encoded:
            key, payload = rng.bytes(32), rng.bytes(PAYLOAD_BYTES)
            rows, stegos = run_cover(cover, width, height, folder, key, payload)
            if previous is not None:  # this cover's token must fail on the previous cover's stego stream
                token, _ = _native(["video-token", str(stegos["random/per-video"])], key.hex() + "\n")
                foreign, _ = _native(["extract-stream-auth", str(previous["random/per-video"]), "-", "4096", str(CAP),
                                      *_flags("random", "per-video")], "token:" + token.stdout.decode().strip() + "\n")
                reason = foreign.stderr.decode(errors="replace").strip()
                # A rejection is the frame check failing (exit 2, version/length), not a crash.
                rows[1]["foreign_token_rejected"] = foreign.returncode == 2 and any(
                    marker in reason.lower() for marker in ("version is invalid", "length exceeds", "length is invalid"))
                rows[1]["foreign_token_reason"] = reason[-200:]
            previous = stegos
            for row in rows:
                sink.write(json.dumps(row) + "\n")
            sink.flush()
            print(cover.stem, [(r["select"], r["key_mode"], r["extract_ok"], r.get("token_extract_ok"),
                                round(r["psnr_y_carrying_mean_mse"] or 0, 2)) for r in rows], flush=True)


if __name__ == "__main__":
    main()
