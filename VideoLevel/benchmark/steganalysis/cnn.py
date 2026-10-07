"""Compact Xu-Net-style CNN steganalyser for decoded luma tiles (PyTorch).

Architecture (Xu, Wu, Shi 2016, reduced): fixed KV high-pass filter ->
conv5x5(8) -> ABS -> BN -> TanH -> avgpool -> conv5x5(16) -> BN -> TanH ->
avgpool -> 3 x [conv1x1 -> BN -> ReLU -> avgpool] (32, 64, 128) -> global
average pooling -> linear(2).

Training uses cover/stego tiles cut at identical positions; every mini-batch
holds both members of each pair and the same random flip / rotation. Model
selection: the epoch with the lowest validation P_E (frame scores are the
mean stego-minus-cover logit over a frame's tiles), early stopping after
``patience`` epochs without improvement. Seeds are fixed and cuDNN runs in
deterministic mode.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field

import numpy as np
import torch
from torch import nn

from .metrics import pe_threshold, roc_auc

KV_KERNEL = np.array([[-1, 2, -2, 2, -1], [2, -6, 8, -6, 2], [-2, 8, -12, 8, -2],
                      [2, -6, 8, -6, 2], [-1, 2, -2, 2, -1]], np.float32) / 12.0


@dataclass(frozen=True)
class CnnConfig:
    tile: int = 256
    max_tiles: int = 8
    batch_pairs: int = 16
    epochs: int = 60
    patience: int = 10
    learning_rate: float = 1e-3
    weight_decay: float = 5e-4
    seed: int = 0
    device: str = field(default_factory=lambda: "cuda" if torch.cuda.is_available() else "cpu")


class XuNet(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.hpf = nn.Conv2d(1, 1, 5, padding=2, bias=False)
        self.hpf.weight.data.copy_(torch.from_numpy(KV_KERNEL)[None, None])
        self.hpf.weight.requires_grad_(False)
        self.conv1 = nn.Conv2d(1, 8, 5, padding=2, bias=False)
        self.bn1 = nn.BatchNorm2d(8)
        self.conv2 = nn.Conv2d(8, 16, 5, padding=2, bias=False)
        self.bn2 = nn.BatchNorm2d(16)
        self.tail = nn.Sequential(*[layer for width_in, width_out in ((16, 32), (32, 64), (64, 128))
                                    for layer in (nn.Conv2d(width_in, width_out, 1, bias=False),
                                                  nn.BatchNorm2d(width_out), nn.ReLU(inplace=True),
                                                  nn.AvgPool2d(5, 2, 2))])
        self.pool = nn.AvgPool2d(5, 2, 2)
        self.fc = nn.Linear(128, 2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.hpf(x)
        x = self.pool(torch.tanh(self.bn1(torch.abs(self.conv1(x)))))
        x = self.pool(torch.tanh(self.bn2(self.conv2(x))))
        x = self.tail(x)
        return self.fc(x.mean(dim=(2, 3)))


def tile_positions(height: int, width: int, tile: int, max_tiles: int) -> list[tuple[int, int]]:
    """Fixed, evenly spread top-left corners of ``tile`` x ``tile`` crops (at most ``max_tiles``)."""
    if tile > min(height, width):
        raise ValueError(f"tile {tile} exceeds frame {width}x{height}")
    ys = np.linspace(0, height - tile, -(-height // tile)).round().astype(int)
    xs = np.linspace(0, width - tile, -(-width // tile)).round().astype(int)
    grid = [(int(y), int(x)) for y in ys for x in xs]
    if len(grid) > max_tiles:
        keep = np.linspace(0, len(grid) - 1, max_tiles).round().astype(int)
        grid = [grid[i] for i in keep]
    return grid


def cut_tiles(plane: np.ndarray, tile: int, max_tiles: int) -> np.ndarray:
    """(n_tiles, tile, tile) uint8 crops of one luma plane."""
    positions = tile_positions(plane.shape[0], plane.shape[1], tile, max_tiles)
    return np.stack([plane[y:y + tile, x:x + tile] for y, x in positions])


def seed_everything(seed: int) -> None:
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True, warn_only=True)


def _augment(batch: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Same random rotation/flip for the whole (pairs, 2, H, W) batch member."""
    out = np.empty_like(batch)
    for index in range(batch.shape[0]):
        member = np.rot90(batch[index], int(rng.integers(4)), axes=(1, 2))
        out[index] = member[:, :, ::-1] if rng.integers(2) else member
    return out


