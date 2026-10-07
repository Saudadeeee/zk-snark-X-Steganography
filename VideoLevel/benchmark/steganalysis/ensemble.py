"""Ensemble of Fisher linear discriminants (Kodovsky, Fridrich, Holub, IEEE TIFS 2012).

Each base learner is an FLD trained on a random subspace of ``d_sub``
features and on a bootstrap sample of the training *pairs* (a cover and its
stego are drawn together). Its threshold minimises the training P_E. The
ensemble decides by majority vote; ``decision_function`` returns the mean
normalised margin, a continuous score suitable for ROC analysis. Pairs left
out of a learner's bootstrap sample give the out-of-bag (OOB) error estimate.
Pure numpy.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .metrics import pe_threshold


@dataclass(frozen=True)
class EnsembleConfig:
    d_sub: int
    n_learners: int = 51
    seed: int = 0
    ridge: float = 1e-6  # relative Tikhonov term added to the within-class scatter


@dataclass(frozen=True)
class FittedEnsemble:
    config: EnsembleConfig
    mean: np.ndarray
    scale: np.ndarray
    subspaces: np.ndarray  # (L, d_sub) feature indices
    weights: np.ndarray  # (L, d_sub)
    thresholds: np.ndarray  # (L,)
    spreads: np.ndarray  # (L,) projection standard deviation on training data
    oob_error: float

    def _projections(self, features: np.ndarray) -> np.ndarray:
        standardised = (np.asarray(features, np.float64) - self.mean) / self.scale
        columns = [standardised[:, subspace] @ weight for subspace, weight in zip(self.subspaces, self.weights)]
        return np.stack(columns, axis=1)

    def decision_function(self, features: np.ndarray) -> np.ndarray:
        """Mean over learners of (projection - threshold) / spread; > 0 leans stego."""
        return ((self._projections(features) - self.thresholds) / self.spreads).mean(axis=1)

    def votes(self, features: np.ndarray) -> np.ndarray:
        """Fraction of learners voting stego."""
        return (self._projections(features) > self.thresholds).mean(axis=1)

    def predict(self, features: np.ndarray) -> np.ndarray:
        return (self.votes(features) > 0.5).astype(np.int64)


def _fld(cover: np.ndarray, stego: np.ndarray, ridge: float) -> np.ndarray:
    """Fisher direction (S_w + lambda I)^-1 (mu_s - mu_c)."""
    difference = stego.mean(axis=0) - cover.mean(axis=0)
    centred_c = cover - cover.mean(axis=0)
    centred_s = stego - stego.mean(axis=0)
    scatter = centred_c.T @ centred_c + centred_s.T @ centred_s
    dimension = scatter.shape[0]
    lam = ridge * max(np.trace(scatter) / dimension, 1e-12)
    for _ in range(8):
        try:
            return np.linalg.solve(scatter + lam * np.eye(dimension), difference)
        except np.linalg.LinAlgError:
            lam *= 100.0
    return np.linalg.lstsq(scatter, difference, rcond=None)[0]


def _check_inputs(cover: np.ndarray, stego: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    cover, stego = np.asarray(cover, np.float64), np.asarray(stego, np.float64)
    if cover.ndim != 2 or cover.shape != stego.shape:
        raise ValueError(f"paired cover/stego matrices required, got {cover.shape} and {stego.shape}")
    if cover.shape[0] < 2:
        raise ValueError("at least two training pairs are required")
    if not (np.isfinite(cover).all() and np.isfinite(stego).all()):
        raise ValueError("features must be finite")
    return cover, stego


def train_ensemble(cover: np.ndarray, stego: np.ndarray, config: EnsembleConfig) -> FittedEnsemble:
    """Train on row-aligned cover/stego feature matrices (row i of each is one pair)."""
    cover, stego = _check_inputs(cover, stego)
    n_pairs, dimension = cover.shape
    d_sub = int(min(max(config.d_sub, 1), dimension))
    if config.n_learners < 1:
        raise ValueError("n_learners must be positive")
    stacked = np.vstack([cover, stego])
    mean = stacked.mean(axis=0)
    scale = stacked.std(axis=0)
    scale = np.where(scale > 1e-12, scale, 1.0)
    cover_z, stego_z = (cover - mean) / scale, (stego - mean) / scale
    rng = np.random.default_rng(config.seed)
    subspaces, weights, thresholds, spreads = [], [], [], []
    oob_votes = np.zeros((2, n_pairs))
    oob_counts = np.zeros(n_pairs)
    labels = np.r_[np.zeros(n_pairs), np.ones(n_pairs)]
    for _ in range(config.n_learners):
        subspace = np.sort(rng.choice(dimension, size=d_sub, replace=False))
        sample = rng.integers(0, n_pairs, size=n_pairs)
        train_c, train_s = cover_z[sample][:, subspace], stego_z[sample][:, subspace]
        weight = _fld(train_c, train_s, config.ridge)
        projections = np.r_[train_c @ weight, train_s @ weight]
        _, threshold = pe_threshold(projections, labels)
        spread = float(np.std(projections)) or 1.0
        out_of_bag = np.setdiff1d(np.arange(n_pairs), sample)
        if out_of_bag.size:
            oob_votes[0, out_of_bag] += (cover_z[out_of_bag][:, subspace] @ weight) > threshold
            oob_votes[1, out_of_bag] += (stego_z[out_of_bag][:, subspace] @ weight) > threshold
            oob_counts[out_of_bag] += 1
        subspaces.append(subspace)
        weights.append(weight)
        thresholds.append(threshold)
        spreads.append(spread)
    oob_error = _oob_error(oob_votes, oob_counts)
    return FittedEnsemble(config, mean, scale, np.array(subspaces), np.array(weights),
                          np.array(thresholds), np.array(spreads), oob_error)


def _oob_error(votes: np.ndarray, counts: np.ndarray) -> float:
    """(P_FA + P_MD) / 2 of the majority vote over the learners that did not see each pair."""
    seen = counts > 0
    if not seen.any():
        return float("nan")
    share = votes[:, seen] / counts[seen]
    false_alarm = np.mean(np.where(share[0] == 0.5, 0.5, share[0] > 0.5))
    missed = np.mean(np.where(share[1] == 0.5, 0.5, share[1] < 0.5))
    return float(0.5 * (false_alarm + missed))


def search_d_sub(cover: np.ndarray, stego: np.ndarray, grid: Sequence[int],
                 n_learners: int = 51, seed: int = 0) -> tuple[int, dict[int, float]]:
    """Pick d_sub from ``grid`` by the OOB error (the paper's automatic search, on a fixed grid)."""
    errors = {int(d): train_ensemble(cover, stego, EnsembleConfig(int(d), n_learners, seed)).oob_error
              for d in grid}
    finite = {d: e for d, e in errors.items() if np.isfinite(e)}
    best = min(finite, key=lambda d: (finite[d], d)) if finite else int(grid[0])
    return best, errors
