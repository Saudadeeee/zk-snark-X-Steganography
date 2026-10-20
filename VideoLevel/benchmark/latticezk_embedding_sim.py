"""Simulated comparison of carrier modification rules against learned steganalysis.

Takes the cover segments that a real E2E run touched, selects the same number
of stable carriers at random (the real pipeline orders carriers by a keyed
shuffle), writes uniformly random bits with two rules, and measures how well
the coefficient-domain detector separates cover from stego:

* ``replacement`` -- LSB replacement of the magnitude (what the pipeline does);
* ``matching``     -- LSB matching: change the magnitude by +1 or -1 at random
  when the parity is wrong, never going below the eligibility threshold;
* ``t1_sign``      -- the original trailing-one sign flip, on the highest-
  frequency trailing one of each block.

Features are the coefficient features plus per-position sign shares, so a
sign-only rule is not invisible by construction.

Patchability is not re-checked, so this isolates the statistical effect of the
modification rule.  The ``replacement`` arm is a sanity check: it should land
near the P_E measured on the real stego videos.

    python -m benchmark.latticezk_embedding_sim --cases container_cif_q22_reg city_cif_q22_reg ...
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark import latticezk_ml_steganalysis as steg  # noqa: E402

RESULTS = ROOT / "benchmark" / "results" / "q2"
CASES_FILE = ROOT / "benchmark" / "latticezk_q2_cases.json"
CARRIER_MIN = 4
SEED = 20261019


def _modify(value: int, bit: int, rule: str, rng: np.random.Generator) -> int:
    if rule == "t1_sign":
        return value if int(value < 0) == bit else -value
    magnitude = abs(value)
    if magnitude % 2 == bit:
        return value
    if rule == "replacement":
        new = magnitude ^ 1
    elif magnitude == CARRIER_MIN:
        new = magnitude + 1  # stay eligible
    else:
        new = magnitude + (1 if rng.integers(2) else -1)
    return new if value > 0 else -new


def _t1_carriers(blocks: list) -> list[tuple[int, int]]:
    """Highest-frequency trailing one of each luma block (sign-flip carrier)."""
    from src.core.stego import CAVLCSafetyFilter

    safety = CAVLCSafetyFilter()
    found = []
    for row, (_mb, block, coefficients) in enumerate(blocks):
        if block >= 16:
            continue
        trailing = safety._detect_trailing_ones(coefficients)
        if trailing:
            found.append((row, max(trailing)))
    return found


def sign_features(blocks: list, macroblocks_per_frame: int, frames: int) -> np.ndarray:
    """Per-position share of positive signs among +-1 levels and among trailing ones."""
    from src.core.stego import CAVLCSafetyFilter

    safety = CAVLCSafetyFilter()
    unit = np.zeros((frames, 2, steg.POSITIONS))
    trailing_counts = np.zeros((frames, 2, steg.POSITIONS))
    for macroblock, block, coefficients in blocks:
        frame = macroblock // macroblocks_per_frame
        if block >= 16 or frame >= frames:
            continue
        trailing = safety._detect_trailing_ones(coefficients)
        for index, value in enumerate(coefficients[: steg.POSITIONS]):
            if abs(value) == 1:
                unit[frame, int(value > 0), index] += 1
                if index in trailing:
                    trailing_counts[frame, int(value > 0), index] += 1
    unit_share = unit[:, 1] / np.maximum(unit.sum(axis=1), 1)
    trailing_share = trailing_counts[:, 1] / np.maximum(trailing_counts.sum(axis=1), 1)
    return np.hstack([unit_share, trailing_share])


def _features(blocks: list, mbs: int, frames: int) -> np.ndarray:
    return np.hstack([steg.coefficient_features(blocks, mbs, frames), sign_features(blocks, mbs, frames)])


def _carriers(blocks: list) -> list[tuple[int, int]]:
    from src.core.stego import CAVLCSafetyFilter, stable_blind_candidate_index

    safety = CAVLCSafetyFilter()
    found = []
    for row, (_mb, block, coefficients) in enumerate(blocks):
        if block >= 16:
            continue
        index = stable_blind_candidate_index(coefficients, safety._detect_trailing_ones(coefficients))
        if index is not None:
            found.append((row, index))
    return found


def simulate_case(name: str, segments_limit: int, densities: tuple[float, ...] = (1.0,)) -> dict[str, Any]:
    from benchmark._common import load_or_extract_idr_blocks
    from src.bitstream.bitstream_ops import BitstreamReconstructor
    from src.blind_sync_streaming import _split_video_into_segments

    cases = {case["name"]: case for case in json.loads(CASES_FILE.read_text(encoding="utf-8"))}
    case = cases[name]
    report = json.loads((RESULTS / f"e2e_{name}.json").read_text(encoding="utf-8"))
    mbs = case.get("macroblocks_per_frame", 396)
    rng = np.random.default_rng(SEED)
    arms = [("replacement", 1.0), ("matching", 1.0), ("t1_sign", 1.0)] + [
        ("replacement", density) for density in densities if density != 1.0]
    rows: dict[str, list[np.ndarray]] = {"cover": [], **{_arm(rule, d): [] for rule, d in arms}}
    with tempfile.TemporaryDirectory(prefix="latticezk-sim-") as directory:
        segments, _ = _split_video_into_segments(
            ROOT / case["video"], directory, 100, ffmpeg="ffmpeg", ffprobe="ffprobe")
        used = min(report["segments_used"], segments_limit)
        per_segment = report["carriers_used"] // report["segments_used"]
        for segment in segments[:used]:
            blocks = load_or_extract_idr_blocks(Path(segment), BitstreamReconstructor(), force=True)[0]
            frames = 1 + max(mb for mb, _b, _c in blocks) // mbs
            carrier_sets = {"magnitude": _carriers(blocks), "t1": _t1_carriers(blocks)}
            rows["cover"].append(_features(blocks, mbs, frames))
            for rule, density in arms:
                carriers = carrier_sets["t1" if rule == "t1_sign" else "magnitude"]
                size = min(int(per_segment * density), len(carriers))
                chosen = rng.choice(len(carriers), size=size, replace=False)
                bits = rng.integers(0, 2, size=len(chosen))
                stego = [(mb, b, list(c)) for mb, b, c in blocks]
                for pick, bit in zip(chosen, bits):
                    row, index = carriers[pick]
                    stego[row][2][index] = _modify(stego[row][2][index], int(bit), rule, rng)
                rows[_arm(rule, density)].append(_features(stego, mbs, frames))
    return {arm: np.concatenate(parts) for arm, parts in rows.items()}


def _arm(rule: str, density: float) -> str:
    return rule if density == 1.0 else f"{rule}@{density:g}"


def evaluate(features: dict[str, dict[str, np.ndarray]]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    clips = sorted(features)
    arms = [arm for arm in next(iter(features.values())) if arm != "cover"]
    for rule in arms:
        x, y, groups = [], [], []
        for clip in clips:
            cover, stego = features[clip]["cover"], features[clip][rule]
            changed = np.abs(cover - stego).sum(axis=1) > 0
            x += [cover[changed], stego[changed]]
            y += [np.zeros(changed.sum()), np.ones(changed.sum())]
            groups += [np.full(changed.sum() * 2, clip)]
        x, y, groups = np.vstack(x), np.concatenate(y), np.concatenate(groups)
        folds = []
        for clip in clips:
            model = steg._detectors()["fld_ensemble"]
            folds.append(steg._score(model, x[groups != clip], y[groups != clip],
                                     x[groups == clip], y[groups == clip]))
        report[rule] = {
            "p_e_mean": round(float(np.mean([fold["p_e"] for fold in folds])), 4),
            "auc_mean": round(float(np.mean([fold["auc"] for fold in folds])), 4),
            "folds": dict(zip(clips, folds)),
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", nargs="+", required=True)
    parser.add_argument("--segments", type=int, default=3)
    parser.add_argument("--densities", type=float, nargs="*", default=[1.0],
                        help="fractions of the real per-segment carrier count to simulate")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    features = {name: simulate_case(name, arguments.segments, tuple(arguments.densities))
                for name in arguments.cases}
    report = {"protocol": "leave-one-clip-out, coefficient features, FLD ensemble, simulated embedding",
              **evaluate(features)}
    text = json.dumps(report, indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
