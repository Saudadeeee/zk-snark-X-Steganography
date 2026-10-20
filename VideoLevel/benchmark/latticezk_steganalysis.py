"""Passive steganalysis of a lattice-ZK stego stream against its cover.

The stable carrier profile writes payload bits into the magnitude LSB of one
AC coefficient with ``|level| >= 4`` per luma block.  Compares the first
``--frames`` frames of both streams with:

* the Westfeld-Pfitzmann pairs-of-values (PoV) chi-square attack on the
  magnitudes ``(2k, 2k+1)``, ``k >= 2`` -- the targeted detector for LSB
  embedding in this domain (p near 1 means "looks embedded");
* a two-sample contingency test of the magnitude histogram against the cover;
* trailing-one sign tests as a control (that domain is not modified);
* SPA and RS on decoded luma, as pixel-domain reference detectors.

    python -m benchmark.latticezk_steganalysis --cover cover.h264 --stego stego.h264
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark._common import load_or_extract_idr_blocks  # noqa: E402
from benchmark.latticezk_ml_steganalysis import decode_luma_native  # noqa: E402
from benchmark.sec4_security import chi_square_t1_signs, rs_analysis, spa_estimate  # noqa: E402

SCAN_POSITIONS = 16
MAGNITUDE_BINS = 64
CARRIER_MIN_MAGNITUDE = 4


def _prefix(video: Path, frames: int, directory: Path) -> Path:
    """Copy the first ``frames`` access units without re-encoding."""
    output = directory / f"{video.stem}.prefix.h264"
    completed = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(video),
         "-c:v", "copy", "-frames:v", str(frames), "-f", "h264", str(output)],
        capture_output=True, text=True, timeout=1800, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg prefix copy failed: {completed.stderr[-400:]}")
    return output


def _coefficient_features(video: Path) -> dict[str, Any]:
    """Trailing-one signs (overall and per scan position) and magnitude counts."""
    from src.bitstream.bitstream_ops import BitstreamReconstructor

    blocks = load_or_extract_idr_blocks(video, BitstreamReconstructor(), force=True)[0]
    signs: list[int] = []
    per_position = np.zeros((2, SCAN_POSITIONS), dtype=np.int64)
    magnitudes: Counter[int] = Counter()
    for _mb, _block, coefficients in blocks:
        for value in coefficients:
            if value:
                magnitudes[min(abs(value), MAGNITUDE_BINS)] += 1
        trailing = 0
        for index in range(len(coefficients) - 1, -1, -1):
            value = coefficients[index]
            if value == 0:
                continue
            if abs(value) != 1 or trailing == 3:
                break
            trailing += 1
            positive = 1 if value > 0 else 0
            signs.append(positive)
            per_position[positive, min(index, SCAN_POSITIONS - 1)] += 1
    return {"signs": signs, "per_position": per_position, "magnitudes": magnitudes}


def _contingency_p(cover: np.ndarray, stego: np.ndarray) -> tuple[float, float]:
    table = np.concatenate([cover, stego], axis=0)
    table = table[:, table.sum(axis=0) > 0]
    statistic, p_value, _dof, _expected = stats.chi2_contingency(table)
    return float(statistic), float(p_value)


def analyse(cover: Path, stego: Path, frames: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="latticezk-steg-") as directory:
        cover_prefix = _prefix(cover, frames, Path(directory))
        stego_prefix = _prefix(stego, frames, Path(directory))
        features = {name: _coefficient_features(path)
                    for name, path in (("cover", cover_prefix), ("stego", stego_prefix))}
        luma = {name: decode_luma_native(path, max_frames=frames)
                for name, path in (("cover", cover_prefix), ("stego", stego_prefix))}

    cover_signs, stego_signs = features["cover"]["signs"], features["stego"]["signs"]
    sign_chi, sign_p = chi_square_t1_signs(stego_signs, cover_signs)
    position_chi, position_p = _per_position_test(features)
    bins = range(1, MAGNITUDE_BINS + 1)
    magnitude_table = np.array([
        [features[name]["magnitudes"].get(level, 0) for level in bins] for name in ("cover", "stego")
    ])
    populated = (magnitude_table >= 5).all(axis=0)
    magnitude_chi, magnitude_p = _contingency_p(
        magnitude_table[:1, populated], magnitude_table[1:, populated]
    )
    rs = {name: rs_analysis(luma[name].astype(np.uint8)) for name in luma}
    return {
        "frames_analysed": frames,
        "trailing_one_signs": {
            "cover_count": len(cover_signs), "stego_count": len(stego_signs),
            "cover_positive_fraction": round(float(np.mean(cover_signs)), 6),
            "stego_positive_fraction": round(float(np.mean(stego_signs)), 6),
            "two_sample_chi_square": round(sign_chi, 4), "p_value": sign_p,
        },
        "per_scan_position_signs": {"chi_square": round(position_chi, 4), "p_value": position_p},
        "pairs_of_values_attack": {
            name: _pairs_of_values(features[name]["magnitudes"]) for name in ("cover", "stego")
        },
        "magnitude_histogram": {
            "identical": bool(np.array_equal(magnitude_table[0], magnitude_table[1])),
            "chi_square": round(magnitude_chi, 4), "p_value": magnitude_p,
        },
        "pixel_reference_detectors": {
            "spa_cover": round(spa_estimate(luma["cover"].astype(np.uint8)), 6),
            "spa_stego": round(spa_estimate(luma["stego"].astype(np.uint8)), 6),
            "rs_delta_cover": round(rs["cover"]["delta"], 6),
            "rs_delta_stego": round(rs["stego"]["delta"], 6),
        },
        "note": "two-sample tests compare against the exact cover; p < 0.05 means detectable",
    }


def _pairs_of_values(magnitudes: Counter[int]) -> dict[str, float]:
    """Westfeld-Pfitzmann PoV statistic over carrier-eligible magnitude pairs."""
    statistic, dof = 0.0, 0
    for low in range(CARRIER_MIN_MAGNITUDE, MAGNITUDE_BINS - 1, 2):
        observed, partner = magnitudes.get(low, 0), magnitudes.get(low + 1, 0)
        expected = (observed + partner) / 2
        if expected >= 5:
            statistic += (observed - expected) ** 2 / expected
            dof += 1
    embedding_probability = float(stats.chi2.sf(statistic, dof - 1)) if dof > 1 else 0.0
    return {"chi_square": round(statistic, 4), "pairs": dof,
            "embedding_probability": embedding_probability}


def _per_position_test(features: dict[str, Any]) -> tuple[float, float]:
    """Contingency of (stream, scan position) over positive trailing-one signs."""
    rows = []
    for name in ("cover", "stego"):
        table = features[name]["per_position"]
        rows.append(table[1])
        rows.append(table[0])
    combined = np.array(rows)  # cover+, cover-, stego+, stego-
    cover_rate = combined[0] / np.maximum(combined[0] + combined[1], 1)
    expected_pos = cover_rate * (combined[2] + combined[3])
    expected_neg = (combined[2] + combined[3]) - expected_pos
    mask = (expected_pos >= 5) & (expected_neg >= 5)
    statistic = float(
        (((combined[2] - expected_pos) ** 2 / np.where(mask, expected_pos, 1))[mask]).sum()
        + (((combined[3] - expected_neg) ** 2 / np.where(mask, expected_neg, 1))[mask]).sum()
    )
    dof = int(mask.sum())
    return statistic, float(stats.chi2.sf(statistic, dof)) if dof else 1.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cover", type=Path, required=True)
    parser.add_argument("--stego", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = analyse(arguments.cover.resolve(strict=True), arguments.stego.resolve(strict=True),
                     arguments.frames)
    text = json.dumps(report, indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