def _to_tensor(tiles: np.ndarray, device: str) -> torch.Tensor:
    return torch.from_numpy(np.ascontiguousarray(tiles, dtype=np.float32)).unsqueeze(1).to(device)


@torch.no_grad()
def tile_scores(model: XuNet, tiles: np.ndarray, config: CnnConfig) -> np.ndarray:
    """Stego-minus-cover logit of each tile."""
    model.eval()
    scores = []
    for start in range(0, tiles.shape[0], 2 * config.batch_pairs):
        logits = model(_to_tensor(tiles[start:start + 2 * config.batch_pairs], config.device))
        scores.append((logits[:, 1] - logits[:, 0]).float().cpu().numpy())
    return np.concatenate(scores) if scores else np.zeros(0, np.float32)


def frame_scores(model: XuNet, tiles: np.ndarray, owners: np.ndarray, config: CnnConfig) -> np.ndarray:
    """Mean tile score per frame; ``owners`` maps tiles to frame rows 0..n-1."""
    per_tile = tile_scores(model, tiles, config)
    counts = np.bincount(owners)
    return np.bincount(owners, weights=per_tile, minlength=counts.size) / np.maximum(counts, 1)


def _validation(model: XuNet, cover: np.ndarray, stego: np.ndarray, owners: np.ndarray,
                config: CnnConfig) -> tuple[float, float]:
    scores = np.r_[frame_scores(model, cover, owners, config), frame_scores(model, stego, owners, config)]
    labels = np.r_[np.zeros(owners.max() + 1), np.ones(owners.max() + 1)]
    return pe_threshold(scores, labels)[0], roc_auc(scores, labels)


def train_cnn(train: tuple[np.ndarray, np.ndarray], val: tuple[np.ndarray, np.ndarray, np.ndarray],
              config: CnnConfig) -> tuple[XuNet, list[dict[str, float]]]:
    """Train on paired tiles ``train = (cover, stego)``; ``val = (cover, stego, owners)``.

    Returns the checkpoint with the lowest validation P_E and the epoch history.
    """
    cover, stego = train
    if cover.shape != stego.shape or cover.ndim != 3 or cover.shape[0] == 0:
        raise ValueError("paired (n, tile, tile) cover/stego tiles are required")
    seed_everything(config.seed)
    rng = np.random.default_rng(config.seed)
    model = XuNet().to(config.device)
    trainable = [p for p in model.parameters() if p.requires_grad]
    optimiser = torch.optim.Adam(trainable, lr=config.learning_rate, weight_decay=config.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=config.epochs)
    loss_fn = nn.CrossEntropyLoss()
    pairs = np.stack([cover, stego], axis=1)
    labels = torch.tensor([0, 1] * config.batch_pairs, device=config.device)
    best_state, best_key, stale, history = copy.deepcopy(model.state_dict()), (2.0, 0.0), 0, []
    for epoch in range(config.epochs):
        model.train()
        order = rng.permutation(pairs.shape[0])
        losses = []
        for start in range(0, order.size, config.batch_pairs):
            batch = _augment(pairs[order[start:start + config.batch_pairs]], rng)
            inputs = _to_tensor(batch.reshape(-1, *batch.shape[2:]), config.device)
            if inputs.shape[0] < 4:
                continue
            optimiser.zero_grad(set_to_none=True)
            loss = loss_fn(model(inputs), labels[:inputs.shape[0]])
            loss.backward()
            optimiser.step()
            losses.append(float(loss.detach()))
        scheduler.step()
        val_pe, val_auc = _validation(model, *val, config)
        history.append({"epoch": epoch, "loss": float(np.mean(losses)) if losses else float("nan"),
                        "val_p_e": val_pe, "val_auc": val_auc})
        if (val_pe, -val_auc) < best_key:
            best_key, stale = (val_pe, -val_auc), 0
            best_state = copy.deepcopy(model.state_dict())
        else:
            stale += 1
            if stale >= config.patience:
                break
    model.load_state_dict(best_state)
    return model, history
