"""Resumable multi-clip evaluation sweep for the lattice-ZK video proof.

For every case it runs, in order, skipping steps whose output already exists:

1. ``encode``  -- all-intra H.264 Baseline/CAVLC from a Y4M source (if needed);
2. ``e2e``     -- embed, blind-extract and verify (``latticezk_video_e2e``);
3. ``steg``    -- classical targeted steganalysis on the first touched frames;
4. ``mlfeat``  -- per-frame features for learned steganalysis.

All outputs go to ``--work`` (stego videos, logs) and ``--results`` (JSON).

    python -m benchmark.latticezk_q2_sweep --cases benchmark/latticezk_q2_cases.json --workers 3
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
CHUNK_MARGIN = 0.97  # stay below the measured minimum segment capacity


def _log(message: str) -> None:
    sys.stderr.write(time.strftime("%H:%M:%S ") + message + "\n")
    sys.stderr.flush()


def _run(command: list[str], log: Path) -> bool:
    with log.open("a", encoding="utf-8") as handle:
        handle.write("$ " + " ".join(command) + "\n")
        handle.flush()
        completed = subprocess.run(command, cwd=ROOT, stdout=handle, stderr=handle, check=False)
    return completed.returncode == 0


def _encode(case: dict[str, Any], video: Path, log: Path) -> bool:
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-i", case["source_y4m"]]
    if case.get("frames"):
        command += ["-frames:v", str(case["frames"])]
    command += ["-c:v", "libx264", "-profile:v", "baseline", "-g", "1", "-bf", "0",
                "-qp", str(case["qp"]), "-f", "h264", str(video)]
    return _run(command, log)


def _auto_chunk(case: dict[str, Any], video: Path, results: Path, log: Path) -> int | None:
    """Pick a chunk size from measured capacity; ``None`` if the envelope cannot fit.

    ``density`` (0 < d <= 1) uses only that fraction of each segment's carriers, so
    the envelope spreads over proportionally more frames.  ``capacity_from`` reuses
    another case's scan of the same video.  Below full density the unscanned tail
    of the video is assumed to be like the scanned segments; the embedder still
    fails closed if a segment turns out to be short.
    """
    from src.lattice_zk import video_proof
    from src.lattice_zk.params import BDLOP_OPEN_128

    density = float(case.get("density", 1.0))
    if not 0 < density <= 1:
        raise ValueError("density must be in (0, 1]")
    capacity = results / f"capacity_{case.get('capacity_from', case['name'])}.json"
    if not capacity.exists():
        _log(f"{case['name']}: capacity scan")
        if not _run([PYTHON, "-B", "-m", "benchmark.latticezk_capacity_scan", str(video),
                     "--segments", str(case.get("scan_segments", 3)),
                     "--carrier", case.get("carrier", "magnitude"), "--output", str(capacity)], log):
            return None
    scan = json.loads(capacity.read_text(encoding="utf-8"))[0]
    carrier = case.get("carrier", "magnitude")
    if scan.get("video", video.name) != video.name or scan.get("carrier", "magnitude") != carrier:
        _log(f"{case['name']}: capacity scan is for {scan.get('video')}/{scan.get('carrier')}, "
             f"not {video.name}/{carrier}")
        return None
    from src.blind_payload_chunks import MAX_CHUNK_BYTES

    chunk = min(int(scan["min_chunk_bytes_supported"] * CHUNK_MARGIN * density), MAX_CHUNK_BYTES)
    envelope = video_proof.envelope_size(BDLOP_OPEN_128, registered=case.get("registered", True))
    needed = -(-envelope // chunk) if chunk > 0 else None
    available = scan["segments_scanned"] if density == 1.0 else scan["segments_total"]
    if needed is None or needed > available:
        return None
    return chunk


def run_case(case: dict[str, Any], work: Path, results: Path) -> dict[str, Any]:
    name = case["name"]
    video = ROOT / case["video"]
    stego = work / f"{name}.h264"
    log = work / f"{name}.log"
    report = results / f"e2e_{name}.json"
    status: dict[str, Any] = {"name": name}

    if not video.exists():
        _log(f"{name}: encode")
        if "source_y4m" not in case or not _encode(case, video, log):
            return {**status, "failed": "encode"}

    chunk_bytes = case.get("chunk_bytes", 1250)
    if chunk_bytes == "auto" and not report.exists():
        chunk_bytes = _auto_chunk(case, video, results, log)
        if chunk_bytes is None:
            (results / f"e2e_{name}.skipped.json").write_text(
                json.dumps({"name": name, "reason": "envelope does not fit the scanned capacity"}) + "\n",
                encoding="utf-8")
            return {**status, "failed": "capacity"}

    if not report.exists():
        _log(f"{name}: e2e start (chunk {chunk_bytes} B)")
        command = [PYTHON, "-B", "-m", "benchmark.latticezk_video_e2e", "--video", str(video),
                   "--output", str(stego), "--report", str(report),
                   "--chunk-bytes", str(chunk_bytes), "--carrier", case.get("carrier", "magnitude")]
        if case.get("registered", True):
            command.append("--registered")
        if not case.get("security_checks", False):
            command.append("--skip-security-checks")
        stego.unlink(missing_ok=True)
        if not _run(command, log):
            return {**status, "failed": "e2e"}
        _log(f"{name}: e2e done")

    steg = results / f"steg_{name}.json"
    if case.get("steganalysis", True) and not steg.exists() and stego.exists():
        _log(f"{name}: classical steganalysis")
        _run([PYTHON, "-B", "-m", "benchmark.latticezk_steganalysis", "--cover", str(video),
              "--stego", str(stego), "--frames", str(case.get("steg_frames", 100)),
              "--output", str(steg)], log)

    features = work / f"mlfeat_{name}.npz"
    if case.get("ml_features", True) and not features.exists() and stego.exists():
        _log(f"{name}: ML features")
        _run([PYTHON, "-B", "-m", "benchmark.latticezk_ml_steganalysis", "features",
              "--cover", str(video), "--stego", str(stego), "--label", case.get("clip", name),
              "--macroblocks-per-frame", str(case.get("macroblocks_per_frame", 396)),
              "--max-segments", str(case.get("ml_segments", 3)), "--output", str(features)], log)
    return {**status, "e2e": report.exists(), "steg": steg.exists(), "mlfeat": features.exists()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--work", type=Path, default=ROOT / "tmp" / "q2")
    parser.add_argument("--results", type=Path, default=ROOT / "benchmark" / "results" / "q2")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--only", nargs="*", help="run only these case names")
    arguments = parser.parse_args()
    arguments.work.mkdir(parents=True, exist_ok=True)
    arguments.results.mkdir(parents=True, exist_ok=True)
    cases = json.loads(arguments.cases.read_text(encoding="utf-8"))
    if arguments.only:
        cases = [case for case in cases if case["name"] in arguments.only]
    with ThreadPoolExecutor(max_workers=arguments.workers) as pool:
        statuses = list(pool.map(lambda case: run_case(case, arguments.work, arguments.results), cases))
    (arguments.results / "sweep_status.json").write_text(json.dumps(statuses, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(statuses, indent=2) + "\n")
    return 0 if all("failed" not in status for status in statuses) else 1


if __name__ == "__main__":
    raise SystemExit(main())
