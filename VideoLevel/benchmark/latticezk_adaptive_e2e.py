"""Real E2E comparison: direct magnitude carriers vs. adaptive (STC) carriers.

For each cover (an all-intra CIF cut of <= 200 frames) and each carrier mode it
runs, sequentially and resumably:

1. ``latticezk_video_e2e`` with the registered envelope (``--registered``,
   ``--chunk-bytes``), which embeds, blind-extracts from the stego video alone
   and verifies the proof;
2. per-frame learned-steganalysis features of every touched segment (the same
   coefficient and pixel features as ``latticezk_ml_steganalysis``) plus the
   exact number of changed coefficients;

and finally evaluates the FLD/logistic detectors per mode (paired half split
and leave-one-clip-out) into one JSON report.

Case names are ``<clip>_cif_q22_reg_b1mag`` / ``..._b1adapt`` so the CNN script
(``--set b1_magnitude`` / ``b1_adaptive``) can reuse the stego videos.

    python -m benchmark.latticezk_adaptive_e2e --covers tmp/cuts/container_200.h264 ... \\
        --work tmp/adaptive --output benchmark/results/q2/adaptive_e2e.json
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

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark import latticezk_ml_steganalysis as steg  # noqa: E402

MODES = {"b1mag": "magnitude", "b1adapt": "adaptive", "b1adtex": "adaptive-texture"}
MACROBLOCKS = 396


def _log(message: str) -> None:
    sys.stderr.write(time.strftime("%H:%M:%S ") + message + "\n")
    sys.stderr.flush()


def case_name(cover: Path, mode: str) -> str:
    return f"{cover.stem.split('_')[0]}_cif_q22_reg_{mode}"


def run_e2e(cover: Path, mode: str, work: Path, chunk_bytes: int) -> dict[str, Any]:
    case = case_name(cover, mode)
    report = work / f"e2e_{case}.json"
    if not report.exists():
        _log(f"{case}: e2e")
        log = work / f"{case}.log"
        command = [sys.executable, "-B", "-m", "benchmark.latticezk_video_e2e",
                   "--video", str(cover), "--output", str(work / f"{case}.h264"),
                   "--report", str(report), "--registered", "--chunk-bytes", str(chunk_bytes),
                   "--carrier", MODES[mode], "--skip-security-checks"]
        with log.open("a", encoding="utf-8") as handle:
            completed = subprocess.run(command, cwd=ROOT, stdout=handle, stderr=handle, check=False)
        if completed.returncode or not report.exists():
            raise RuntimeError(f"{case}: e2e failed, see {log}")
    return json.loads(report.read_text(encoding="utf-8"))


def _count_changes(cover_blocks: list, stego_blocks: list) -> dict[str, int]:
    stego = {(mb, blk): levels for mb, blk, levels in stego_blocks}
    blocks = coefficients = magnitude_changes = 0
    for mb, blk, levels in cover_blocks:
        other = stego.get((mb, blk))
        if other is None or list(other) == list(levels):
            continue
        blocks += 1
        for before, after in zip(levels, other):
            if before != after:
                coefficients += 1
                magnitude_changes += abs(before) != abs(after)
    return {"blocks": blocks, "coefficients": coefficients, "magnitude_changes": magnitude_changes}


def features(cover: Path, case: str, work: Path) -> tuple[Path, dict[str, Any]]:
    """Steganalysis features of touched segments (``latticezk_ml_steganalysis`` format)."""
    from benchmark.legacy._common import load_or_extract_idr_blocks
    from src.bitstream.bitstream_ops import BitstreamReconstructor
    from src.transport.blind_sync_streaming import _split_video_into_segments

    output = work / f"features_{case}.npz"
    counts_path = work / f"changes_{case}.json"
    if output.exists() and counts_path.exists():
        return output, json.loads(counts_path.read_text(encoding="utf-8"))
    stego = work / f"{case}.h264"
    outputs: dict[str, list] = {name: [] for name in ("coeff", "pixel", "label", "pair", "modified")}
    totals = {"blocks": 0, "coefficients": 0, "magnitude_changes": 0}
    with tempfile.TemporaryDirectory(prefix="adaptive-feat-") as directory:
        root = Path(directory)
        (root / "c").mkdir()
        (root / "s").mkdir()
        cover_segments, _ = _split_video_into_segments(cover, str(root / "c"), 100)
        stego_segments, _ = _split_video_into_segments(stego, str(root / "s"), 100)
        for index, (cover_segment, stego_segment) in enumerate(zip(cover_segments, stego_segments)):
            if Path(cover_segment).read_bytes() == Path(stego_segment).read_bytes():
                continue
            per_side = {}
            for side, segment in (("cover", cover_segment), ("stego", stego_segment)):
                luma = steg.decode_luma_native(Path(segment))
                blocks = load_or_extract_idr_blocks(Path(segment), BitstreamReconstructor(), force=True)[0]
                per_side[side] = (steg.coefficient_features(blocks, MACROBLOCKS, len(luma)),
                                  steg.pixel_features(luma), blocks)
                del luma
            for key, value in _count_changes(per_side["cover"][2], per_side["stego"][2]).items():
                totals[key] += value
            frames = min(len(per_side["cover"][0]), len(per_side["stego"][0]))
            changed = np.abs(per_side["cover"][0][:frames] - per_side["stego"][0][:frames]).sum(axis=1) > 0
            for label, side in ((0, "cover"), (1, "stego")):
                outputs["coeff"].append(per_side[side][0][:frames])
                outputs["pixel"].append(per_side[side][1][:frames])
                outputs["label"].append(np.full(frames, label))
                outputs["pair"].append(index * 100 + np.arange(frames))
                outputs["modified"].append(changed)
            del per_side
    clip = case.split("_cif")[0]
    result = {key: np.concatenate(value) for key, value in outputs.items()}
    result["clip"] = np.array([clip] * len(result["label"]))
    np.savez_compressed(output, **result)
    counts_path.write_text(json.dumps(totals, indent=2) + "\n", encoding="utf-8")
    return output, totals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--covers", nargs="+", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chunk-bytes", type=int, default=4200)
    parser.add_argument("--modes", nargs="+", choices=sorted(MODES), default=sorted(MODES))
    arguments = parser.parse_args()
    arguments.work.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("ZKSTEGO_ANALYSIS_WORKERS", "2")

    cases: dict[str, Any] = {}
    feature_paths: dict[str, list[Path]] = {mode: [] for mode in arguments.modes}
    for cover in [path.resolve(strict=True) for path in arguments.covers]:
        for mode in arguments.modes:
            case = case_name(cover, mode)
            report = run_e2e(cover, mode, arguments.work, arguments.chunk_bytes)
            _log(f"{case}: features")
            path, changes = features(cover, case, arguments.work)
            feature_paths[mode].append(path)
            cases[case] = {
                "cover": cover.name,
                "carrier": report["carrier"],
                "carrier_contract": report["carrier_contract"],
                "verified_from_video_alone": report["blind_video_only_verification"],
                "envelope_bytes": report["envelope_bytes"],
                "carriers_used": report["carriers_used"],
                "segments_used": report["segments_used"],
                "changes": changes,
                "changes_per_envelope_bit": round(
                    changes["coefficients"] / (report["envelope_bytes"] * 8), 4),
                "decoded_quality": report["decoded_quality"],
                "frame_quality": report["frame_quality"],
                "timings_s": report["timings_s"],
            }
            _log(f"{case}: verified={report['blind_video_only_verification']} changes={changes}")
    # ZKSTEGO_SKIP_LEARNED=1 defers the learned-steganalysis evaluation.
    detection = ({} if os.environ.get("ZKSTEGO_SKIP_LEARNED", "") == "1"
                 else {mode: steg.evaluate(paths) for mode, paths in feature_paths.items()})
    summary = {
        "protocol": ("registered BDLOP envelope, chunk-bytes %d, 100-frame segments; "
                     "FLD/logistic on per-frame coefficient (340) and SRM-lite (500) features; "
                     "attacker trains on exact cover/stego pairs" % arguments.chunk_bytes),
        "modes": {mode: MODES[mode] for mode in arguments.modes},
        "cases": cases,
        "detection": detection,
    }
    text = json.dumps(summary, indent=2) + "\n"
    arguments.output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
