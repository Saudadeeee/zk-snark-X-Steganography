"""Experiments A, B and C of the distortion model (see benchmark/distortion_model_new.py).

    py -3.12 -m benchmark.distortion_experiments_new [--samples 100] [--only A|B|C]

Writes benchmark/results/distortion_new/{sequence_frames.csv, single_flips.csv,
inverse_check.csv, summary.json}.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from benchmark.distortion_model_new import (
    CATEGORY_NAMES,
    CONFIGS,
    MEDIA_RUN,
    OUT,
    RAW,
    _run,
    cap_for_target,
    chroma_qp,
    decode_planes,
    exact_block_flip_sse,
    flip_sse,
    flip_sse_exact,
    flipped_bits,
    flipped_raster,
    frame_sse,
    max_flips,
    hx,
    plane_of,
    psnr_from_sse,
    slice_qps,
    x264_options,
)
from benchmark.e2e_benchmark_new import file_offset_of_rbsp_bit
from benchmark.media_benchmark_new import _inspect_binary, _native_binary, _tool, inspect_segments

SOURCES_B = ("foreman_cif.y4m", "city_cif.y4m")
QPS_B = (22, 28, 34)
TARGETS_C = (40.0, 45.0, 50.0)
FRAMES_C = 30
REPETITIONS_C = 5  # independent keys and payloads per (config, target, policy)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _quantiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    pick = lambda q: ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1) + 0.5))]  # noqa: E731
    positive = [v for v in ordered if v > 0]
    return {"n": len(ordered),
            "geo_mean": math.exp(statistics.fmean(math.log(v) for v in positive)) if positive else 0.0,
            "mean": statistics.fmean(ordered), "p10": pick(0.10), "median": pick(0.5), "p90": pick(0.9),
            "p95": pick(0.95),
            "max": ordered[-1]}


# ------------------------------------------------------------------ A: sequence level

def _case_frames(case: dict[str, Any], run_dir: Path) -> list[dict[str, Any]]:
    stem = f"{Path(case['source']).stem}__{case['resolution']}__qp22_allintra_new"
    cover, stego = run_dir / "encoded_h264" / f"{stem}.h264", run_dir / "stego_h264" / f"{stem}__stego_new.h264"
    width, height = map(int, case["resolution"].split("x"))
    qps, offset = slice_qps(cover)
    segments = inspect_segments(_inspect_binary(), cover, 64)
    identity = {(c["nal_index"], c["rbsp_bit_offset"]): c["id"] for s in segments["segments"] for c in s["candidates"]}
    frame_of_nal = {s["idr_nal_index"]: s["segment"] for s in segments["segments"]}
    if len(frame_of_nal) != len(qps):
        raise RuntimeError(f"{stem}: {len(frame_of_nal)} IDR segments for {len(qps)} slices")
    predicted, flips = np.zeros((len(qps), 3)), np.zeros((len(qps), 3), dtype=int)
    for nal, bit in flipped_bits(cover.read_bytes(), stego.read_bytes()):
        if (nal, bit) not in identity:
            raise RuntimeError(f"{stem}: changed bit {nal}:{bit} is not a sign candidate")
        _, _, category, block, _ = map(int, identity[(nal, bit)].split(":"))
        frame, plane = frame_of_nal[nal], plane_of(category, block)
        qp = qps[frame] if plane == 0 else chroma_qp(qps[frame], offset)
        predicted[frame, plane] += flip_sse(qp)
        flips[frame, plane] += 1
    measured = frame_sse(decode_planes(cover, width, height), decode_planes(stego, width, height))
    return [{"source": Path(case["source"]).stem, "resolution": case["resolution"], "frame": f, "qp": qps[f],
             "flips_y": int(flips[f, 0]), "flips_c": int(flips[f, 1] + flips[f, 2]),
             "predicted_direct_sse_y": float(predicted[f, 0]), "measured_sse_y": float(measured[f, 0]),
             "predicted_direct_sse_c": float(predicted[f, 1] + predicted[f, 2]),
             "measured_sse_c": float(measured[f, 1] + measured[f, 2]), "pixels_y": width * height}
            for f in range(len(qps))]


LUMA = ("LumaDC", "Luma4x4")


def _psnr_error(row: dict[str, Any], gain: float) -> float:
    pixels = row["pixels_y"]
    return psnr_from_sse(gain * row["predicted_direct_sse_y"], pixels) - psnr_from_sse(row["measured_sse_y"], pixels)


def _abs_mean(values: list[float]) -> float:
    return statistics.fmean(abs(v) for v in values)


def experiment_a(run_dir: Path = MEDIA_RUN) -> list[dict[str, Any]]:
    cases = json.loads((run_dir / "video_pipeline_new.json").read_text(encoding="utf-8"))["results"]
    rows = [row for case in cases for row in _case_frames(case, run_dir)]
    _write_csv(OUT / "sequence_frames.csv", rows)
    return rows


def frame_gain_quantiles(gains: list[float], flips: int, draws: int = 20000, seed: int = 1) -> dict[str, float]:
    """Frame-level gain of `flips` carriers drawn from single-flip gains (additive model, Monte Carlo)."""
    rng = random.Random(seed)
    frames = sorted(statistics.fmean(rng.choice(gains) for _ in range(flips)) for _ in range(draws))
    return {"flips": flips, "mean": statistics.fmean(frames), "p50": frames[draws // 2],
            "p95": frames[int(0.95 * draws)], "p99": frames[int(0.99 * draws)]}


def _resolution_summary(part: list[dict[str, Any]]) -> dict[str, Any]:
    # Expected energy: ratio of sums (= flip-weighted mean of the per-flip gains).
    mean_gain = sum(r["measured_sse_y"] for r in part) / sum(r["predicted_direct_sse_y"] for r in part)
    held_out = []
    for source in sorted({r["source"] for r in part}):
        train = [r for r in part if r["source"] != source]
        gain = sum(r["measured_sse_y"] for r in train) / sum(r["predicted_direct_sse_y"] for r in train)
        held_out += [_psnr_error(r, gain) for r in part if r["source"] == source]
    errors = [_psnr_error(r, mean_gain) for r in part]
    predicted = [psnr_from_sse(mean_gain * r["predicted_direct_sse_y"], r["pixels_y"]) for r in part]
    measured = [psnr_from_sse(r["measured_sse_y"], r["pixels_y"]) for r in part]
    return {"frames": len(part), "mean_gain": mean_gain,
            "frame_gain": _quantiles([r["measured_sse_y"] / r["predicted_direct_sse_y"] for r in part]),
            "flips_per_frame_y": statistics.fmean(r["flips_y"] for r in part),
            "measured_psnr_median_db": statistics.median(measured),
            "psnr_bias_db": statistics.fmean(errors), "psnr_mae_db": _abs_mean(errors),
            "psnr_loso_mae_db": _abs_mean(held_out), "pearson_r": float(np.corrcoef(predicted, measured)[0, 1])}


def summarize_a(rows: list[dict[str, Any]], single: list[dict[str, Any]]) -> dict[str, Any]:
    used = [r for r in rows if r["flips_y"] and r["measured_sse_y"] > 0]
    resolutions = sorted({r["resolution"] for r in used}, key=lambda res: int(res.split("x")[0]))
    summary: dict[str, Any] = {
        "frames": len(rows), "frames_with_luma_flips": len(used),
        "flips_per_frame_y": statistics.fmean(r["flips_y"] for r in rows),
        "flips_per_frame_c": statistics.fmean(r["flips_c"] for r in rows),
        "by_resolution": {res: _resolution_summary([r for r in used if r["resolution"] == res]) for res in resolutions}}
    # Cross-experiment check: CIF sequence frames predicted from experiment B's single flips (same encoder).
    cif = [r for r in used if r["resolution"] == "352x288"]
    single_gains = [r["gain"] for r in single if r["config"] == "ultrafast" and r["category"] in LUMA]
    b_gain = statistics.fmean(single_gains)
    errors = [_psnr_error(r, b_gain) for r in cif]
    summary["cif_from_single_flips"] = {
        "gain_from_b": b_gain, "psnr_bias_db": statistics.fmean(errors), "psnr_mae_db": _abs_mean(errors),
        "predicted_frame_gain": frame_gain_quantiles(single_gains, round(statistics.fmean(r["flips_y"] for r in cif))),
        "measured_frame_gain": _quantiles([r["measured_sse_y"] / r["predicted_direct_sse_y"] for r in cif])}
    return summary


# ------------------------------------------------------------------ B: single flips

def encode(source: Path, output: Path, config: str, qp: int, frames: int) -> None:
    _run([_tool("ffmpeg"), "-v", "error", "-y", "-i", str(source), "-frames:v", str(frames), "-c:v", "libx264",
          *CONFIGS[config], "-profile:v", "baseline", "-qp", str(qp), "-g", "1", "-bf", "0", "-threads", "1",
          "-pix_fmt", "yuv420p", "-an", "-x264-params", "keyint=1:min-keyint=1:scenecut=0:slices=1:threads=1",
          "-f", "h264", str(output)])


def _single_flip_rows(path: Path, config: str, source: str, samples: int, rng: random.Random) -> list[dict]:
    trace = json.loads(_run([str(_inspect_binary()), str(path)]).stdout)
    if x264_options(path).get("aq") != "0":
        raise RuntimeError("experiment B assumes constant QP (x264 aq=0)")
    data = path.read_bytes()
    nals = {row["index"]: row for row in trace["nals"]}
    info = trace["slices"][0]
    qp, offset = info["initial_qp"], slice_qps(path)[1]
    width, height = info["mb_width"] * 16, info["mb_height"] * 16
    base, base_nd = decode_planes(path, width, height), decode_planes(path, width, height, deblock=False)
    pool = list(trace["candidates"])
    rng.shuffle(pool)
    rows: list[dict] = []
    with tempfile.TemporaryDirectory() as folder:
        edited = Path(folder) / "flip.h264"
        for cand in pool:
            if len(rows) == samples:
                break
            nal, mb, category, block, bit = cand["id"]
            offset_b = file_offset_of_rbsp_bit(data, nals[nal], bit)
            mask = 0x80 >> (bit % 8)
            if data[offset_b] < 4 or data[offset_b] ^ mask < 4:
                continue  # would create or remove an emulation-prevention byte
            patched = bytearray(data)
            patched[offset_b] ^= mask
            edited.write_bytes(bytes(patched))
            sse = frame_sse(base, decode_planes(edited, width, height))[0]
            decoded_nd = decode_planes(edited, width, height, deblock=False)
            sse_nd = frame_sse(base_nd, decoded_nd)[0]
            plane = plane_of(category, block)
            plane_qp = qp if plane == 0 else chroma_qp(qp, offset)
            row_c, col_c = flipped_raster(cand["coefficients_scan"], category)
            model = flip_sse(plane_qp)
            local = exact = None
            if category == 1 and cand["mb_type"] == 0 and len(cand["coefficients_scan"]) == 16:
                exact = exact_block_flip_sse(cand["coefficients_scan"], qp)
                bx, by = hx.block_xy(block)
                x, y = mb % info["mb_width"] * 16 + bx * 4, mb // info["mb_width"] * 16 + by * 4
                local = float(((decoded_nd[0][0, y:y + 4, x:x + 4] - base_nd[0][0, y:y + 4, x:x + 4]) ** 2).sum())
            rows.append({"config": config, "source": source, "qp": qp, "plane_qp": plane_qp,
                         "category": CATEGORY_NAMES[category], "mb_class": "I4x4" if cand["mb_type"] == 0 else "I16x16",
                         "mb_row_fraction": (mb // info["mb_width"]) / max(1, info["mb_height"] - 1),
                         "coef_row": row_c, "coef_col": col_c, "model_sse": model,
                         "pre_rounding_sse": flip_sse_exact(plane_qp, row_c, col_c),
                         "exact_block_sse": exact, "measured_block_sse_no_deblock": local,
                         "measured_sse_no_deblock": float(sse_nd[plane]), "measured_sse": float(sse[plane]),
                         "gain_no_deblock": float(sse_nd[plane]) / model, "gain": float(sse[plane]) / model})
    return rows


def experiment_b(samples: int) -> list[dict[str, Any]]:
    rng = random.Random(20261005)
    rows: list[dict] = []
    with tempfile.TemporaryDirectory() as folder:
        for config in CONFIGS:
            for source in SOURCES_B:
                for qp in QPS_B:
                    path = Path(folder) / f"{config}_{Path(source).stem}_{qp}.h264"
                    encode(RAW / source, path, config, qp, 1)
                    rows += _single_flip_rows(path, config, Path(source).stem, samples, rng)
    _write_csv(OUT / "single_flips.csv", rows)
    return rows


def _config_summary(part: list[dict[str, Any]]) -> dict[str, Any]:
    luma = [r for r in part if r["category"] in LUMA]
    return {
        "category": {c: _quantiles([r["gain"] for r in part if r["category"] == c])
                     for c in CATEGORY_NAMES if any(r["category"] == c for r in part)},
        "luma": _quantiles([r["gain"] for r in luma]),
        "luma_no_deblock": _quantiles([r["gain_no_deblock"] for r in luma]),
        "chroma": _quantiles([r["gain"] for r in part if r["category"] not in LUMA]),
        "luma_by_qp": {str(q): _quantiles([r["gain"] for r in luma if r["qp"] == q])
                       for q in sorted({r["qp"] for r in luma})},
        "luma_by_mb_class": {k: _quantiles([r["gain"] for r in luma if r["mb_class"] == k])
                             for k in ("I4x4", "I16x16") if any(r["mb_class"] == k for r in luma)},
        "frame_gain_mc": [frame_gain_quantiles([r["gain"] for r in luma], n) for n in (20, 40, 80)],
    }


def summarize_b(rows: list[dict[str, Any]]) -> dict[str, Any]:
    exact = [r for r in rows if r["exact_block_sse"] is not None]
    return {
        "samples": len(rows),
        # Decoder check: the flipped block's own change equals the exact (rounded) residual change.
        "block_exact_match": sum(r["measured_block_sse_no_deblock"] == r["exact_block_sse"] for r in exact),
        "block_exact_total": len(exact),
        "exact_over_model": _quantiles([r["exact_block_sse"] / r["model_sse"] for r in exact if r["exact_block_sse"]]),
        "pre_rounding_over_model": _quantiles([r["pre_rounding_sse"] / r["model_sse"] for r in rows]),
        "configs": {config: _config_summary([r for r in rows if r["config"] == config])
                    for config in CONFIGS},
    }


# ------------------------------------------------------------------ C: inverse check

def _conservative_gain(gains: list[float], target: float, qp: int, pixels: int, quantile: str) -> float:
    """Fixed point of: gain = quantile of the frame gain for the number of flips that gain allows."""
    gain = statistics.fmean(gains)
    for _ in range(4):
        flips = max(1, round(max_flips(target, qp, gain, pixels)))
        gain = frame_gain_quantiles(gains, flips, draws=4000)[quantile]
    return gain


def _embed_and_measure(cover: Path, base: list[np.ndarray], idr_nals: list[int], cap: int, out: Path,
                       width: int, height: int, rng: random.Random) -> list[tuple[int, float]]:
    capacity = inspect_segments(_inspect_binary(), cover, cap)["candidate_capacity_bits"]
    payload = rng.randbytes(max(1, min(4096, capacity // 8 - 3)))
    _run([str(_native_binary()), "embed-stream-auth-stdin", str(cover), str(out), str(cap)],
         stdin=(rng.randbytes(32).hex() + "\n" + payload.hex() + "\n").encode())
    carrying = sorted({idr_nals.index(nal) for nal, _ in flipped_bits(cover.read_bytes(), out.read_bytes())})
    full = carrying[:-1] if len(carrying) > 1 else carrying  # the last carrying IDR may be partly filled
    sse = frame_sse(base, decode_planes(out, width, height))[:, 0]
    return [(i, psnr_from_sse(float(sse[i]), width * height)) for i in full]


def _candidates_per_idr(trace: dict[str, Any], idr_nals: list[int]) -> list[int]:
    counts = {nal: 0 for nal in idr_nals}
    for candidate in trace["candidates"]:
        if candidate["id"][0] in counts:
            counts[candidate["id"][0]] += 1
    return [counts[nal] for nal in idr_nals]


def _sequence_gain_p95(sequence: list[dict[str, Any]]) -> float:
    """95th percentile of the frame-level gain of the CIF sequence frames (experiment A, ultrafast encodes)."""
    gains = sorted(r["measured_sse_y"] / r["predicted_direct_sse_y"] for r in sequence
                   if r["resolution"] == "352x288" and r["flips_y"] and r["measured_sse_y"] > 0)
    return gains[int(0.95 * (len(gains) - 1))]


def experiment_c(single: list[dict[str, Any]], sequence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Caps from a target PSNR under three gain policies, embedded and measured.

    expected     mean single-flip gain (B): expected energy meets the budget
    p95          95th percentile of a Monte Carlo frame gain built from B (independent flips)
    p95_sequence 95th percentile of measured frame gains of experiment A (ultrafast only: same encoder)
    """
    rows: list[dict] = []
    rng = random.Random(20261006)
    source = RAW / "foreman_cif_300f.y4m"
    with tempfile.TemporaryDirectory() as folder:
        for config in CONFIGS:
            gains = [r["gain"] for r in single if r["config"] == config and r["category"] in LUMA]
            cover = Path(folder) / f"cover_{config}.h264"
            encode(source, cover, config, 22, FRAMES_C)
            trace = json.loads(_run([str(_inspect_binary()), str(cover)]).stdout)
            info = trace["slices"][0]
            width, height, qp = info["mb_width"] * 16, info["mb_height"] * 16, info["initial_qp"]
            luma_share = sum(c["id"][2] in (0, 1) for c in trace["candidates"]) / len(trace["candidates"])
            idr_nals = [row["index"] for row in trace["nals"] if row["type"] == 5]
            per_idr = _candidates_per_idr(trace, idr_nals)
            base = decode_planes(cover, width, height)
            policies = {"expected": lambda _t: statistics.fmean(gains),
                        "p95": lambda t: _conservative_gain(gains, t, qp, width * height, "p95")}
            if config == "ultrafast":
                policies["p95_sequence"] = lambda _t: _sequence_gain_p95(sequence)
            for target in TARGETS_C:
                for policy, gain_of in policies.items():
                    gain = gain_of(target)
                    cap = cap_for_target(target, qp, gain, width * height, 0.5 * luma_share)
                    for repetition in range(REPETITIONS_C):
                        out = Path(folder) / f"stego_{config}_{int(target)}_{policy}_{repetition}.h264"
                        rows += [{"config": config, "target_db": target, "policy": policy, "gain": gain,
                                  "luma_share": luma_share, "cap_bits_per_idr": cap,
                                  "frame_candidates": per_idr[i], "saturated": int(cap >= per_idr[i]),
                                  "repetition": repetition, "frame": i, "psnr_y": psnr}
                                 for i, psnr in _embed_and_measure(cover, base, idr_nals, cap, out, width, height,
                                                                   rng)]
    _write_csv(OUT / "inverse_check.csv", rows)
    return rows


