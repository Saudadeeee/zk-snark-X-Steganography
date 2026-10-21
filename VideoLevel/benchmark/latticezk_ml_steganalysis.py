"""Learned steganalysis of lattice-ZK stego video, frame by frame.

Two stages:

``features`` extracts, for every frame of every segment the embedding touched,
the same features from the cover and the stego stream:

* **coefficient domain** (the carrier domain): per-zig-zag-position histograms
  of luma 4x4 magnitudes, odd-magnitude rates for ``|level| >= 4``,
  adjacent-position magnitude co-occurrences, and per-position shares of
  positive signs among +-1 levels and among trailing ones (340 values), so
  both magnitude and sign carriers are visible;
* **pixel domain**: a reduced spatial rich model -- first- and second-order
  luma residuals, quantised and truncated to ``[-2, 2]``, as 3-sample
  horizontal and vertical co-occurrences (500 values).

``evaluate`` trains detectors on cover/stego frame pairs and reports the
minimum average detection error ``P_E = min (P_FA + P_MD) / 2`` and AUC on
held-out data.  Splits keep each cover/stego pair together; with several clips
the main protocol is leave-one-clip-out.  The attacker is strong: it trains on
exact pairs from the same encoder settings and knows which frames carry bits.

    python -m benchmark.latticezk_ml_steganalysis features --cover c.h264 --stego s.h264 \\
        --label coastguard --output tmp/q2/features_coastguard.npz
    python -m benchmark.latticezk_ml_steganalysis evaluate tmp/q2/features_*.npz
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

POSITIONS = 16
MAGNITUDES = 16
COOCCURRENCE_LEVELS = 6
CARRIER_MIN_MAGNITUDE = 4
TRUNCATION = 2
RANDOM_SEED = 20261019


# -- features ------------------------------------------------------------- #

def coefficient_features(blocks: list, macroblocks_per_frame: int, frames: int) -> np.ndarray:
    """Per-frame carrier-domain statistics of luma 4x4 residual blocks."""
    from src.core.stego import CAVLCSafetyFilter

    trailing_detector = CAVLCSafetyFilter()
    histogram = np.zeros((frames, POSITIONS, MAGNITUDES))
    unit_signs = np.zeros((frames, 2, POSITIONS))
    trailing_signs = np.zeros((frames, 2, POSITIONS))
    odd = np.zeros((frames, POSITIONS))
    eligible = np.zeros((frames, POSITIONS))
    cooccurrence = np.zeros((frames, COOCCURRENCE_LEVELS, COOCCURRENCE_LEVELS))
    block_counts = np.zeros(frames)
    for macroblock, block, coefficients in blocks:
        if block >= 16:
            continue
        frame = macroblock // macroblocks_per_frame
        if frame >= frames:
            continue
        magnitudes = np.abs(np.asarray(coefficients[:POSITIONS], dtype=np.int64))
        if magnitudes.size < POSITIONS:
            magnitudes = np.pad(magnitudes, (0, POSITIONS - magnitudes.size))
        block_counts[frame] += 1
        histogram[frame, np.arange(POSITIONS), np.minimum(magnitudes, MAGNITUDES - 1)] += 1
        large = magnitudes >= CARRIER_MIN_MAGNITUDE
        eligible[frame] += large
        odd[frame] += large & (magnitudes % 2 == 1)
        clipped = np.minimum(magnitudes, COOCCURRENCE_LEVELS - 1)
        np.add.at(cooccurrence[frame], (clipped[:-1], clipped[1:]), 1)
        trailing = trailing_detector._detect_trailing_ones(coefficients)
        for index, value in enumerate(coefficients[:POSITIONS]):
            if abs(value) == 1:
                unit_signs[frame, int(value > 0), index] += 1
                if index in trailing:
                    trailing_signs[frame, int(value > 0), index] += 1
    scale = np.maximum(block_counts, 1)[:, None]
    return np.concatenate([
        (histogram.reshape(frames, -1) / scale),
        odd / np.maximum(eligible, 1),
        cooccurrence.reshape(frames, -1) / (scale * (POSITIONS - 1)),
        unit_signs[:, 1] / np.maximum(unit_signs.sum(axis=1), 1),
        trailing_signs[:, 1] / np.maximum(trailing_signs.sum(axis=1), 1),
    ], axis=1)


def _cooccurrence_3(residual: np.ndarray, axis: int) -> np.ndarray:
    levels = 2 * TRUNCATION + 1
    clipped = np.clip(np.rint(residual), -TRUNCATION, TRUNCATION).astype(np.int64) + TRUNCATION
    if axis == 1:
        a, b, c = clipped[:, :-2], clipped[:, 1:-1], clipped[:, 2:]
    else:
        a, b, c = clipped[:-2, :], clipped[1:-1, :], clipped[2:, :]
    index = (a * levels + b) * levels + c
    counts = np.bincount(index.ravel(), minlength=levels ** 3).astype(np.float64)
    return counts / counts.sum()


def pixel_features(luma: np.ndarray) -> np.ndarray:
    """Reduced SRM: 1st/2nd-order residual co-occurrences, both directions."""
    rows = []
    for frame in luma.astype(np.float64):
        first_h = frame[:, 1:] - frame[:, :-1]
        first_v = frame[1:, :] - frame[:-1, :]
        second_h = frame[:, :-2] - 2 * frame[:, 1:-1] + frame[:, 2:]
        second_v = frame[:-2, :] - 2 * frame[1:-1, :] + frame[2:, :]
        rows.append(np.concatenate([
            _cooccurrence_3(first_h, 1), _cooccurrence_3(first_v, 0),
            _cooccurrence_3(second_h, 1), _cooccurrence_3(second_v, 0),
        ]))
    return np.array(rows)


def decode_luma_native(video: Path, max_frames: int | None = None) -> np.ndarray:
    """Decode luma at the stream's own resolution (no rescaling)."""
    import subprocess

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0:s=x", str(video)],
        capture_output=True, text=True, timeout=600, check=True,
    )
    width, height = (int(value) for value in probe.stdout.strip().split("x"))
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(video)]
    if max_frames is not None:
        command += ["-frames:v", str(max_frames)]
    # Raw yuv420p keeps the decoded Y plane exactly; a "gray" conversion would rescale its range.
    command += ["-f", "rawvideo", "-pix_fmt", "yuv420p", "-"]
    raw = subprocess.run(command, capture_output=True, timeout=3600, check=True).stdout
    frame_bytes = width * height * 3 // 2
    frames = len(raw) // frame_bytes
    planes = np.frombuffer(raw[: frames * frame_bytes], dtype=np.uint8).reshape(frames, frame_bytes)
    return planes[:, : width * height].reshape(frames, height, width)


