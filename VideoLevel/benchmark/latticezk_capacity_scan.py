"""Stable, patchability-checked carrier capacity per segment of an H.264 clip.

Reports how many envelope bits each 100-frame segment can carry under the
blind contract used by the lattice-ZK pipeline, and whether the registered
(7 589 B) and in-band (14 309 B) envelopes fit with a given chunk size.

    python -m benchmark.latticezk_capacity_scan data/encoded/foreman_cif_q22_g1.h264 --segments 1
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.latticezk_video_e2e import CARRIER_CONTRACTS  # noqa: E402
from src.transport.blind_payload_chunks import CHUNK_HEADER  # noqa: E402
from src.transport.blind_sync import BLIND_ENVELOPE_HEADER_BYTES, derive_blind_positions_operating_contract  # noqa: E402
from src.transport.blind_sync_streaming import _split_video_into_segments  # noqa: E402
from src.core.analysis_cache import clear_video_analysis_cache  # noqa: E402
from src.lattice_zk import video_proof  # noqa: E402
from src.lattice_zk.params import BDLOP_OPEN_128  # noqa: E402

UNBOUNDED_BITS = 10_000_000
CHUNK_FRAMING_BYTES = BLIND_ENVELOPE_HEADER_BYTES + CHUNK_HEADER.size


def _frame_count(video: Path) -> int:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, timeout=600, check=True,
    )
    return int(completed.stdout.strip())


def scan(video: Path, frames_per_segment: int, segments: int | None,
         carrier: str = "magnitude") -> dict[str, Any]:
    started = time.perf_counter()
    capacities: list[int] = []
    with tempfile.TemporaryDirectory(prefix="latticezk-capacity-") as directory:
        paths, counts = _split_video_into_segments(
            video, directory, frames_per_segment, ffmpeg="ffmpeg", ffprobe="ffprobe"
        )
        for path in paths[: segments or len(paths)]:
            positions, _metadata = derive_blind_positions_operating_contract(
                str(path), b"capacity-scan-key", UNBOUNDED_BITS, CARRIER_CONTRACTS[carrier],
                use_analysis_cache=True,
            )
            capacities.append(len(positions))
            clear_video_analysis_cache()
    per_segment_bytes = [bits // 8 - CHUNK_FRAMING_BYTES for bits in capacities]
    usable_chunk = min(per_segment_bytes)
    report: dict[str, Any] = {
        "video": video.name,
        "carrier": carrier,
        "frames": sum(counts),
        "segments_total": len(paths),
        "segments_scanned": len(capacities),
        "carrier_bits_per_segment": capacities,
        "min_chunk_bytes_supported": usable_chunk,
        "scan_seconds": round(time.perf_counter() - started, 1),
    }
    for mode, registered in (("registered", True), ("in_band", False)):
        size = video_proof.envelope_size(BDLOP_OPEN_128, registered=registered)
        needed = math.ceil(size / max(usable_chunk, 1)) if usable_chunk > 0 else None
        report[f"{mode}_segments_needed_at_min_chunk"] = needed
        report[f"{mode}_fits_estimate"] = needed is not None and needed <= len(paths)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("videos", nargs="+", type=Path)
    parser.add_argument("--frames-per-segment", type=int, default=100)
    parser.add_argument("--segments", type=int, help="scan only the first N segments")
    parser.add_argument("--carrier", choices=sorted(CARRIER_CONTRACTS), default="magnitude")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    reports = [scan(video.resolve(strict=True), arguments.frames_per_segment, arguments.segments,
                    arguments.carrier)
               for video in arguments.videos]
    text = json.dumps(reports, indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
