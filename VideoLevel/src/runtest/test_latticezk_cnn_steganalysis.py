"""Sanity of the CNN steganalysis pipeline on tiny synthetic data (CPU).

A CNN that cannot learn an obvious injected +-1 pattern would make a
near-chance result on the real stego videos meaningless, so the training loop,
the paired batching and the metrics are checked on data with a known answer.
"""

from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("sklearn")

from benchmark import latticezk_cnn_steganalysis as cnn  # noqa: E402


def _smooth_pairs(count: int, size: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Smooth random covers; stego adds a dense random +-1 pattern."""
    rng = np.random.default_rng(seed)
    coarse = rng.uniform(40, 210, size=(count, size // 16 + 1, size // 16 + 1))
    covers = np.stack([np.kron(image, np.ones((16, 16)))[:size, :size] for image in coarse])
    covers = np.clip(np.rint(covers), 1, 254).astype(np.uint8)
    pattern = rng.choice([-1, 1], size=covers.shape)
    stegos = (covers.astype(np.int16) + pattern).astype(np.uint8)
    return covers, stegos


def test_srm_bank_is_thirty_zero_mean_high_pass_filters() -> None:
    kernels, scales = cnn.srm_kernels()
    assert kernels.shape == (30, 5, 5)
    assert scales.shape == (30,)
    assert np.allclose(kernels.reshape(30, -1).sum(axis=1), 0.0)
    assert len({kernel.tobytes() for kernel in kernels}) == 30


def test_crop_offsets_are_grid_aligned_and_cover_the_frame() -> None:
    for length, crop in ((288, 256), (352, 256), (64, 48), (64, 64)):
        offsets = cnn.crop_offsets(length, crop)
        assert all(offset % cnn.GRID == 0 for offset in offsets)
        assert offsets[0] == 0 and offsets[-1] + crop >= length - cnn.GRID + 1


def test_amplified_change_is_integer_and_clipped() -> None:
    cover = torch.tensor([[10, 250, 0]], dtype=torch.uint8)
    stego = torch.tensor([[11, 252, 0]], dtype=torch.uint8)
    amplified = cnn.amplify_change(cover, stego, 2.5)
    assert amplified.tolist() == [[12.0, 255.0, 0.0]]
    assert cnn.amplify_change(cover, stego, 1.0) is stego


def test_metrics_extremes() -> None:
    labels = np.array([0] * 20 + [1] * 20)
    perfect = cnn.metrics(labels, labels * 2.0 - 1.0)
    assert perfect == {"p_e": 0.0, "auc": 1.0, "p_e_at_0": 0.0}
    assert cnn.threshold_error(labels, np.full(40, 5.0)) == 0.5


def test_protocol_folds_keep_pairs_and_hold_out_clips() -> None:
    clips = np.array(["a"] * 10 + ["b"] * 10 + ["c"] * 6)
    folds = cnn.protocol_folds("loco", clips, seed=1, validation_fraction=0.2)
    assert [fold["name"] for fold in folds] == ["a", "b", "c"]
    for fold in folds:
        assert set(clips[fold["test"]]) == {fold["name"]}
        assert fold["name"] not in set(clips[fold["train"]]) | set(clips[fold["val"]])
        assert not set(fold["train"]) & set(fold["val"])
    paired = cnn.protocol_folds("paired", clips, seed=1, validation_fraction=0.2)[0]
    together = np.concatenate([paired["train"], paired["val"], paired["test"]])
    assert sorted(together.tolist()) == list(range(len(clips)))


def test_paired_batch_applies_the_same_crop_to_cover_and_stego() -> None:
    covers, stegos = _smooth_pairs(4, 64, seed=5)
    cover, stego = torch.from_numpy(covers), torch.from_numpy(stegos)
    images, labels = cnn._paired_batch(cover, stego, np.arange(4), 32, np.random.default_rng(0))
    assert images.shape == (8, 1, 32, 32)
    assert labels.tolist() == [0.0] * 4 + [1.0] * 4
    difference = images[4:].int() - images[:4].int()
    assert set(torch.unique(difference).tolist()) <= {-1, 1}


def test_training_learns_an_obvious_injected_pattern_on_cpu() -> None:
    covers, stegos = _smooth_pairs(16, 64, seed=7)
    cover, stego = torch.from_numpy(covers), torch.from_numpy(stegos)
    clips = np.array(["a"] * 8 + ["b"] * 8)
    config = cnn.TrainConfig(crop=48, batch_pairs=4, max_epochs=7, steps_per_epoch=8,
                             learning_rate=3e-3, patience=7, amp=False, seed=3,
                             curriculum_start=3.0, curriculum_epochs=2)
    fold = cnn.protocol_folds("loco", clips, seed=3, validation_fraction=0.25)[0]
    model, training = cnn.train_model(cover, stego, fold["train"], fold["val"], config)
    assert training["epochs_run"] >= 3
    assert config.curriculum_epochs <= training["best_epoch"] < training["epochs_run"]
    assert [entry["alpha"] for entry in training["history"][:3]] == [3.0, 2.0, 1.0]
    assert all(np.isfinite(entry["train_loss"]) for entry in training["history"])
    result = cnn._evaluate_pairs(model, cover, stego, fold["test"], config.crop)
    scores = cnn.metrics(result["labels"], result["scores"])
    assert scores["p_e"] <= 0.15, scores
    assert scores["auc"] >= 0.9, scores
