"""QIM carriers and the content fingerprint of the robust mode."""

from __future__ import annotations

import numpy as np
import pytest

from src.robust import features, watermark

KEY = b"w" * 32


def _clip(frames: int = 6, height: int = 96, width: int = 128) -> np.ndarray:
    rng = np.random.default_rng(5)
    y, x = np.mgrid[0:height, 0:width]
    base = 110 + 60 * np.sin(x / 9.0) * np.cos(y / 13.0)
    clip = base[None] + rng.normal(0, 6, (frames, height, width))
    return np.clip(np.round(clip), 0, 255).astype(np.uint8)


def _chroma(frames: int, height: int, width: int) -> tuple[np.ndarray, np.ndarray]:
    """Smooth 4:2:0 companion planes for ``_clip`` geometry."""
    rng = np.random.default_rng(12)
    y, x = np.mgrid[0:height // 2, 0:width // 2]
    u = 128 + 20 * np.sin(x / 7.0) + rng.normal(0, 2, (frames, height // 2, width // 2))
    v = 120 + 25 * np.cos(y / 5.0) + rng.normal(0, 2, (frames, height // 2, width // 2))
    return (np.clip(np.round(u), 0, 255).astype(np.uint8), np.clip(np.round(v), 0, 255).astype(np.uint8))


def test_qim_round_trip_without_attack() -> None:
    luma = _clip()
    layout = watermark.WatermarkLayout(luma.shape[0], luma.shape[1], luma.shape[2], 64.0, group=2)
    bits = np.random.default_rng(6).integers(0, 2, layout.capacity).astype(np.uint8)
    marked = watermark.embed(luma, bits, KEY, layout)
    soft = watermark.slot_soft_values(watermark.frame_soft_values(marked, KEY, layout), layout)
    assert np.array_equal((soft > 0).astype(np.uint8), bits)
    assert np.mean(np.abs(soft)) > 0.9  # pixel rounding barely moves the lattice point


def test_qim_survives_moderate_pixel_noise() -> None:
    luma = _clip()
    layout = watermark.WatermarkLayout(luma.shape[0], luma.shape[1], luma.shape[2], 64.0, group=3)
    bits = np.random.default_rng(7).integers(0, 2, layout.capacity).astype(np.uint8)
    marked = watermark.embed(luma, bits, KEY, layout).astype(np.float64)
    noisy = np.clip(np.round(marked + np.random.default_rng(8).normal(0, 3, marked.shape)), 0, 255)
    soft = watermark.slot_soft_values(watermark.frame_soft_values(noisy.astype(np.uint8), KEY, layout), layout)
    assert np.mean((soft > 0) != bits) < 0.02


def test_wrong_key_reads_noise() -> None:
    luma = _clip()
    layout = watermark.WatermarkLayout(luma.shape[0], luma.shape[1], luma.shape[2], 64.0)
    bits = np.random.default_rng(9).integers(0, 2, layout.capacity).astype(np.uint8)
    marked = watermark.embed(luma, bits, KEY, layout)
    soft = watermark.slot_soft_values(watermark.frame_soft_values(marked, b"x" * 32, layout), layout)
    assert 0.4 < np.mean((soft > 0) != bits) < 0.6


def test_permutation_and_dither_are_deterministic_and_keyed() -> None:
    layout = watermark.WatermarkLayout(6, 96, 128, 64.0)
    order = watermark.permutation(KEY, layout)
    assert np.array_equal(order, watermark.permutation(KEY, layout))
    assert sorted(order.tolist()) == list(range(layout.capacity))
    assert not np.array_equal(order, watermark.permutation(b"y" * 32, layout))
    # Dither depends on the frame geometry only, so it is constant over time.
    longer = watermark.WatermarkLayout(12, 96, 128, 64.0)
    assert np.array_equal(watermark.dither(KEY, layout), watermark.dither(KEY, longer))


def test_spread_and_gather_combine_repetitions() -> None:
    order = np.random.default_rng(10).permutation(50)
    codeword = np.array([1, 0, 1, 1, 0], dtype=np.uint8)
    slots = watermark.spread(codeword, order)
    soft = 2.0 * slots - 1.0
    soft[order[:5]] = -soft[order[:5]]  # corrupt one copy of every bit
    combined = watermark.gather(soft, order, len(codeword))
    assert np.array_equal((combined > 0).astype(np.uint8), codeword)


def test_embedding_keeps_fingerprint_cells() -> None:
    luma = _clip(height=128, width=128)
    layout = watermark.WatermarkLayout(luma.shape[0], 128, 128, 80.0)
    bits = np.random.default_rng(11).integers(0, 2, layout.capacity).astype(np.uint8)
    marked = watermark.embed(luma, bits, KEY, layout)
    spec = features.FingerprintSpec()
    drift = np.abs(features.cell_means(luma, spec.block) - features.cell_means(marked, spec.block))
    assert drift.max() < 0.5


def test_layout_validation() -> None:
    with pytest.raises(ValueError):
        watermark.WatermarkLayout(1, 96, 128, 64.0, coefficients=((0, 0),))
    with pytest.raises(ValueError):
        watermark.WatermarkLayout(2, 96, 128, 64.0, group=3)
    with pytest.raises(ValueError):
        watermark.WatermarkLayout(2, 96, 128, 64.0, block=12)


def test_fingerprint_blob_round_trip_and_tamper_detection() -> None:
    luma = _clip(frames=13, height=96, width=130)
    u, v = _chroma(*luma.shape)
    spec = features.FingerprintSpec()
    assert spec.binds_chroma and list(spec.sampled_frames(13)) == [0, 6, 12]
    print_ = features.compute(luma, spec, u, v)
    assert print_.chroma_values.shape == (3, 2, 1, 2)  # 48x65 chroma plane: one row, a partial column
    blob = print_.to_bytes()
    assert len(blob) == spec.blob_bytes(*luma.shape)
    decoded = features.Fingerprint.from_bytes(blob)
    assert np.array_equal(decoded.values, print_.values)
    assert np.array_equal(decoded.chroma_values, print_.chroma_values)
    with pytest.raises(ValueError):
        features.Fingerprint.from_bytes(blob[:-1])
    with pytest.raises(ValueError):  # the spec binds chroma, so the planes are required
        features.compute(luma, spec)
    tolerance = features.Tolerance()
    assert features.compare(decoded, features.compute(luma, spec, u, v), tolerance).accepted
    edited = luma.copy()
    edited[2, 10:58, 10:58] = 255 - edited[2, 10:58, 10:58]
    result = features.compare(decoded, features.compute(edited, spec, u, v), tolerance)
    assert not result.accepted and "luma" in result.reason
    assert {cell[0] for cell in result.flagged} == {2}
    shorter = features.compute(luma[:-1], spec, u[:-1], v[:-1])
    assert not features.compare(decoded, shorter, tolerance).accepted


def test_fingerprint_catches_recolouring_of_sampled_frames() -> None:
    luma = _clip(frames=13, height=96, width=130)
    u, v = _chroma(*luma.shape)
    spec, tolerance = features.FingerprintSpec(), features.Tolerance()
    carried = features.compute(luma, spec, u, v)
    recoloured = v.copy()
    recoloured[6] = np.clip(recoloured[6].astype(np.int64) + 16, 0, 255).astype(np.uint8)
    result = features.compare(carried, features.compute(luma, spec, u, recoloured), tolerance)
    assert not result.accepted and "colour" in result.reason
    assert result.max_chroma_delta >= tolerance.chroma_hard_delta
    assert {cell[0] for cell in result.flagged_chroma} == {6}
    assert {cell[1] for cell in result.flagged_chroma} == {1}  # plane 1 is V
    # Frame 7 is not sampled: the same recolouring there is invisible to the fingerprint.
    unsampled = v.copy()
    unsampled[7] = np.clip(unsampled[7].astype(np.int64) + 16, 0, 255).astype(np.uint8)
    assert features.compare(carried, features.compute(luma, spec, u, unsampled), tolerance).accepted


def test_luma_only_fingerprint_spec() -> None:
    luma = _clip(frames=4, height=96, width=128)
    spec = features.FingerprintSpec(chroma_every=0)
    print_ = features.compute(luma, spec)
    assert print_.chroma_values.size == 0 and spec.chroma_bytes(*luma.shape) == 0
    blob = print_.to_bytes()
    assert len(blob) == spec.blob_bytes(*luma.shape)
    decoded = features.Fingerprint.from_bytes(blob)
    assert decoded.spec == spec and np.array_equal(decoded.values, print_.values)
    assert features.compare(decoded, print_, features.Tolerance()).accepted
    # Differing specs never compare equal, so luma-only and chroma blobs cannot be confused.
    u, v = _chroma(*luma.shape)
    assert not features.compare(decoded, features.compute(luma, features.FingerprintSpec(), u, v),
                                features.Tolerance()).accepted


def test_tolerance_validation() -> None:
    with pytest.raises(ValueError):
        features.Tolerance(chroma_drift_delta=3, chroma_hard_delta=2)
    with pytest.raises(ValueError):
        features.Tolerance(chroma_max_drift_fraction=1.0)
    with pytest.raises(ValueError):
        features.FingerprintSpec(chroma_block=4)
    with pytest.raises(ValueError):
        features.FingerprintSpec(chroma_every=256)
