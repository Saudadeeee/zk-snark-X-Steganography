"""Deep-learning (CNN) steganalysis of lattice-ZK stego video, frame by frame.

Complements the feature-based detectors in ``latticezk_ml_steganalysis`` with a
spatial-domain convolutional detector trained on the GPU:

* **data** -- for each case the cover and stego streams are decoded to exact
  luma planes (``decode_luma_native``); only frames whose luma differs are
  kept, and every cover frame stays paired with its stego frame;
* **model** -- a Yedroudj-Net-style network: a fixed bank of the 30 SRM
  high-pass filters (computed exactly in fp32 with integer taps), truncation,
  two 5x5 layers with ABS/BN/TLU, three pooled 3x3 stages and global average
  pooling, ending in one logit;
* **training** -- random 4-aligned crops (the H.264 4x4 transform grid keeps
  its phase), the same crop and D4 transform (flips/rot90) on the cover and
  its stego in every mini-batch, AdamW, a payload curriculum (the change is
  amplified 6x and decayed to the real 1x over the first epochs -- from scratch
  at 1x the loss never leaves ln 2), early stopping on a validation split
  carved from the training clips only;
* **scoring** -- per-frame score = mean logit over a fixed grid of crops
  covering the full frame (the full-frame logit is reported too); per-video
  score = mean frame score over a video's modified frames.  Metrics are
  ``P_E = min (P_FA + P_MD) / 2`` and AUC.

Protocols: leave-one-clip-out (``loco``) and a per-clip paired half split
(``paired``).  The attacker is strong: it trains on exact cover/stego pairs
from the same encoder settings and knows which frames carry bits.

    python -m benchmark.latticezk_cnn_steganalysis dataset --set magnitude
    python -m benchmark.latticezk_cnn_steganalysis train --set magnitude --protocol loco \\
        --output benchmark/results/q2/cnn_magnitude_loco.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RANDOM_SEED = 20261021
GRID = 4  # H.264 luma transform block size; crops keep this phase
AMPLIFIED_PROBES = (2.0, 4.0)  # the alpha=1 model is also scored on amplified test changes
CASE_SETS: dict[str, tuple[str, ...]] = {
    "magnitude": ("container_cif_q22_reg", "coastguard_cif_q22_reg", "city_cif_q22_reg",
                  "hall_cif_q22_reg", "deadline_cif_q22_reg"),
    "t1_spread": ("container_cif_q22_reg_t1_spread", "coastguard_cif_q22_reg_t1_spread",
                  "city_cif_q22_reg_t1_spread", "hall_cif_q22_reg_t1_spread"),
}


@dataclass(frozen=True)
class TrainConfig:
    crop: int = 256
    batch_pairs: int = 16
    max_epochs: int = 40
    steps_per_epoch: int | None = None  # default: one crop per training pair per epoch
    learning_rate: float = 2e-4
    weight_decay: float = 1e-4
    patience: int = 10
    validation_fraction: float = 0.2
    seed: int = RANDOM_SEED
    amp: bool = True
    # Payload curriculum: train first on cover + alpha * (stego - cover), alpha decaying
    # linearly from ``curriculum_start`` to ``amplify`` over ``curriculum_epochs`` epochs.
    curriculum_start: float = 6.0
    curriculum_epochs: int = 15
    # Target amplification for the final epochs, validation and test.  1.0 = the real
    # stego; > 1 is the "detectability margin" experiment (a deliberately stronger change).
    amplify: float = 1.0


# -- metrics -------------------------------------------------------------- #

def detection_error(labels: np.ndarray, scores: np.ndarray) -> float:
    """Minimum over thresholds of (P_FA + P_MD) / 2 (same definition as the FLD study)."""
    from benchmark.latticezk_ml_steganalysis import detection_error as fld_detection_error

    return fld_detection_error(labels, scores)


def threshold_error(labels: np.ndarray, scores: np.ndarray, threshold: float = 0.0) -> float:
    """(P_FA + P_MD) / 2 at a fixed threshold (logit 0 = the trained decision rule)."""
    labels = np.asarray(labels).astype(bool)
    decided = np.asarray(scores) > threshold
    false_alarm = float(decided[~labels].mean()) if (~labels).any() else 0.0
    missed = float((~decided[labels]).mean()) if labels.any() else 0.0
    return (false_alarm + missed) / 2


def metrics(labels: np.ndarray, scores: np.ndarray) -> dict[str, float]:
    from sklearn.metrics import roc_auc_score

    labels = np.asarray(labels)
    scores = np.asarray(scores, dtype=np.float64)
    if len(np.unique(labels)) < 2:
        return {"p_e": float("nan"), "auc": float("nan"), "p_e_at_0": float("nan")}
    return {"p_e": round(detection_error(labels, scores), 4),
            "auc": round(float(roc_auc_score(labels, scores)), 4),
            "p_e_at_0": round(threshold_error(labels, scores), 4)}


# -- dataset -------------------------------------------------------------- #

def case_clip(case: str) -> str:
    return case.split("_cif")[0]


def build_case(case: str, encoded_dir: Path, stego_dir: Path, reports_dir: Path,
               cache_dir: Path) -> Path:
    """Decode cover/stego luma once and cache the modified frame pairs as uint8."""
    from benchmark.latticezk_ml_steganalysis import decode_luma_native

    output = cache_dir / f"cnn_pairs_{case}.npz"
    if output.exists():
        return output
    report = json.loads((reports_dir / f"e2e_{case}.json").read_text(encoding="utf-8"))
    cover_path = encoded_dir / report["input_video"]
    stego_path = stego_dir / f"{case}.h264"
    cover = decode_luma_native(cover_path.resolve(strict=True))
    stego = decode_luma_native(stego_path.resolve(strict=True))
    frames = min(len(cover), len(stego))
    changed = np.flatnonzero(np.any(cover[:frames] != stego[:frames], axis=(1, 2)))
    expected = int(report.get("frame_quality", {}).get("frames_modified", -1))
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.savez(output,
             cover=np.ascontiguousarray(cover[changed]), stego=np.ascontiguousarray(stego[changed]),
             frame=changed.astype(np.int32),
             segment=(changed // int(report.get("frames_per_segment", 100))).astype(np.int32),
             expected_modified=np.int32(expected), total_frames=np.int32(frames))
    del cover, stego
    sys.stdout.write(json.dumps({"case": case, "frames": frames, "modified": int(len(changed)),
                                 "report_frames_modified": expected}) + "\n")
    return output


def load_set(paths: list[Path]) -> dict[str, np.ndarray]:
    parts: dict[str, list] = {key: [] for key in ("cover", "stego", "frame", "segment", "clip")}
    for path in paths:
        with np.load(path) as data:
            for key in ("cover", "stego", "frame", "segment"):
                parts[key].append(data[key])
            parts["clip"].append(np.array([case_clip(path.stem.removeprefix("cnn_pairs_"))]
                                          * len(data["frame"])))
    return {key: np.concatenate(value) for key, value in parts.items()}


# -- model ---------------------------------------------------------------- #

def srm_kernels() -> tuple[np.ndarray, np.ndarray]:
    """The 30 SRM high-pass filters as integer 5x5 taps plus their divisors."""
    kernels: list[np.ndarray] = []
    scales: list[float] = []

    def put(taps: dict[tuple[int, int], int], scale: float) -> None:
        kernel = np.zeros((5, 5))
        for (row, col), value in taps.items():
            kernel[2 + row, 2 + col] = value
        kernels.append(kernel)
        scales.append(scale)

    directions = [(0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1)]
    for dy, dx in directions:  # 1st order
        put({(0, 0): -1, (dy, dx): 1}, 1.0)
    for dy, dx in directions[:4]:  # 2nd order
        put({(-dy, -dx): 1, (0, 0): -2, (dy, dx): 1}, 2.0)
    for dy, dx in directions:  # 3rd order
        put({(-dy, -dx): 1, (0, 0): -3, (dy, dx): 3, (2 * dy, 2 * dx): -1}, 3.0)
    square3 = np.array([[-1, 2, -1], [2, -4, 2], [-1, 2, -1]])
    edge3 = square3.copy()
    edge3[2] = 0
    square5 = np.array([[-1, 2, -2, 2, -1], [2, -6, 8, -6, 2], [-2, 8, -12, 8, -2],
                        [2, -6, 8, -6, 2], [-1, 2, -2, 2, -1]])
    edge5 = square5.copy()
    edge5[3:] = 0
    kernels.append(np.pad(square3, 1))
    scales.append(4.0)
    for turn in range(4):
        kernels.append(np.rot90(np.pad(edge3, 1), turn))
        scales.append(4.0)
    kernels.append(square5)
    scales.append(12.0)
    for turn in range(4):
        kernels.append(np.rot90(edge5, turn))
        scales.append(12.0)
    return np.stack(kernels).astype(np.float32), np.array(scales, dtype=np.float32)


def _torch():
    import torch
    from torch import nn

    return torch, nn


def build_model():
    """Yedroudj-Net-style detector with a fixed SRM front end; returns an nn.Module."""
    torch, nn = _torch()

    class HighPass(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            kernels, scales = srm_kernels()
            self.register_buffer("weight", torch.from_numpy(kernels)[:, None])
            self.register_buffer("scale", torch.from_numpy(scales)[None, :, None, None])

        def forward(self, images):
            # Integer taps on integer pixels are exact in fp32; disable autocast/TF32 effects.
            with torch.autocast(device_type=images.device.type, enabled=False):
                centred = images.float() - 128.0
                residual = torch.nn.functional.conv2d(centred, self.weight, padding=2)
                return residual / self.scale

    class TLU(nn.Module):
        def __init__(self, threshold: float) -> None:
            super().__init__()
            self.threshold = threshold

        def forward(self, values):
            return torch.clamp(values, -self.threshold, self.threshold)

    class Absolute(nn.Module):
        def forward(self, values):
            return values.abs()

    def stage(inputs: int, outputs: int) -> list:
        return [nn.Conv2d(inputs, outputs, 3, padding=1, bias=False), nn.BatchNorm2d(outputs),
                nn.ReLU(inplace=True), nn.AvgPool2d(5, stride=2, padding=2)]

    model = nn.Sequential(
        HighPass(), TLU(3.0),
        nn.Conv2d(30, 30, 5, padding=2, bias=False), Absolute(), nn.BatchNorm2d(30), TLU(3.0),
        nn.Conv2d(30, 30, 5, padding=2, bias=False), nn.BatchNorm2d(30), TLU(2.0),
        nn.AvgPool2d(5, stride=2, padding=2),
        *stage(30, 32), *stage(32, 64),
        nn.Conv2d(64, 128, 3, padding=1, bias=False), nn.BatchNorm2d(128), nn.ReLU(inplace=True),
        nn.AdaptiveAvgPool2d(1), nn.Flatten(),
        nn.Linear(128, 128), nn.ReLU(inplace=True), nn.Dropout(0.3), nn.Linear(128, 1),
    )
    return model


# -- training ------------------------------------------------------------- #

def crop_offsets(length: int, crop: int) -> list[int]:
    """Grid-aligned offsets covering a frame dimension with ``crop``-sized windows."""
    if crop >= length:
        return [0]
    last = (length - crop) // GRID * GRID
    return sorted({0, (last // 2) // GRID * GRID, last})


def _d4(images, transform: int):
    torch, _ = _torch()
    if transform & 4:
        images = torch.flip(images, dims=(-1,))
    return torch.rot90(images, k=transform & 3, dims=(-2, -1))


def curriculum_alpha(config: TrainConfig, epoch: int) -> float:
    target = config.amplify
    if config.curriculum_epochs <= 0 or epoch >= config.curriculum_epochs:
        return target
    start = max(config.curriculum_start, target)
    return start + (target - start) * epoch / config.curriculum_epochs


def amplify_change(cover, stego, alpha: float):
    """cover + alpha * (stego - cover), rounded and clipped to valid 8-bit pixels.

    Rounding matters: fractional pixel values would be a trivial shortcut.
    """
    torch, _ = _torch()
    if alpha == 1.0:
        return stego
    base = cover.float()
    return torch.clamp(torch.round(base + alpha * (stego.float() - base)), 0, 255)


def _paired_batch(cover, stego, indices: np.ndarray, crop: int, rng: np.random.Generator,
                  alpha: float = 1.0):
    """Same crop and D4 transform for each cover and its stego; returns (images, labels).

    ``alpha != 1`` amplifies the embedding change (curriculum / margin experiment).
    """
    torch, _ = _torch()
    height, width = cover.shape[-2:]
    rows = rng.integers(0, (height - crop) // GRID + 1, size=len(indices)) * GRID
    cols = rng.integers(0, (width - crop) // GRID + 1, size=len(indices)) * GRID
    transforms = rng.integers(0, 8, size=len(indices))
    covers, stegos = [], []
    for index, row, col, transform in zip(indices, rows, cols, transforms):
        window = (slice(row, row + crop), slice(col, col + crop))
        covers.append(_d4(cover[index][window], int(transform)))
        stegos.append(_d4(stego[index][window], int(transform)))
    base = torch.stack(covers)
    images = torch.cat([base.float(), amplify_change(base, torch.stack(stegos), alpha).float()])
    images = images[:, None]
    labels = torch.cat([torch.zeros(len(indices)), torch.ones(len(indices))]).to(images.device)
    return images, labels


def score_frames(model, frames, crop: int, batch: int = 32,
                 crops: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Per-frame (mean logit over a covering crop grid, full-frame logit).

    With ``crops=False`` only the (cheaper) full-frame logit is computed and returned twice.
    """
    torch, _ = _torch()
    height, width = frames.shape[-2:]
    windows = [(row, col) for row in crop_offsets(height, crop) for col in crop_offsets(width, crop)]
    crop_scores, full_scores = [], []
    model.eval()
    with torch.no_grad(), torch.autocast(device_type=frames.device.type,
                                         enabled=frames.device.type == "cuda"):
        for start in range(0, len(frames), batch):
            chunk = frames[start:start + batch][:, None]
            full = model(chunk).float().squeeze(1).cpu().numpy()
            full_scores.append(full)
            if not crops:
                crop_scores.append(full)
                continue
            logits = [model(chunk[..., r:r + crop, c:c + crop]).float().squeeze(1)
                      for r, c in windows]
            crop_scores.append(torch.stack(logits).mean(0).cpu().numpy())
    return np.concatenate(crop_scores), np.concatenate(full_scores)