def summarize_c(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in sorted({(r["config"], r["target_db"], r["policy"]) for r in rows}):
        part = [r for r in rows if (r["config"], r["target_db"], r["policy"]) == key]
        values = [r["psnr_y"] for r in part]
        summary.setdefault(key[0], {}).setdefault(f"{key[1]:.0f}", {})[key[2]] = {
            "gain": part[0]["gain"], "cap_bits_per_idr": part[0]["cap_bits_per_idr"],
            "saturated_share": statistics.fmean(r["saturated"] for r in part), "frames": len(values),
            "min_db": min(values), "p05_db": sorted(values)[int(0.05 * (len(values) - 1))],
            "median_db": statistics.median(values),
            "share_at_or_above_target": sum(v >= key[1] for v in values) / len(values)}
    return summary


def _load_csv(name: str) -> list[dict[str, Any]]:
    def value(text: str) -> Any:
        if text == "":
            return None
        for kind in (int, float):
            try:
                return kind(text)
            except ValueError:
                pass
        return text
    with (OUT / name).open(encoding="utf-8") as handle:
        return [{k: value(v) for k, v in row.items()} for row in csv.DictReader(handle)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--samples", type=int, default=100, help="single flips per (config, source, QP)")
    parser.add_argument("--reuse", default="", help="experiments whose CSV is reused instead of rerun, e.g. AB")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    sequence = _load_csv("sequence_frames.csv") if "A" in args.reuse else experiment_a()
    single = _load_csv("single_flips.csv") if "B" in args.reuse else experiment_b(args.samples)
    inverse = _load_csv("inverse_check.csv") if "C" in args.reuse else experiment_c(single, sequence)
    summary = {"A_sequence": summarize_a(sequence, single), "B_single_flips": summarize_b(single),
               "C_inverse": summarize_c(inverse)}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary["C_inverse"], indent=1))


if __name__ == "__main__":
    main()