def _segment_features(segment: Path, macroblocks_per_frame: int) -> tuple[np.ndarray, np.ndarray]:
    from benchmark.legacy._common import load_or_extract_idr_blocks
    from src.bitstream.bitstream_ops import BitstreamReconstructor

    luma = decode_luma_native(segment)
    blocks = load_or_extract_idr_blocks(segment, BitstreamReconstructor(), force=True)[0]
    return coefficient_features(blocks, macroblocks_per_frame, len(luma)), pixel_features(luma)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(cover: Path, stego: Path, label: str, frames_per_segment: int,
            macroblocks_per_frame: int, max_segments: int | None) -> dict[str, np.ndarray]:
    from src.transport.blind_sync_streaming import _split_video_into_segments

    outputs: dict[str, list] = {name: [] for name in ("coeff", "pixel", "label", "pair", "modified")}
    with tempfile.TemporaryDirectory(prefix="latticezk-mlsteg-") as directory:
        root = Path(directory)
        (root / "cover").mkdir()
        (root / "stego").mkdir()
        cover_segments, _ = _split_video_into_segments(
            cover, str(root / "cover"), frames_per_segment, ffmpeg="ffmpeg", ffprobe="ffprobe")
        stego_segments, _ = _split_video_into_segments(
            stego, str(root / "stego"), frames_per_segment, ffmpeg="ffmpeg", ffprobe="ffprobe")
        touched = [index for index, (c, s) in enumerate(zip(cover_segments, stego_segments))
                   if _sha256(Path(c)) != _sha256(Path(s))]
        for index in touched[: max_segments or len(touched)]:
            cover_coeff, cover_pixel = _segment_features(Path(cover_segments[index]), macroblocks_per_frame)
            stego_coeff, stego_pixel = _segment_features(Path(stego_segments[index]), macroblocks_per_frame)
            frames = min(len(cover_coeff), len(stego_coeff))
            changed = (np.abs(cover_coeff[:frames] - stego_coeff[:frames]).sum(axis=1) > 0)
            for value, coeff, pixel in ((0, cover_coeff, cover_pixel), (1, stego_coeff, stego_pixel)):
                outputs["coeff"].append(coeff[:frames])
                outputs["pixel"].append(pixel[:frames])
                outputs["label"].append(np.full(frames, value))
                outputs["pair"].append(index * frames_per_segment + np.arange(frames))
                outputs["modified"].append(changed)
    return {
        "coeff": np.concatenate(outputs["coeff"]),
        "pixel": np.concatenate(outputs["pixel"]),
        "label": np.concatenate(outputs["label"]),
        "pair": np.concatenate(outputs["pair"]),
        "modified": np.concatenate(outputs["modified"]),
        "clip": np.array([label] * sum(len(item) for item in outputs["label"])),
    }


