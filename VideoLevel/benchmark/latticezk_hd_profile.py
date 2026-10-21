"""Peak memory and time of carrier analysis, embedding and extraction on short HD cuts.

Each frame count runs in a fresh process (peak working set / max RSS is
monotonic), on a cut of the first N pictures of the video, as one transport
segment. A linear fit over the frame counts extrapolates to a segment length:
the transport analyses one segment at a time, so peak memory grows with
``frames_per_segment`` x macroblocks per frame, not with the video length.

    python -m benchmark.latticezk_hd_profile --video data/encoded/park_joy_720p_q22_g1.h264 \
        --frames 3 6 --extrapolate 25 50 100 --output tmp/hd_profile.json
    python -m benchmark.latticezk_hd_profile --synthetic 1920x1080 --frames 3 6

``--synthetic WxH`` encodes an upscaled-noise stand-in (lavfi testsrc2); its
coefficient density is not that of natural content, so treat it as a check of
the machinery, not of real-content memory.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PAYLOAD = b"hd profile payload " * 4


def _peak_mb() -> float:
    try:
        import psutil

        info = psutil.Process().memory_info()
        peak = getattr(info, "peak_wset", None)
        if peak is not None:
            return round(peak / 2**20, 1)
    except ImportError:
        pass
    import resource  # POSIX: ru_maxrss is KiB on Linux

    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def _cut(video: Path, frames: int, target: Path) -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    from repro import cut_annexb  # noqa: PLC0415

    return cut_annexb(video, target, frames)


def _child(video: Path, frames: int, phases: list[str],
           carrier: str = "magnitude") -> dict[str, Any]:
    from benchmark.latticezk_video_e2e import CARRIER_CONTRACTS
    from src import blind_sync_streaming as transport
    from src.core.analysis_cache import (
        clear_video_analysis_cache,
        load_or_build_reconstruction_context,
        load_or_build_video_analysis,
    )
    from src.gop_policy import ALL_INTRA, IDR_CARRIERS_INTER_RAW, inspect_segment

    key = bytes(range(32))
    contract = CARRIER_CONTRACTS[carrier]
    report: dict[str, Any] = {"frames": frames, "carrier": carrier}
    with tempfile.TemporaryDirectory(prefix="latticezk-hd-") as directory:
        cut = Path(directory) / "cut.h264"
        report["pictures"] = _cut(video, frames, cut)
        try:
            structure = inspect_segment(cut, ALL_INTRA)
            policy = ALL_INTRA
        except ValueError:
            structure = inspect_segment(cut, IDR_CARRIERS_INTER_RAW)
            policy = IDR_CARRIERS_INTER_RAW
        report.update(gop_policy=policy, structure=vars(structure))
        started = time.perf_counter()
        analysis = load_or_build_video_analysis(cut, use_cache=True, stable_blind_only=True)
        context = load_or_build_reconstruction_context(cut)
        report["analysis_s"] = round(time.perf_counter() - started, 1)
        report["macroblocks_per_picture"] = int(context["mb_count_per_slice"])
        report["coded_luma_blocks"] = len(analysis[0])
        report["stable_carriers"] = len(analysis[5])
        report["peak_after_analysis_mb"] = _peak_mb()
        del analysis, context
        clear_video_analysis_cache()
        # Envelope framing is 37 bytes; size the payload to the cut's capacity.
        payload = PAYLOAD[: max(0, min(len(PAYLOAD), report["stable_carriers"] // 8 - 40))]
        report["payload_bytes"] = len(payload)
        if "embed" in phases and payload:
            stego = Path(directory) / "stego.h264"
            started = time.perf_counter()
            transport.embed_chunked_video_payload(
                cut, stego, payload, key, contract, frames_per_segment=frames,
                chunk_size=len(payload), gop_policy=policy,
            )
            report["embed_s"] = round(time.perf_counter() - started, 1)
            report["peak_after_embed_mb"] = _peak_mb()
            started = time.perf_counter()
            extracted = transport.extract_chunked_video_payload(
                stego, key, contract, frames_per_segment=frames, gop_policy=policy
            )
            report["extract_s"] = round(time.perf_counter() - started, 1)
            report["extracted_ok"] = extracted.payload == payload
            report["peak_after_extract_mb"] = _peak_mb()
    return report


def _fit(points: list[tuple[int, float]]) -> tuple[float, float]:
    """Least-squares ``y = a + b x``; one point gives ``b = y / x``."""
    if len(points) == 1:
        return 0.0, points[0][1] / points[0][0]
    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / sum(
        (x - mean_x) ** 2 for x, _ in points
    )
    return mean_y - slope * mean_x, slope


def _encode_synthetic(size: str, frames: int, target: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi",
         "-i", f"testsrc2=size={size}:rate=25,noise=alls=12:allf=t", "-frames:v", str(frames),
         "-pix_fmt", "yuv420p", "-c:v", "libx264", "-profile:v", "baseline", "-g", "1",
         "-bf", "0", "-qp", "22", "-threads", "1", "-f", "h264", str(target)],
        check=True, timeout=600,
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--video", type=Path)
    source.add_argument("--synthetic", metavar="WxH")
    parser.add_argument("--frames", type=int, nargs="+", default=[3, 6])
    parser.add_argument("--extrapolate", type=int, nargs="*", default=[10, 25, 50, 100])
    parser.add_argument("--analysis-only", action="store_true", help="skip embed/extract")
    parser.add_argument("--carrier", default="magnitude",
                        help="carrier contract (benchmark.latticezk_video_e2e.CARRIER_CONTRACTS)")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    phases = [] if arguments.analysis_only else ["embed"]
    if arguments.child:
        sys.stdout.write(json.dumps(
            _child(arguments.video, arguments.frames[0], phases, arguments.carrier)) + "\n")
        return 0

    with tempfile.TemporaryDirectory(prefix="latticezk-hd-src-") as directory:
        video = arguments.video
        if arguments.synthetic:
            video = _encode_synthetic(arguments.synthetic, max(arguments.frames),
                                      Path(directory) / "synthetic.h264")
        runs = []
        for frames in arguments.frames:
            command = [sys.executable, "-B", "-m", "benchmark.latticezk_hd_profile", "--child",
                       "--video", str(video.resolve()), "--frames", str(frames),
                       "--carrier", arguments.carrier]
            if arguments.analysis_only:
                command.append("--analysis-only")
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                       check=True, env={**os.environ})
            runs.append(json.loads(completed.stdout.strip().splitlines()[-1]))
    # A cut too small for any payload skips embedding; then fit analysis peaks only.
    embedded = all("peak_after_extract_mb" in run for run in runs)
    peak_key = "peak_after_extract_mb" if embedded else "peak_after_analysis_mb"
    base, per_frame = _fit([(run["frames"], run[peak_key]) for run in runs])
    _t0, seconds_per_frame = _fit([
        (run["frames"], run["analysis_s"] + run.get("embed_s", 0) + run.get("extract_s", 0))
        for run in runs
    ])
    report = {
        "video": str(arguments.video) if arguments.video else f"synthetic {arguments.synthetic}",
        "runs": runs,
        "peak_mb_fit": {"base_mb": round(base, 1), "per_frame_mb": round(per_frame, 1),
                        "fitted_peak": peak_key},
        "seconds_per_frame_analysis_embed_extract": round(seconds_per_frame, 2),
        "extrapolated_peak_mb_by_frames_per_segment": {
            str(frames): round(base + per_frame * frames) for frames in arguments.extrapolate
        },
    }
    text = json.dumps(report, indent=2) + "\n"
    if arguments.output:
        arguments.output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
