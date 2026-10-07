"""Steganalysis dataset: cover/stego pairs of every method at three rates, split by source.

    py -3.12 -m benchmark.stego_dataset_new [--workers 3]

Covers: x264 medium, Baseline, QP 22, all-intra; CIF sequences with 60 frames and the
native HD sequences with 10 frames (feature extraction at 1080p is the bottleneck).
Rates per IDR: the system default of 64 bits, and 5% and 20% of the IDR's candidates.
Splits are by source (no sequence in two splits) and mix resolutions. Writes
benchmark/results/stego_compare/stego/ (git-ignored streams) and
benchmark/results/stego_compare/steganalysis_manifest.json.
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from benchmark.distortion_model_new import flipped_bits
from benchmark.stego_compare_new import OUT, _dimensions, encode_cover, sources
from benchmark.stego_embed_new import candidates, embed
from benchmark.stego_methods_new import METHODS

STEGO = OUT / "stego"
METHOD_NAMES = ("random", "low-drift", "kim2007", "lin2012", "wang2018", "liao2009")
RATES = {"cap64": lambda n: 64, "rate5": lambda n: max(1, round(0.05 * n)),
         "rate20": lambda n: max(1, round(0.20 * n))}
FRAMES = {"cif": 60, "hd": 10}
QP = 22
TEST = {"football_cif", "foreman_cif", "crowd_run_1080p50_60f", "park_joy_1080p50_60f", "rush_hour_1080p25_60f",
        "vidyo3_720p_60fps_60f", "720p50_shields_ter_60f"}
VALIDATION = {"hall_monitor_cif", "station2_1080p25_60f", "vidyo1_720p_60fps_60f"}


def split_of(source: str) -> str:
    return "test" if source in TEST else "val" if source in VALIDATION else "train"


def build(job: tuple[str, Path]) -> list[dict]:
    dataset, source = job
    width, height = _dimensions(source)
    cover = encode_cover(source, QP, 1, FRAMES[dataset])
    cands = candidates(cover, workers=2)
    entries = []
    for method in METHOD_NAMES:
        for rate, bits in RATES.items():
            stego = STEGO / f"{source.stem}__{method}__{rate}.h264"
            if not stego.is_file():
                partial = stego.with_suffix(".part")
                embed(cover, partial, cands, METHODS[method], bits,
                      f"steg|{source.stem}|{method}|{rate}".encode().ljust(32, b"\0")[:32])
                partial.replace(stego)
            # Frames whose IDR differs from the cover, recomputed from the files (fresh or reused stego).
            idr_order = {nal: index for index, nal in enumerate(sorted({c.nal for c in cands}))}
            carrying = sorted({idr_order[nal] for nal, _ in flipped_bits(cover.read_bytes(), stego.read_bytes())
                               if nal in idr_order})
            entries.append({"pair_id": f"{source.stem}|{method}|{rate}", "source": source.stem,
                            "split": split_of(source.stem), "method": method, "rate": rate,
                            "cover": str(cover), "stego": str(stego), "width": width, "height": height,
                            "frames": carrying or list(range(FRAMES[dataset]))})
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    STEGO.mkdir(parents=True, exist_ok=True)
    jobs = [(dataset, source) for dataset in ("cif", "hd") for source in sources(dataset)]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        manifest = [entry for entries in pool.map(build, jobs) for entry in entries]
    counts = {split: len({e["source"] for e in manifest if e["split"] == split}) for split in ("train", "val", "test")}
    (OUT / "steganalysis_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"{len(manifest)} pairs; sources per split {counts}")


if __name__ == "__main__":
    main()