# -- evaluation ----------------------------------------------------------- #

def detection_error(labels: np.ndarray, scores: np.ndarray) -> float:
    """Minimum over thresholds of (P_FA + P_MD) / 2."""
    from sklearn.metrics import roc_curve

    false_alarm, true_positive, _ = roc_curve(labels, scores)
    return float(np.min((false_alarm + (1 - true_positive)) / 2))


def _detectors() -> dict[str, Any]:
    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
    from sklearn.ensemble import BaggingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return {
        "logistic": make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=5000)),
        "fld_ensemble": make_pipeline(StandardScaler(), BaggingClassifier(
            LinearDiscriminantAnalysis(solver="lsqr", shrinkage="auto"),
            n_estimators=51, max_features=0.3, bootstrap=False, random_state=RANDOM_SEED)),
    }


def _score(model: Any, train_x, train_y, test_x, test_y) -> dict[str, float]:
    from sklearn.metrics import roc_auc_score

    model.fit(train_x, train_y)
    scores = model.decision_function(test_x)
    return {"p_e": round(detection_error(test_y, scores), 4),
            "auc": round(float(roc_auc_score(test_y, scores)), 4)}


def evaluate(paths: list[Path]) -> dict[str, Any]:
    data = [dict(np.load(path)) for path in paths]
    merged = {key: np.concatenate([item[key] for item in data]) for key in data[0]}
    pair_modified = {}
    for clip, pair, modified in zip(merged["clip"], merged["pair"], merged["modified"]):
        pair_modified[(clip, pair)] = pair_modified.get((clip, pair), False) or bool(modified)
    keep = np.array([pair_modified[(c, p)] for c, p in zip(merged["clip"], merged["pair"])])
    feature_sets = {
        "coefficient": merged["coeff"][keep],
        "pixel": merged["pixel"][keep],
        "combined": np.hstack([merged["coeff"], merged["pixel"]])[keep],
    }
    labels, clips, pairs = merged["label"][keep], merged["clip"][keep], merged["pair"][keep]
    report: dict[str, Any] = {
        "frame_pairs": int(keep.sum() // 2),
        "clips": sorted(set(clips.tolist())),
        "protocols": {},
    }
    rng = np.random.default_rng(RANDOM_SEED)
    pair_keys = np.array([f"{c}/{p}" for c, p in zip(clips, pairs)])
    unique_pairs = np.unique(pair_keys)
    test_pairs = set(rng.choice(unique_pairs, size=len(unique_pairs) // 2, replace=False).tolist())
    is_test = np.array([key in test_pairs for key in pair_keys])
    splits = {"paired_half_split": [(~is_test, is_test)]}
    if len(report["clips"]) > 1:
        splits["leave_one_clip_out"] = [(clips != clip, clips == clip) for clip in report["clips"]]
    for protocol, folds in splits.items():
        results: dict[str, Any] = {}
        for feature_name, features in feature_sets.items():
            for detector_name in _detectors():
                fold_scores = [
                    _score(_detectors()[detector_name], features[train], labels[train],
                           features[test], labels[test])
                    for train, test in folds
                ]
                results[f"{feature_name}/{detector_name}"] = {
                    "p_e_mean": round(float(np.mean([s["p_e"] for s in fold_scores])), 4),
                    "auc_mean": round(float(np.mean([s["auc"] for s in fold_scores])), 4),
                    "folds": fold_scores,
                }
        report["protocols"][protocol] = results
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    features = commands.add_parser("features")
    features.add_argument("--cover", type=Path, required=True)
    features.add_argument("--stego", type=Path, required=True)
    features.add_argument("--label", required=True)
    features.add_argument("--output", type=Path, required=True)
    features.add_argument("--frames-per-segment", type=int, default=100)
    features.add_argument("--macroblocks-per-frame", type=int, default=396)
    features.add_argument("--max-segments", type=int)
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("features", nargs="+", type=Path)
    evaluation.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if arguments.command == "features":
        result = extract(arguments.cover.resolve(strict=True), arguments.stego.resolve(strict=True),
                         arguments.label, arguments.frames_per_segment,
                         arguments.macroblocks_per_frame, arguments.max_segments)
        np.savez_compressed(arguments.output, **result)
        summary = {"label": arguments.label, "rows": int(len(result["label"])),
                   "modified_rows": int(result["modified"].sum())}
        sys.stdout.write(json.dumps(summary) + "\n")
        return 0
    report = evaluate(arguments.features)
    text = json.dumps(report, indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
