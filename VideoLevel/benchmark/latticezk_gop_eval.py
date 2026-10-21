"""GOP > 1 evaluation of the lattice-ZK video proof against all-intra on the same clip.

For every case it (resumably) encodes a Baseline/CAVLC cut with a fixed GOP,
checks the slice structure of every transport segment, scans the carrier
capacity, runs the end-to-end embed/verify (``latticezk_video_e2e``) under the
case's GOP policy, and measures per-frame quality including P-frame drift.

    python -m benchmark.latticezk_gop_eval --cases benchmark/latticezk_gop_cases.json
    python -m benchmark.latticezk_gop_eval --cases benchmark/latticezk_gop_cases.json --only foreman_g8

Outputs ``<results>/gop_<name>.json`` per case and ``<results>/gop_summary.json``.
Run one case at a time on a memory-constrained machine (ZKSTEGO_ANALYSIS_WORKERS=2
keeps a 100-frame CIF segment below ~1 GB).
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

from benchmark.latticezk_quality import _psnr, per_frame_luma_mse, summarize_luma_mse  # noqa: E402
from src import gop_policy  # noqa: E402

PYTHON = sys.executable
CHUNK_MARGIN = 0.97


def _log(message: str) -> None:
    sys.stderr.write(time.strftime("%H:%M:%S ") + message + "\n")
    sys.stderr.flush()


def encode_command(case: dict[str, Any], source: Path | str, output: Path | str) -> list[str]:
    """Baseline/CAVLC, fixed GOP (no scene-cut IDRs), no B frames, constant QP."""
    gop = int(case["gop"])
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
    if case.get("stream_loop"):
        command += ["-stream_loop", str(case["stream_loop"])]
    command += ["-i", str(source)]
    if case.get("frames"):
        command += ["-frames:v", str(case["frames"])]
    command += ["-c:v", "libx264", "-profile:v", "baseline", "-coder", "0", "-bf", "0",
                "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
                "-qp", str(case["qp"]), "-threads", str(case.get("threads", 4))]
    if case.get("x264_params"):
        command += ["-x264-params", case["x264_params"]]
    return command + ["-f", "h264", str(output)]


def _structure(video: Path, frames_per_segment: int, policy: str) -> list[dict[str, int]]:
    from src.blind_sync_streaming import _inspect_segments, _split_video_into_segments

    with tempfile.TemporaryDirectory(prefix="latticezk-gop-") as directory:
        segments, counts = _split_video_into_segments(video, directory, frames_per_segment)
        structures = _inspect_segments(segments, counts, policy)
    return [{"frames": count, **vars(structure)} for count, structure in zip(counts, structures)]


def _drift_profile(luma_mse: list[float], gop: int) -> dict[str, Any]:
    """PSNR by distance from the last IDR: shows how IDR changes drift into P frames.

    The by-position profile averages only GOPs whose IDR picture was modified.
    """
    by_position: dict[int, list[float]] = {}
    for index, mse in enumerate(luma_mse):
        if luma_mse[index - index % gop] > 0:
            by_position.setdefault(index % gop, []).append(mse)
    profile = {
        str(position): _psnr(sum(values) / len(values))
        for position, values in sorted(by_position.items())
    }
    idr = [mse for index, mse in enumerate(luma_mse) if index % gop == 0]
    inter = [mse for index, mse in enumerate(luma_mse) if index % gop != 0]
    worst = max(range(len(luma_mse)), key=luma_mse.__getitem__)
    return {
        "modified_gops": sum(1 for index in range(0, len(luma_mse), gop) if luma_mse[index] > 0),
        "luma_psnr_by_gop_position_in_modified_gops_db": profile,
        "worst_frame_index": worst,
        "worst_frame_gop_position": worst % gop,
        "luma_psnr_idr_frames_db": _psnr(sum(idr) / len(idr)) if idr else None,
        "luma_psnr_p_frames_db": _psnr(sum(inter) / len(inter)) if inter else None,
        "p_frames_changed_by_drift": sum(1 for mse in inter if mse > 0),
        "p_frames": len(inter),
    }


def _envelope_fit(carrier_bits: list[int], frames: list[int]) -> dict[str, Any]:
    from src.blind_payload_chunks import CHUNK_HEADER
    from src.blind_sync import BLIND_ENVELOPE_HEADER_BYTES
    from src.lattice_zk import video_proof
    from src.lattice_zk.params import BDLOP_OPEN_128

    framing = BLIND_ENVELOPE_HEADER_BYTES + CHUNK_HEADER.size
    bits_per_frame = sum(carrier_bits) / sum(frames)
    fit = {"carrier_bits_per_100_frames": round(100 * bits_per_frame, 1)}
    for mode, registered in (("registered", True), ("in_band", False)):
        size = video_proof.envelope_size(BDLOP_OPEN_128, registered=registered)
        usable = min(bits // 8 - framing for bits in carrier_bits)
        fit[f"{mode}_128_envelope_bytes"] = size
        fit[f"{mode}_128_segments_needed_at_min_chunk"] = (
            math.ceil(size / usable) if usable > 0 else None
        )
        # Frames of this clip's average capacity the envelope needs, ignoring per-chunk framing.
        fit[f"{mode}_128_frames_needed_estimate"] = math.ceil(size * 8 / bits_per_frame)
    return fit


def run_case(case: dict[str, Any], work: Path, results: Path, data_root: Path) -> dict:
    name = case["name"]
    video = work / f"{name}.h264"
    stego = work / f"{name}.stego.h264"
    report_path = results / f"gop_{name}.json"
    if report_path.exists():
        return json.loads(report_path.read_text(encoding="utf-8"))
    policy = case.get("gop_policy", gop_policy.ALL_INTRA if case["gop"] == 1
                      else gop_policy.IDR_CARRIERS_INTER_RAW)
    frames_per_segment = int(case["frames_per_segment"])
    command = encode_command(case, data_root / case["source_y4m"], video)
    if not video.exists():
        _log(f"{name}: encode")
        subprocess.run(command, check=True, cwd=ROOT)
    structure = _structure(video, frames_per_segment, policy)

    _log(f"{name}: capacity scan")
    from benchmark.latticezk_capacity_scan import scan

    capacity = scan(video, frames_per_segment, case.get("scan_segments"), case.get("carrier", "magnitude"))
    idrs = sum(segment["idr_slices"] for segment in structure[: capacity["segments_scanned"]])
    frames_scanned = [segment["frames"] for segment in structure[: capacity["segments_scanned"]]]
    capacity["carrier_bits_per_idr"] = round(sum(capacity["carrier_bits_per_segment"]) / max(idrs, 1), 1)
    capacity.update(_envelope_fit(capacity["carrier_bits_per_segment"], frames_scanned))

    chunk = min(int(capacity["min_chunk_bytes_supported"] * CHUNK_MARGIN), int(case.get("max_chunk_bytes", 1250)))
    from src.lattice_zk import params as parameter_sets
    from src.lattice_zk import video_proof

    envelope = video_proof.envelope_size(
        getattr(parameter_sets, case.get("parameter_set", "TOY")), registered=case.get("registered", True)
    )
    segments_needed = math.ceil(envelope / chunk) if chunk > 0 else None
    report = {
        "name": name,
        "clip": case["clip"],
        "gop": case["gop"],
        "qp": case["qp"],
        "frames_per_segment": frames_per_segment,
        "gop_policy": policy,
        "encode_command": " ".join(encode_command(case, case["source_y4m"], f"{name}.h264")),
        "segment_structure": structure,
        "capacity": capacity,
    }
    if segments_needed is None or segments_needed > capacity["segments_total"]:
        report["e2e"] = {"skipped": (
            f"{case.get('parameter_set', 'TOY')} envelope of {envelope} B needs "
            f"{segments_needed} segments at {chunk} B per segment; the clip has "
            f"{capacity['segments_total']}")}
        report["quality"] = None
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report
    e2e_path = work / f"{name}.e2e.json"
    if not (e2e_path.exists() and stego.exists()):
        stego.unlink(missing_ok=True)
        e2e_path.unlink(missing_ok=True)
        _log(f"{name}: e2e (chunk {chunk} B, policy {policy})")
        e2e_command = [PYTHON, "-B", "-m", "benchmark.latticezk_video_e2e", "--video", str(video),
                       "--output", str(stego), "--report", str(e2e_path),
                       "--parameter-set", case.get("parameter_set", "TOY"),
                       "--frames-per-segment", str(frames_per_segment), "--chunk-bytes", str(chunk),
                       "--carrier", case.get("carrier", "magnitude"), "--gop-policy", policy]
        if case.get("registered", True):
            e2e_command.append("--registered")
        if not case.get("security_checks", True):
            e2e_command.append("--skip-security-checks")
        with (work / f"{name}.log").open("a", encoding="utf-8") as log:
            completed = subprocess.run(e2e_command, cwd=ROOT, stdout=log, stderr=log, check=False)
        if completed.returncode != 0 and not e2e_path.exists():
            raise RuntimeError(f"{name}: e2e failed, see {work / (name + '.log')}")
    e2e = json.loads(e2e_path.read_text(encoding="utf-8"))

    luma_mse = per_frame_luma_mse(video, stego)
    report.update({
        "frames": len(luma_mse),
        "e2e": {key: e2e.get(key) for key in (
            "parameter_set", "mode", "carrier", "envelope_bytes", "carriers_used", "segments_used",
            "chunk_bytes", "carrier_profile_id", "statement_id", "blind_video_only_verification",
            "verify_reason", "replay_rejected", "tamper_rejected", "p_slice_tamper_rejected",
            "p_slice_tamper_reason", "slice_nal_comparison", "decoded_quality", "timings_s")},
        "quality": {**summarize_luma_mse(luma_mse), **_drift_profile(luma_mse, int(case["gop"]))},
        "per_frame_luma_psnr_db": [_psnr(value) for value in luma_mse],
    })
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _summary(reports: list[dict]) -> list[dict]:
    rows = []
    for report in reports:
        quality, capacity, e2e = report["quality"] or {}, report["capacity"], report["e2e"]
        if "skipped" in e2e:
            rows.append({"name": report["name"], "clip": report["clip"], "gop": report["gop"],
                         "carrier_bits_per_100_frames": capacity["carrier_bits_per_100_frames"],
                         "carrier_bits_per_idr": capacity["carrier_bits_per_idr"],
                         "registered_128_frames_needed_estimate":
                             capacity["registered_128_frames_needed_estimate"],
                         "in_band_128_frames_needed_estimate":
                             capacity["in_band_128_frames_needed_estimate"],
                         "e2e_skipped": e2e["skipped"]})
            continue
        rows.append({
            "name": report["name"], "clip": report["clip"], "gop": report["gop"],
            "frames_per_segment": report["frames_per_segment"], "gop_policy": report["gop_policy"],
            "carrier_bits_per_100_frames": capacity["carrier_bits_per_100_frames"],
            "carrier_bits_per_idr": capacity["carrier_bits_per_idr"],
            "registered_128_frames_needed_estimate": capacity["registered_128_frames_needed_estimate"],
            "in_band_128_frames_needed_estimate": capacity["in_band_128_frames_needed_estimate"],
            "e2e_parameter_set": e2e["parameter_set"], "e2e_envelope_bytes": e2e["envelope_bytes"],
            "verified": e2e["blind_video_only_verification"],
            "p_slice_tamper_rejected": e2e["p_slice_tamper_rejected"],
            "non_idr_slices_identical": (e2e["slice_nal_comparison"] or {}).get("non_idr_slices_identical"),
            "non_idr_slices": (e2e["slice_nal_comparison"] or {}).get("non_idr_slices"),
            "frames_modified": quality["frames_modified"],
            "luma_psnr_all_frames_db": quality["luma_psnr_all_frames_db"],
            "luma_psnr_modified_frames_db": quality["luma_psnr_modified_frames_db"],
            "luma_psnr_worst_frame_db": quality["luma_psnr_worst_frame_db"],
            "luma_psnr_p_frames_db": quality["luma_psnr_p_frames_db"],
            "embed_s": (e2e["timings_s"] or {}).get("embed_s"),
            "verify_s": (e2e["timings_s"] or {}).get("verify_s"),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--work", type=Path, default=ROOT / "tmp" / "gop")
    parser.add_argument("--results", type=Path, default=ROOT / "benchmark" / "results" / "q2")
    parser.add_argument("--only", nargs="*", help="run only these case names")
    parser.add_argument("--data-root", type=Path, default=ROOT,
                        help="directory that holds the cases' data/raw/*.y4m sources")
    arguments = parser.parse_args()
    arguments.work.mkdir(parents=True, exist_ok=True)
    arguments.results.mkdir(parents=True, exist_ok=True)
    cases = json.loads(arguments.cases.read_text(encoding="utf-8"))
    by_name = {case["name"]: case for case in cases}
    # Long ``integrator_only`` cases run only when named with --only.
    if arguments.only:
        selected = [case for case in cases if case["name"] in arguments.only]
    else:
        selected = [case for case in cases if not case.get("integrator_only")]
    for case in selected:
        run_case(case, arguments.work, arguments.results, arguments.data_root)
    reports = [json.loads(path.read_text(encoding="utf-8"))
               for name in by_name if (path := arguments.results / f"gop_{name}.json").exists()]
    summary = _summary(reports)
    (arguments.results / "gop_summary.json").write_text(json.dumps(summary, indent=2) + "\n",
                                                        encoding="utf-8")
    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
