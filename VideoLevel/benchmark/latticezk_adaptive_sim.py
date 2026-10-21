"""Simulated selection of the cost model for adaptive (syndrome-coded) carriers.

For every 100-frame segment of each cover it builds the real stable carrier
set (the exact patchability analysis the embedder uses), then writes the
per-segment registered-envelope bits with several rules:

* ``direct``        -- the current pipeline: one bit per carrier on a random
  subset (keyed order), LSB replacement;
* ``stc/<model>``   -- syndrome-trellis coding over *all* stable carriers of
  the segment with the given cost model (Viterbi minimises the summed cost).

It reports the number of changed carriers and the leave-one-clip-out P_E of
the coefficient-domain FLD ensemble from ``latticezk_ml_steganalysis``.  The
bitstream is not rebuilt, so this isolates the statistical effect; the real
E2E comparison is ``latticezk_adaptive_e2e``.

    python -m benchmark.latticezk_adaptive_sim --videos a_200.h264 b_200.h264 \\
        --work tmp/adaptive_sim --output benchmark/results/q2/adaptive_sim.json
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark import latticezk_ml_steganalysis as steg  # noqa: E402
from src.core import adaptive_carriers as ac  # noqa: E402

SEED = 20261021
MACROBLOCKS = 396
REGISTERED_ENVELOPE_CHUNK = 4200  # two chunks of the 8 165-byte v2 envelope


def _segment_bits(envelope_bytes: int, chunk_bytes: int) -> list[int]:
    from src.blind_payload_chunks import pack_payload_chunks
    from src.blind_sync import pack_blind_payload

    chunks = pack_payload_chunks(bytes(envelope_bytes), chunk_size=chunk_bytes)
    return [len(pack_blind_payload(chunk)) * 8 for chunk in chunks]


def _variant_costs(positions, coefficients) -> dict[str, list[float]]:
    """Cost variants explored; ``texture-magnitude-v1`` is the shipped one."""
    blocks = {(mb, blk): levels for mb, blk, levels in coefficients}
    texture = ac.macroblock_texture(coefficients)
    q = np.array([max(1, abs(blocks[(mb, blk)][k]) >> 1) for mb, blk, k in positions], float)
    t = np.array([texture.get(mb, 0) for mb, _blk, _k in positions], float)
    k = np.array([k for _mb, _blk, k in positions], float)
    tex = 1.0 + t / ac.TEXTURE_SCALE
    return {
        "uniform": np.ones(len(positions)).tolist(),
        "magnitude": (1.0 / q).tolist(),
        "magnitude2": (1.0 / q ** 2).tolist(),
        "texture": (1.0 / tex).tolist(),
        "texture-magnitude-v1": ac.carrier_costs(positions, coefficients, "texture-magnitude-v1"),
        "texture-magnitude2": (1.0 / (q ** 2 * tex)).tolist(),
        "high-frequency": (1.0 / k).tolist(),
    }


def _apply(coefficients, positions, stego_bits) -> tuple[list, int]:
    rows = {(mb, blk): index for index, (mb, blk, _c) in enumerate(coefficients)}
    stego = [(mb, blk, list(levels)) for mb, blk, levels in coefficients]
    changes = 0
    for (mb, blk, k), bit in zip(positions, stego_bits):
        levels = stego[rows[(mb, blk)]][2]
        magnitude = abs(levels[k])
        if magnitude & 1 != bit:
            new = magnitude ^ 1
            levels[k] = new if levels[k] > 0 else -new
            changes += 1
    return stego, changes


def simulate_video(video: Path, envelope_bytes: int, chunk_bytes: int, height: int,
                   log: Callable[[str], None]) -> dict[str, Any]:
    from src.blind_sync_streaming import _split_video_into_segments
    from src.core.analysis_cache import clear_video_analysis_cache, load_or_build_video_analysis

    rng = np.random.default_rng(SEED)
    per_segment_bits = _segment_bits(envelope_bytes, chunk_bytes)
    features: dict[str, list[np.ndarray]] = {}
    changes: dict[str, int] = {}
    carriers: list[int] = []
    with tempfile.TemporaryDirectory(prefix="adaptive-sim-") as directory:
        segments, _ = _split_video_into_segments(video, directory, 100)
        for segment, bits_needed in zip(segments, per_segment_bits):
            started = time.perf_counter()
            analysis = load_or_build_video_analysis(segment, use_cache=True, stable_blind_only=True)
            coefficients, positions = analysis[0], list(analysis[5])
            clear_video_analysis_cache()
            log(f"{video.name} {Path(segment).name}: {len(positions)} carriers for {bits_needed} bits "
                f"(analysis {time.perf_counter() - started:.0f}s)")
            if len(positions) < bits_needed:
                raise ValueError(f"{video.name}: segment capacity {len(positions)} < {bits_needed}")
            carriers.append(len(positions))
            frames = 1 + max(mb for mb, _b, _c in coefficients) // MACROBLOCKS
            order = rng.permutation(len(positions))
            positions = [positions[i] for i in order]
            levels_by_block = {(mb, blk): lv for mb, blk, lv in coefficients}
            cover_bits = [abs(levels_by_block[(mb, blk)][k]) & 1 for mb, blk, k in positions]
            message = rng.integers(0, 2, bits_needed).tolist()
            features.setdefault("cover", []).append(steg.coefficient_features(coefficients, MACROBLOCKS, frames))
            arms = {"direct": positions[:bits_needed]}
            direct_stego, count = _apply(coefficients, arms["direct"], message)
            features.setdefault("direct", []).append(steg.coefficient_features(direct_stego, MACROBLOCKS, frames))
            changes["direct"] = changes.get("direct", 0) + count
            for model, costs in _variant_costs(positions, coefficients).items():
                stego_bits = ac.stc_embed(cover_bits, message, costs, height)
                assert ac.stc_extract(stego_bits, bits_needed, height) == message
                stego, count = _apply(coefficients, positions, stego_bits)
                arm = f"stc/{model}"
                features.setdefault(arm, []).append(steg.coefficient_features(stego, MACROBLOCKS, frames))
                changes[arm] = changes.get(arm, 0) + count
            del coefficients, analysis
    return {
        "features": {arm: np.concatenate(parts) for arm, parts in features.items()},
        "changes": changes,
        "carriers": carriers,
        "payload_bits": per_segment_bits,
    }


def evaluate(per_clip: dict[str, dict[str, np.ndarray]]) -> dict[str, Any]:
    clips = sorted(per_clip)
    arms = [arm for arm in next(iter(per_clip.values())) if arm != "cover"]
    report: dict[str, Any] = {}
    for arm in arms:
        x, y, groups = [], [], []
        for clip in clips:
            cover, stego = per_clip[clip]["cover"], per_clip[clip][arm]
            changed = np.abs(cover - stego).sum(axis=1) > 0
            x += [cover[changed], stego[changed]]
            y += [np.zeros(changed.sum()), np.ones(changed.sum())]
            groups.append(np.full(changed.sum() * 2, clip))
        x, y, groups = np.vstack(x), np.concatenate(y), np.concatenate(groups)
        folds = {}
        for clip in clips:
            model = steg._detectors()["fld_ensemble"]
            folds[clip] = steg._score(model, x[groups != clip], y[groups != clip],
                                      x[groups == clip], y[groups == clip])
        report[arm] = {
            "p_e_mean": round(float(np.mean([f["p_e"] for f in folds.values()])), 4),
            "auc_mean": round(float(np.mean([f["auc"] for f in folds.values()])), 4),
            "folds": folds,
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--videos", nargs="+", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    from src.lattice_zk import video_proof
    from src.lattice_zk.params import BDLOP_OPEN_128

    parser.add_argument("--envelope-bytes", type=int,
                        default=video_proof.envelope_size(BDLOP_OPEN_128, registered=True))
    parser.add_argument("--chunk-bytes", type=int, default=REGISTERED_ENVELOPE_CHUNK)
    parser.add_argument("--height", type=int, default=10)
    arguments = parser.parse_args()
    arguments.work.mkdir(parents=True, exist_ok=True)

    def log(message: str) -> None:
        sys.stderr.write(time.strftime("%H:%M:%S ") + message + "\n")
        sys.stderr.flush()

    per_clip, counts = {}, {}
    for video in arguments.videos:
        clip = video.stem
        cached = arguments.work / f"{clip}.npz"
        meta = arguments.work / f"{clip}.json"
        if cached.exists() and meta.exists():
            per_clip[clip] = dict(np.load(cached))
            counts[clip] = json.loads(meta.read_text(encoding="utf-8"))
            continue
        result = simulate_video(video.resolve(strict=True), arguments.envelope_bytes,
                                arguments.chunk_bytes, arguments.height, log)
        np.savez_compressed(cached, **result["features"])
        counts[clip] = {key: result[key] for key in ("changes", "carriers", "payload_bits")}
        meta.write_text(json.dumps(counts[clip], indent=2), encoding="utf-8")
        per_clip[clip] = result["features"]
    report = {
        "protocol": "simulated embedding of the registered envelope (2 x 100 frames per clip), "
                    "real stable carriers, coefficient features, FLD ensemble, leave-one-clip-out",
        "constraint_height": arguments.height,
        "clips": counts,
        "detection": evaluate(per_clip),
    }
    text = json.dumps(report, indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