def _evaluate_pairs(model, cover, stego, indices: np.ndarray, crop: int,
                   crops: bool = True, alpha: float = 1.0) -> dict[str, Any]:
    torch, _ = _torch()
    index = torch.as_tensor(indices, device=cover.device, dtype=torch.long)
    covers = cover[index]
    stegos = amplify_change(covers, stego[index], alpha)
    cover_crop, cover_full = score_frames(model, covers, crop, crops=crops)
    stego_crop, stego_full = score_frames(model, stegos, crop, crops=crops)
    labels = np.repeat([0, 1], len(indices))
    return {"labels": labels,
            "scores": np.concatenate([cover_crop, stego_crop]),
            "full_scores": np.concatenate([cover_full, stego_full])}


def train_model(cover, stego, train_idx: np.ndarray, val_idx: np.ndarray,
                config: TrainConfig) -> tuple[Any, dict[str, Any]]:
    """Train on paired crops; keep the epoch with the lowest validation P_E (then loss)."""
    torch, nn = _torch()
    device = cover.device
    torch.manual_seed(config.seed)
    rng = np.random.default_rng(config.seed)
    model = build_model().to(device)
    optimiser = torch.optim.AdamW(model.parameters(), lr=config.learning_rate,
                                  weight_decay=config.weight_decay)
    steps = config.steps_per_epoch or max(1, len(train_idx) // config.batch_pairs)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=config.max_epochs * steps)
    use_amp = config.amp and device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    loss_fn = nn.BCEWithLogitsLoss()
    best: dict[str, Any] = {"key": (1.0, float("inf")), "epoch": -1, "state": None}
    history = []
    stale = 0
    for epoch in range(config.max_epochs):
        model.train()
        order = rng.permutation(np.resize(rng.permutation(train_idx), steps * config.batch_pairs))
        losses = []
        for step in range(steps):
            batch = order[step * config.batch_pairs:(step + 1) * config.batch_pairs]
            images, labels = _paired_batch(cover, stego, batch, config.crop, rng,
                                           curriculum_alpha(config, epoch))
            with torch.autocast(device_type=device.type, enabled=use_amp):
                loss = loss_fn(model(images).float().squeeze(1), labels)
            optimiser.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.step(optimiser)
            scaler.update()
            scheduler.step()
            losses.append(float(loss.detach()))
        val = _evaluate_pairs(model, cover, stego, val_idx, config.crop, crops=False,
                              alpha=config.amplify)
        val_metrics = metrics(val["labels"], val["scores"])
        logits = torch.as_tensor(val["scores"])
        val_loss = float(loss_fn(logits, torch.as_tensor(val["labels"], dtype=torch.float32)))
        history.append({"epoch": epoch, "train_loss": round(float(np.mean(losses)), 4),
                        "val_loss": round(val_loss, 4), "val_p_e": val_metrics["p_e"],
                        "val_auc": val_metrics["auc"]})
        history[-1]["alpha"] = round(curriculum_alpha(config, epoch), 3)
        key = (val_metrics["p_e"], val_loss)
        if epoch < config.curriculum_epochs:
            continue  # amplified-signal epochs are never selected
        if key < best["key"]:
            best = {"key": key, "epoch": epoch,
                    "state": {k: v.detach().clone() for k, v in model.state_dict().items()}}
            stale = 0
        else:
            stale += 1
            if stale >= config.patience:
                break
    if best["state"] is not None:  # otherwise (curriculum only) keep the final weights
        model.load_state_dict(best["state"])
    return model, {"best_epoch": best["epoch"], "epochs_run": len(history),
                   "best_val_p_e": best["key"][0], "history": history}


# -- protocols ------------------------------------------------------------ #

def _split_validation(indices: np.ndarray, clips: np.ndarray, fraction: float,
                      contiguous: bool, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Validation from training clips only: each clip's last frames (or a random subset)."""
    train, val = [], []
    for clip in np.unique(clips[indices]):
        members = indices[clips[indices] == clip]
        count = max(1, int(round(len(members) * fraction)))
        if contiguous:
            train.append(members[:-count])
            val.append(members[-count:])
        else:
            chosen = rng.permutation(members)
            val.append(chosen[:count])
            train.append(chosen[count:])
    return np.sort(np.concatenate(train)), np.sort(np.concatenate(val))


def protocol_folds(protocol: str, clips: np.ndarray, seed: int,
                   validation_fraction: float) -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed)
    everything = np.arange(len(clips))
    folds = []
    if protocol == "loco":
        for clip in sorted(np.unique(clips)):
            train, val = _split_validation(everything[clips != clip], clips, validation_fraction,
                                           contiguous=True, rng=rng)
            folds.append({"name": str(clip), "train": train, "val": val,
                          "test": everything[clips == clip]})
    elif protocol == "paired":
        train_all, test = [], []
        for clip in sorted(np.unique(clips)):
            members = rng.permutation(everything[clips == clip])
            half = len(members) // 2
            test.append(members[:half])
            train_all.append(members[half:])
        train, val = _split_validation(np.sort(np.concatenate(train_all)), clips,
                                       validation_fraction, contiguous=False, rng=rng)
        folds.append({"name": "paired_half_split", "train": train, "val": val,
                      "test": np.sort(np.concatenate(test))})
    else:
        raise ValueError(f"unknown protocol {protocol!r}")
    return folds


def _video_units(frame_scores: np.ndarray, labels: np.ndarray,
                 groups: np.ndarray) -> list[dict[str, Any]]:
    """Average frame scores per (group, cover|stego) video unit."""
    units = []
    for group in np.unique(groups):
        for label in (0, 1):
            mask = (groups == group) & (labels == label)
            units.append({"unit": str(group), "label": label,
                          "frames": int(mask.sum()), "score": float(frame_scores[mask].mean())})
    return units


def run_protocol(data: dict[str, np.ndarray], protocol: str, config: TrainConfig,
                 device: str) -> dict[str, Any]:
    torch, _ = _torch()
    cover = torch.from_numpy(data["cover"]).to(device)
    stego = torch.from_numpy(data["stego"]).to(device)
    clips = data["clip"]
    folds = protocol_folds(protocol, clips, config.seed, config.validation_fraction)
    report: dict[str, Any] = {"protocol": protocol, "config": asdict(config), "device": device,
                              "frame_pairs": int(len(clips)), "clips": sorted(set(clips.tolist())),
                              "folds": []}
    pooled_clip_units, pooled_segment_units = [], []
    started = time.perf_counter()
    for number, fold in enumerate(folds):
        fold_started = time.perf_counter()
        fold_config = replace(config, seed=config.seed + number)
        model, training = train_model(cover, stego, fold["train"], fold["val"], fold_config)
        test = _evaluate_pairs(model, cover, stego, fold["test"], config.crop, alpha=config.amplify)
        amplified = {}
        for alpha in (AMPLIFIED_PROBES if config.amplify == 1.0 else ()):
            probe = _evaluate_pairs(model, cover, stego, fold["test"], config.crop, crops=False,
                                    alpha=alpha)
            amplified[str(alpha)] = metrics(probe["labels"], probe["full_scores"])
        test_clips = np.concatenate([clips[fold["test"]]] * 2)
        test_segments = np.array([f"{c}/seg{s}" for c, s in
                                  zip(test_clips, np.concatenate([data["segment"][fold["test"]]] * 2))])
        clip_units = _video_units(test["scores"], test["labels"], test_clips)
        segment_units = _video_units(test["scores"], test["labels"], test_segments)
        pooled_clip_units += clip_units
        pooled_segment_units += segment_units
        per_clip = {clip: metrics(test["labels"][test_clips == clip], test["scores"][test_clips == clip])
                    for clip in np.unique(test_clips)}
        report["folds"].append({
            "name": fold["name"],
            "pairs": {"train": int(len(fold["train"])), "val": int(len(fold["val"])),
                      "test": int(len(fold["test"]))},
            "training": {k: v for k, v in training.items() if k != "history"},
            "history": training["history"],
            "frame": metrics(test["labels"], test["scores"]),
            "frame_full_logit": metrics(test["labels"], test["full_scores"]),
            "frame_per_clip": per_clip if protocol == "paired" else None,
            "frame_full_logit_on_amplified_test": amplified,
            "video_clip_units": clip_units,
            "video_clip_pairs_correct": _pair_correct(clip_units),
            "video_segment": metrics([u["label"] for u in segment_units],
                                     [u["score"] for u in segment_units]),
            "seconds": round(time.perf_counter() - fold_started, 1),
        })
        sys.stdout.write(json.dumps({"fold": fold["name"], **report["folds"][-1]["frame"],
                                     "epochs": training["epochs_run"],
                                     "seconds": report["folds"][-1]["seconds"]}) + "\n")
        sys.stdout.flush()
        del model
        if device == "cuda":
            torch.cuda.empty_cache()
    frames = [fold["frame"] for fold in report["folds"]]
    report["summary"] = {
        "frame_p_e_mean": round(float(np.mean([f["p_e"] for f in frames])), 4),
        "frame_auc_mean": round(float(np.mean([f["auc"] for f in frames])), 4),
        "frame_full_logit_p_e_mean": round(float(np.mean(
            [fold["frame_full_logit"]["p_e"] for fold in report["folds"]])), 4),
        "video_clip_pooled": metrics([u["label"] for u in pooled_clip_units],
                                     [u["score"] for u in pooled_clip_units]),
        "video_clip_pairs_correct": _pair_correct(pooled_clip_units),
        "video_segment_pooled": metrics([u["label"] for u in pooled_segment_units],
                                        [u["score"] for u in pooled_segment_units]),
        "video_segment_units": len(pooled_segment_units),
        "seconds": round(time.perf_counter() - started, 1),
    }
    return report


def _pair_correct(units: list[dict[str, Any]]) -> str:
    """How many cover/stego video pairs the stego video scores higher than its cover."""
    by_unit: dict[str, dict[int, float]] = {}
    for unit in units:
        by_unit.setdefault(unit["unit"], {})[unit["label"]] = unit["score"]
    correct = sum(1 for scores in by_unit.values() if scores.get(1, 0) > scores.get(0, 0))
    return f"{correct}/{len(by_unit)}"


# -- CLI ------------------------------------------------------------------ #

def _paths(arguments) -> tuple[Path, Path, Path, Path]:
    return (arguments.encoded_dir, arguments.stego_dir, arguments.reports_dir, arguments.cache_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--encoded-dir", type=Path, default=ROOT / "data" / "encoded")
    parser.add_argument("--stego-dir", type=Path, default=ROOT / "tmp" / "q2")
    parser.add_argument("--reports-dir", type=Path, default=ROOT / "benchmark" / "results" / "q2")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "tmp" / "cnn_cache")
    commands = parser.add_subparsers(dest="command", required=True)
    dataset = commands.add_parser("dataset")
    dataset.add_argument("--set", choices=sorted(CASE_SETS), required=True)
    train = commands.add_parser("train")
    train.add_argument("--set", choices=sorted(CASE_SETS), required=True)
    train.add_argument("--protocol", choices=("loco", "paired"), required=True)
    train.add_argument("--output", type=Path, required=True)
    train.add_argument("--max-epochs", type=int, default=TrainConfig.max_epochs)
    train.add_argument("--patience", type=int, default=TrainConfig.patience)
    train.add_argument("--batch-pairs", type=int, default=TrainConfig.batch_pairs)
    train.add_argument("--learning-rate", type=float, default=TrainConfig.learning_rate)
    train.add_argument("--curriculum-start", type=float, default=TrainConfig.curriculum_start)
    train.add_argument("--curriculum-epochs", type=int, default=TrainConfig.curriculum_epochs)
    train.add_argument("--amplify", type=float, default=1.0,
                       help="margin experiment: train/validate/test on cover + a*(stego-cover)")
    train.add_argument("--seed", type=int, default=RANDOM_SEED)
    train.add_argument("--device", default=None)
    arguments = parser.parse_args()
    encoded, stego, reports, cache = _paths(arguments)
    paths = [build_case(case, encoded, stego, reports, cache) for case in CASE_SETS[arguments.set]]
    if arguments.command == "dataset":
        return 0
    torch, _ = _torch()
    device = arguments.device or ("cuda" if torch.cuda.is_available() else "cpu")
    if device == "cuda":
        torch.backends.cudnn.benchmark = True
    config = TrainConfig(max_epochs=arguments.max_epochs, patience=arguments.patience,
                         batch_pairs=arguments.batch_pairs, learning_rate=arguments.learning_rate,
                         curriculum_start=arguments.curriculum_start,
                         curriculum_epochs=arguments.curriculum_epochs, amplify=arguments.amplify,
                         seed=arguments.seed)
    report = run_protocol(load_set(paths), arguments.protocol, config, device)
    report.update({"case_set": arguments.set, "cases": list(CASE_SETS[arguments.set]),
                   "torch": torch.__version__,
                   "gpu": torch.cuda.get_device_name(0) if device == "cuda" else None})
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps({"output": str(arguments.output), **report["summary"]}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
