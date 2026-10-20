"""Sanity of the learned-steganalysis features and evaluation protocol.

A detector that cannot separate an obviously shifted feature would make every
"undetectable" result meaningless, so the protocol is checked on synthetic
data with known answers first.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("sklearn")

from benchmark import latticezk_ml_steganalysis as steg  # noqa: E402


def test_detection_error_extremes() -> None:
    labels = np.array([0] * 50 + [1] * 50)
    assert steg.detection_error(labels, labels.astype(float)) == 0.0
    rng = np.random.default_rng(1)
    assert 0.35 < steg.detection_error(labels, rng.normal(size=100)) <= 0.5


def test_coefficient_features_see_a_single_parity_flip() -> None:
    cover = [(0, 0, [9, 6, 1, 0] + [0] * 12), (396, 0, [3, 0] + [0] * 14)]
    stego = [(0, 0, [9, 5, 1, 0] + [0] * 12), (396, 0, [3, 0] + [0] * 14)]
    before = steg.coefficient_features(cover, 396, 2)
    after = steg.coefficient_features(stego, 396, 2)
    assert before.shape == (2, 16 * 16 + 16 + 36 + 2 * 16)
    assert not np.array_equal(before[0], after[0])
    assert np.array_equal(before[1], after[1])  # the other frame is untouched


def test_coefficient_features_see_a_trailing_one_sign_flip() -> None:
    cover = [(0, 0, [9, 3, 1, -1] + [0] * 12)]
    stego = [(0, 0, [9, 3, 1, 1] + [0] * 12)]
    assert not np.array_equal(
        steg.coefficient_features(cover, 396, 1), steg.coefficient_features(stego, 396, 1)
    )


def test_pixel_features_are_normalised_cooccurrences() -> None:
    frames = np.random.default_rng(2).integers(0, 255, size=(3, 32, 32))
    features = steg.pixel_features(frames)
    assert features.shape == (3, 4 * 125)
    assert np.allclose(features.reshape(3, 4, 125).sum(axis=2), 1.0)


def _synthetic(tmp_path, shift: float, clips: int = 2):
    rng = np.random.default_rng(3)
    paths = []
    for clip in range(clips):
        frames = 120
        base = rng.normal(size=(frames, 8))
        coeff = np.vstack([base, base + shift + rng.normal(scale=0.05, size=base.shape)])
        pixel = np.vstack([base[:, :4], base[:, :4]])
        path = tmp_path / f"clip{clip}.npz"
        np.savez(path, coeff=coeff, pixel=pixel, label=np.repeat([0, 1], frames),
                 pair=np.tile(np.arange(frames), 2), modified=np.ones(2 * frames, dtype=bool),
                 clip=np.array([f"clip{clip}"] * 2 * frames))
        paths.append(path)
    return paths


def test_protocol_detects_an_obvious_shift(tmp_path) -> None:
    report = steg.evaluate(_synthetic(tmp_path, shift=2.0))
    result = report["protocols"]["leave_one_clip_out"]["coefficient/logistic"]
    assert result["p_e_mean"] < 0.05
    pixel = report["protocols"]["leave_one_clip_out"]["pixel/logistic"]
    assert pixel["p_e_mean"] > 0.3  # pixel features were left identical


def test_protocol_reports_chance_without_a_signal(tmp_path) -> None:
    report = steg.evaluate(_synthetic(tmp_path, shift=0.0))
    for name, result in report["protocols"]["paired_half_split"].items():
        assert result["p_e_mean"] > 0.3, name
