"""Original (CIF-grid) vs SPS-geometry carrier order: capacity and decoded quality.

For one short all-intra cut it measures the stable carrier capacity per
segment and per picture, then embeds the same random payload with each
carrier contract at several fill levels (fraction of every segment's
carriers the chunk uses), with the same sync key and chunk layout, and
reports luma PSNR of the changed frames and of the worst frame, the time per
frame and the peak memory.  The extraction from the stego is checked at the
highest fill level.  No proof is generated: the order only decides which
carriers a prefix uses, which is what the quality depends on.

    python -m benchmark.latticezk_hd_order --video tmp/hd/park_joy_720p_q22_10f.h264 \
        --frames-per-segment 5 --carriers magnitude magnitude-geo --fill 0.25 0.5 0.9 \
        --output benchmark/results/q2/hd_order_parkjoy720p.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.latticezk_capacity_scan import CHUNK_FRAMING_BYTES, UNBOUNDED_BITS  # noqa: E402
from benchmark.latticezk_quality import per_frame_luma_mse, summarize_luma_mse  # noqa: E402
from benchmark.latticezk_video_e2e import CARRIER_CONTRACTS  # noqa: E402
from src.transport import blind_sync_streaming as transport  # noqa: E402
from src.transport.blind_sync import derive_blind_positions_operating_contract  # noqa: E402
from src.core.analysis_cache import (  # noqa: E402
    clear_video_analysis_cache,
    load_or_build_reconstruction_context,
)
from src.core.carrier_order import geometry_from_sps  # noqa: E402
from src.transport.gop_policy import ALL_INTRA, inspect_segment  # noqa: E402
from src.lattice_zk import video_proof  # noqa: E402
from src.lattice_zk.params import BDLOP_OPEN_128, TOY  # noqa: E402

KEY = hashlib.sha256(b"latticezk-hd-order-key").digest()


def sync_key(index: int) -> bytes:
    """Key 0 is ``KEY``; further keys repeat a run with other carrier prefixes."""
    return KEY if index == 0 else hashlib.sha256(KEY + index.to_bytes(4, "big")).digest()


def _peak_mb() -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    info = psutil.Process().memory_info()
    peak = getattr(info, "peak_wset", None) or info.rss
    return round(peak / 2**20, 1)


def capacity(video: Path, frames_per_segment: int, carrier: str) -> dict[str, Any]:
    """Stable carriers per segment and per picture (one slot per coded slice)."""
    structure = inspect_segment(video, ALL_INTRA)
    slices_per_picture = structure.coded_slices // structure.pictures
    started = time.perf_counter()
    per_segment: list[int] = []
    per_picture: list[int] = []
    with tempfile.TemporaryDirectory(prefix="latticezk-hd-order-cap-") as directory:
        paths, counts = transport._split_video_into_segments(
            video, directory, frames_per_segment, ffmpeg="ffmpeg", ffprobe="ffprobe"
        )
        for path, frames in zip(paths, counts):
            positions, _metadata = derive_blind_positions_operating_contract(
                str(path), KEY, UNBOUNDED_BITS, CARRIER_CONTRACTS[carrier], use_analysis_cache=True
            )
            geometry = geometry_from_sps(load_or_build_reconstruction_context(path)["sps"])
            pictures = [0] * frames
            for mb, _block, _coefficient in positions:
                pictures[mb // geometry.mbs_per_picture // slices_per_picture] += 1
            per_segment.append(len(positions))
            per_picture.extend(pictures)
            clear_video_analysis_cache()
    return {
        "width_mbs": geometry.width_mbs,
        "height_mbs": geometry.height_mbs,
        "slices_per_picture": slices_per_picture,
        "pictures": structure.pictures,
        "carrier_bits_per_segment": per_segment,
        "carrier_bits_per_picture": per_picture,
        "carrier_bits_per_picture_mean": round(sum(per_picture) / len(per_picture), 1),
        "carrier_bits_per_picture_min": min(per_picture),
        "seconds": round(time.perf_counter() - started, 1),
    }


def frames_needed(bits_per_picture: float, frames_per_segment: int,
                  fill: float = 1.0) -> int | None:
    """Pictures a registered envelope needs at a mean capacity (one chunk per segment)."""
    usable = bits_per_picture * fill
    if usable <= 0:
        return None
    envelope = video_proof.envelope_size(BDLOP_OPEN_128, registered=True)
    pictures = 1
    while pictures < 1_000_000:
        chunks = -(-pictures // frames_per_segment)
        if pictures * usable >= (envelope + chunks * CHUNK_FRAMING_BYTES) * 8:
            return pictures
        pictures += 1
    return None


def envelope_needs(bits_per_picture: float) -> dict[str, Any]:
    return {
        "registered_envelope_bytes": {
            BDLOP_OPEN_128.name: video_proof.envelope_size(BDLOP_OPEN_128, registered=True),
            "toy": video_proof.envelope_size(TOY, registered=True),
        },
        f"{BDLOP_OPEN_128.name}_pictures_by_frames_per_segment_and_fill": {
            f"fps{fps}_fill{fill}": frames_needed(bits_per_picture, fps, fill)
            for fps in (10, 25) for fill in (1.0, 0.9, 0.5)
        },
    }


def embed_quality(video: Path, frames_per_segment: int, carrier: str, chunk: int,
                  segments: int, check_extraction: bool, key: bytes = KEY) -> dict[str, Any]:
    # Deterministic pseudo-random payload: the same bits for every carrier contract.
    payload = hashlib.shake_256(b"hd-order-payload" + chunk.to_bytes(4, "big")).digest(
        chunk * segments)
    contract = CARRIER_CONTRACTS[carrier]
    clear_video_analysis_cache()
    with tempfile.TemporaryDirectory(prefix="latticezk-hd-order-") as directory:
        stego = Path(directory) / "stego.h264"
        started = time.perf_counter()
        embedded = transport.embed_chunked_video_payload(
            video, stego, payload, key, contract, frames_per_segment=frames_per_segment,
            chunk_size=chunk,
        )
        embed_s = time.perf_counter() - started
        clear_video_analysis_cache()
        quality = summarize_luma_mse(per_frame_luma_mse(video, stego))
        row: dict[str, Any] = {
            "carrier": carrier,
            "contract_version": contract.version,
            "chunk_bytes": chunk,
            "segments": segments,
            "carriers_used": embedded.carriers_used,
            "embed_s": round(embed_s, 1),
            **quality,
            "stego_sha256": hashlib.sha256(stego.read_bytes()).hexdigest(),
        }
        if check_extraction:
            started = time.perf_counter()
            extracted = transport.extract_chunked_video_payload(
                stego, key, contract, frames_per_segment=frames_per_segment
            )
            row["extract_s"] = round(time.perf_counter() - started, 1)
            row["extracted_ok"] = extracted.payload == payload
            clear_video_analysis_cache()
    row["peak_mb"] = _peak_mb()
    return row


def summarize(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mean PSNR (changed frames, worst frame) per fill level and carrier over the keys."""
    groups: dict[tuple[float, str], list[dict[str, Any]]] = {}
    for row in runs:
        groups.setdefault((row["fill"], row["carrier"]), []).append(row)
    summary = []
    for (fill, carrier), rows in sorted(groups.items()):
        def mean(field: str, rows=rows) -> float | None:
            values = [row[field] for row in rows if row[field] is not None]
            return round(sum(values) / len(values), 3) if values else None

        summary.append({
            "fill": fill, "carrier": carrier, "keys": len(rows),
            "psnr_modified_frames_db_mean": mean("luma_psnr_modified_frames_db"),
            "psnr_worst_frame_db_mean": mean("luma_psnr_worst_frame_db"),
            "psnr_worst_frame_db_min": min(row["luma_psnr_worst_frame_db"] for row in rows),
            "psnr_all_frames_db_mean": mean("luma_psnr_all_frames_db"),
        })
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--frames-per-segment", type=int, required=True)
    parser.add_argument("--carriers", nargs="+", default=["magnitude", "magnitude-geo"])
    parser.add_argument("--fill", type=float, nargs="+", default=[0.25, 0.5, 0.9])
    parser.add_argument("--keys", type=int, default=1,
                        help="repeat every fill level with this many sync keys")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    video = arguments.video.resolve(strict=True)
    started = time.perf_counter()
    scan = capacity(video, arguments.frames_per_segment, arguments.carriers[0])
    segments = len(scan["carrier_bits_per_segment"])
    report: dict[str, Any] = {
        "video": video.name,
        "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
        "frames_per_segment": arguments.frames_per_segment,
        "capacity": scan,
        "frames_needed_at_mean_capacity": envelope_needs(scan["carrier_bits_per_picture_mean"]),
        "runs": [],
    }
    sys.stderr.write(json.dumps(scan) + "\n")
    for fill in sorted(arguments.fill):
        chunk = int(min(scan["carrier_bits_per_segment"]) * fill) // 8 - CHUNK_FRAMING_BYTES
        if chunk < 1:
            continue
        for key_index in range(arguments.keys):
            for carrier in arguments.carriers:
                row = embed_quality(
                    video, arguments.frames_per_segment, carrier, chunk, segments,
                    check_extraction=fill == max(arguments.fill) and key_index == 0,
                    key=sync_key(key_index),
                )
                row["fill"] = fill
                row["key_index"] = key_index
                sys.stderr.write(json.dumps(row) + "\n")
                report["runs"].append(row)
                # Partial report after every run, so an interrupted sweep keeps its rows.
                report["complete"] = False
                arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["complete"] = True
    report["summary"] = summarize(report["runs"])
    report["total_s"] = round(time.perf_counter() - started, 1)
    report["seconds_per_frame_per_embed"] = round(
        sum(row["embed_s"] for row in report["runs"]) / max(len(report["runs"]), 1)
        / scan["pictures"], 2)
    report["peak_mb"] = _peak_mb()
    arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if all(row.get("extracted_ok", True) for row in report["runs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
