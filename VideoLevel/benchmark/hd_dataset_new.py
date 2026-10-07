"""Native high-resolution test material: the first frames of Xiph camera-captured 1080p/720p sequences.

    py -3.12 -m benchmark.hd_dataset_new [--frames 60]

Only the first N frames are fetched (HTTP Range on the uncompressed Y4M), so each
1080p sequence costs about 190 MB instead of 1.5 GB. Files land in data/raw_hd/
(git-ignored) and are verified frame by frame (every frame must start with FRAME).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw_hd"
BASE_URL = "https://media.xiph.org/video/derf/y4m/"
# Camera-captured natural content only (no animation), 4:2:0.
SEQUENCES = (
    "crowd_run_1080p50", "ducks_take_off_1080p50", "in_to_tree_1080p50", "old_town_cross_1080p50",
    "park_joy_1080p50", "pedestrian_area_1080p25", "riverbed_1080p25", "rush_hour_1080p25",
    "station2_1080p25", "sunflower_1080p25", "tractor_1080p25", "blue_sky_1080p25",
    "720p50_mobcal_ter", "720p50_parkrun_ter", "720p50_shields_ter", "720p5994_stockholm_ter",
    "vidyo1_720p_60fps", "vidyo3_720p_60fps", "vidyo4_720p_60fps",
)
MAX_HEADER = 512


CHUNK = 4 * 1024 * 1024
PARALLEL = 16  # the server throttles each connection (~10 KB/s), not the client


def _get_once(url: str, first: int, last: int) -> bytes:
    request = urllib.request.Request(url, headers={"Range": f"bytes={first}-{last}"})
    with urllib.request.urlopen(request, timeout=300) as response:
        if response.status != 206:
            raise RuntimeError(f"{url}: HTTP {response.status} (range requests required)")
        data = response.read()
    if len(data) != last - first + 1:
        raise RuntimeError(f"{url}: short read {len(data)} for {first}-{last}")
    return data


def _get(url: str, first: int, last: int, attempts: int = 5) -> bytes:
    """Byte range [first, last] fetched as parallel 4 MB chunks, each retried on failure."""
    spans = [(start, min(last, start + CHUNK - 1)) for start in range(first, last + 1, CHUNK)]

    def fetch_span(span: tuple[int, int]) -> bytes:
        for attempt in range(attempts):
            try:
                return _get_once(url, *span)
            except (OSError, RuntimeError):
                if attempt == attempts - 1:
                    raise
        raise AssertionError("unreachable")

    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        return b"".join(pool.map(fetch_span, spans))


def parse_header(head: bytes) -> tuple[int, int, int, dict[str, str]]:
    """(header length incl. newline, width, height, tags) of a Y4M stream; 4:2:0 only."""
    end = head.index(b"\n")
    fields = head[:end].decode("ascii").split()
    if fields[0] != "YUV4MPEG2":
        raise ValueError("not a YUV4MPEG2 stream")
    tags = {item[0]: item[1:] for item in fields[1:]}
    chroma = tags.get("C", "420")
    if not chroma.startswith("420"):
        raise ValueError(f"chroma {chroma} is not 4:2:0")
    return end + 1, int(tags["W"]), int(tags["H"]), tags


def fetch(name: str, frames: int) -> dict:
    url = BASE_URL + name + ".y4m"
    target = OUT / f"{name}_{frames}f.y4m"
    head = _get(url, 0, MAX_HEADER - 1)
    header_len, width, height, tags = parse_header(head)
    frame_bytes = 6 + width * height * 3 // 2  # "FRAME\n" + Y + U + V
    if head[header_len:header_len + 6] != b"FRAME\n":
        raise ValueError(f"{name}: frames carry parameters; not supported")
    total = header_len + frames * frame_bytes
    if not (target.is_file() and target.stat().st_size == total):
        data = _get(url, 0, total - 1)
        if len(data) != total:
            raise RuntimeError(f"{name}: got {len(data)} bytes, expected {total} (sequence shorter?)")
        for index in range(frames):
            start = header_len + index * frame_bytes
            if data[start:start + 6] != b"FRAME\n":
                raise RuntimeError(f"{name}: frame {index} marker missing")
        partial = target.with_suffix(".part")
        partial.write_bytes(data)
        partial.replace(target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return {"name": name, "file": str(target.relative_to(ROOT)), "width": width, "height": height,
            "fps": tags.get("F"), "frames": frames, "bytes": total, "sha256": digest, "url": url}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frames", type=int, default=60)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name in SEQUENCES:
        try:
            entry = fetch(name, args.frames)
        except (OSError, ValueError, RuntimeError) as error:
            entry = {"name": name, "error": str(error)}
        manifest.append(entry)
        print(json.dumps({k: entry.get(k) for k in ("name", "width", "height", "bytes", "error")}), flush=True)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
