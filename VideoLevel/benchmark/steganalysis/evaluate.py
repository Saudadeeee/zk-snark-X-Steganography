"""Train / select / test a steganalyser over a cover-stego manifest.

Usage::

    py -3.12 -m benchmark.steganalysis.evaluate --manifest pairs.json --detector cavlc
        [--out results.json] [--workers 4] [--d-sub 25,50,100,200] [--learners 51]
        [--epochs 60] [--tile 256] [--max-tiles 8] [--seed 0]

One detector is trained per (method, rate) group on the "train" split;
hyper-parameters (FLD-ensemble d_sub, CNN epoch) are chosen by P_E on "val"
and the chosen detector is reported on "test". Metrics are given per frame
(every frame listed in "frames" is one cover and one stego sample) and per
stream (frame scores averaged over a stream; n = number of test pairs).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from .common import DEFAULT_CACHE_DIR, Pair, load_manifest
from .datasets import DETECTORS, FrameTable, StreamJob, build_table, run_job
from .ensemble import EnsembleConfig, train_ensemble
from .metrics import summarise

DEFAULT_D_SUB = (10, 25, 50, 100, 200, 400, 800)


def _metrics(cover_scores: np.ndarray, stego_scores: np.ndarray, owners: np.ndarray) -> dict[str, float]:
    labels = np.r_[np.zeros(cover_scores.size), np.ones(stego_scores.size)]
    frame = summarise(np.r_[cover_scores, stego_scores], labels)
    groups = np.unique(owners)
    cover_stream = np.array([cover_scores[owners == g].mean() for g in groups])
    stego_stream = np.array([stego_scores[owners == g].mean() for g in groups])
    stream = summarise(np.r_[cover_stream, stego_stream], np.r_[np.zeros(groups.size), np.ones(groups.size)])
    return {"frame_auc": frame["auc"], "frame_p_e": frame["p_e"],
            "stream_auc": stream["auc"], "stream_p_e": stream["p_e"]}


def _split_counts(pairs: Sequence[Pair], frames_of: dict[str, int]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for split in ("train", "val", "test"):
        members = [p for p in pairs if p.split == split]
        counts[f"n_{split}_pairs"] = len(members)
        counts[f"n_{split}_frames"] = sum(frames_of[p.pair_id] for p in members)
    return counts


def _rows(table: FrameTable, pairs: Sequence[Pair], split: str) -> FrameTable:
    wanted = np.array([pair.split == split for pair in pairs])
    return table.select(np.flatnonzero(wanted[table.pair_index]))


def evaluate_features(pairs: Sequence[Pair], detector: str, args: argparse.Namespace) -> dict:
    """FLD ensemble on one feature set; returns the group report."""
    table = build_table(pairs, detector, args.cache_dir, args.workers)
    train, val, test = (_rows(table, pairs, split) for split in ("train", "val", "test"))
    dimension = table.cover.shape[1]
    grid = [d for d in args.d_sub if d <= dimension] or [dimension]
    candidates = []
    for d_sub in grid:
        model = train_ensemble(train.cover, train.stego, EnsembleConfig(d_sub, args.learners, args.seed))
        if val.size:
            score = _metrics(model.decision_function(val.cover), model.decision_function(val.stego),
                             val.pair_index)["frame_p_e"]
        else:
            score = model.oob_error
        candidates.append((score, d_sub, model))
    val_pe, d_sub, model = min(candidates, key=lambda item: (item[0], item[1]))
    report = _metrics(model.decision_function(test.cover), model.decision_function(test.stego), test.pair_index)
    report.update({"feature_dim": int(dimension), "selected_d_sub": int(d_sub), "learners": args.learners,
                   "selection": "val_p_e" if val.size else "oob_error", "selection_p_e": float(val_pe),
                   "oob_error": float(model.oob_error),
                   "d_sub_scores": {str(d): float(s) for s, d, _ in candidates}})
    return report


def _tiles(pairs: Sequence[Pair], split: str, args: argparse.Namespace, tile: int
           ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    covers, stegos, owners, pair_of_frame = [], [], [], []
    row = 0
    for index, pair in enumerate(p for p in pairs if p.split == split):
        stacks = [run_job(StreamJob(stream, pair.width, pair.height, pair.frames, "cnn", args.cache_dir,
                                    tile, args.max_tiles)) for stream in (pair.cover, pair.stego)]
        n_frames, n_tiles = stacks[0].shape[:2]
        covers.append(stacks[0].reshape(-1, tile, tile))
        stegos.append(stacks[1].reshape(-1, tile, tile))
        owners.append(np.repeat(np.arange(row, row + n_frames), n_tiles))
        pair_of_frame.append(np.full(n_frames, index))
        row += n_frames
    if not covers:
        empty = np.zeros((0, tile, tile), np.uint8)
        return empty, empty, np.zeros(0, np.int64), np.zeros(0, np.int64)
    return (np.concatenate(covers), np.concatenate(stegos), np.concatenate(owners),
            np.concatenate(pair_of_frame))


def evaluate_cnn(pairs: Sequence[Pair], args: argparse.Namespace) -> dict:
    from .cnn import CnnConfig, frame_scores, train_cnn

    tile = min([args.tile] + [min(p.width, p.height) for p in pairs])
    tile -= tile % 16
    config = CnnConfig(tile=tile, max_tiles=args.max_tiles, epochs=args.epochs, seed=args.seed,
                       patience=args.patience)
    train_c, train_s, _, _ = _tiles(pairs, "train", args, tile)
    val_c, val_s, val_owners, _ = _tiles(pairs, "val", args, tile)
    test_c, test_s, test_owners, test_pairs = _tiles(pairs, "test", args, tile)
    selection = "val_p_e"
    if val_owners.size == 0:
        selection, val_c, val_s = "train_p_e (no val split)", train_c, train_s
        val_owners = np.arange(train_c.shape[0])
    model, history = train_cnn((train_c, train_s), (val_c, val_s, val_owners), config)
    report = _metrics(frame_scores(model, test_c, test_owners, config),
                      frame_scores(model, test_s, test_owners, config), test_pairs)
    best = min(history, key=lambda h: (h["val_p_e"], -h["val_auc"]))
    report.update({"tile": tile, "train_tiles": int(train_c.shape[0]), "device": config.device,
                   "selection": selection, "selected_epoch": best["epoch"], "selection_p_e": best["val_p_e"],
                   "epochs_run": len(history), "history": history})
    return report


def run(pairs: Sequence[Pair], args: argparse.Namespace) -> list[dict]:
    groups: dict[tuple[str, str], list[Pair]] = defaultdict(list)
    for pair in pairs:
        groups[pair.group].append(pair)
    reports = []
    for (method, rate), members in sorted(groups.items()):
        counts = _split_counts(members, {p.pair_id: len(p.frames) for p in members})
        base = {"method": method, "rate": rate, **counts}
        if not counts["n_train_pairs"] or not counts["n_test_pairs"]:
            reports.append({**base, "skipped": "group needs train and test pairs"})
            continue
        started = time.perf_counter()
        detail = evaluate_cnn(members, args) if args.detector == "cnn" else \
            evaluate_features(members, args.detector, args)
        reports.append({**base, **detail, "seconds": round(time.perf_counter() - started, 3)})
    return reports


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--detector", choices=DETECTORS, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--d-sub", type=lambda s: [int(v) for v in s.split(",")], default=list(DEFAULT_D_SUB))
    parser.add_argument("--learners", type=int, default=51)
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--tile", type=int, default=256)
    parser.add_argument("--max-tiles", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args(argv)


def _print_table(reports: Sequence[dict]) -> None:
    print(f"{'method':<14}{'rate':<12}{'pairs':>6}{'frames':>8}{'AUC':>8}{'P_E':>8}{'sAUC':>8}{'sP_E':>8}")
    for r in reports:
        if "skipped" in r:
            print(f"{r['method']:<14}{r['rate']:<12} skipped: {r['skipped']}")
            continue
        print(f"{r['method']:<14}{r['rate']:<12}{r['n_test_pairs']:>6}{r['n_test_frames']:>8}"
              f"{r['frame_auc']:>8.3f}{r['frame_p_e']:>8.3f}{r['stream_auc']:>8.3f}{r['stream_p_e']:>8.3f}")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    pairs = load_manifest(args.manifest)
    reports = run(pairs, args)
    out = args.out or args.cache_dir / "results" / f"{args.manifest.stem}_{args.detector}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    document = {"detector": args.detector, "manifest": str(args.manifest.resolve()),
                "settings": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
                "groups": reports}
    out.write_text(json.dumps(document, indent=2), encoding="utf-8")
    _print_table(reports)
    print(f"results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
