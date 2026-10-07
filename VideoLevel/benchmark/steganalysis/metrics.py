"""Detection metrics: ROC AUC and P_E = min over thresholds of (P_FA + P_MD) / 2.

Convention: label 1 = stego, larger score = "more likely stego".
"""

from __future__ import annotations

import numpy as np
from scipy.stats import rankdata


def _validate(scores: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    scores = np.asarray(scores, dtype=np.float64).ravel()
    labels = np.asarray(labels).ravel().astype(np.int64)
    if scores.shape != labels.shape:
        raise ValueError("scores and labels differ in length")
    if not np.isin(labels, (0, 1)).all():
        raise ValueError("labels must be 0 (cover) or 1 (stego)")
    if labels.min(initial=1) == labels.max(initial=0) or scores.size == 0:
        raise ValueError("both classes are required")
    if not np.isfinite(scores).all():
        raise ValueError("scores must be finite")
    return scores, labels


def roc_auc(scores: np.ndarray, labels: np.ndarray) -> float:
    """Area under the ROC curve (Mann-Whitney statistic, ties count one half)."""
    scores, labels = _validate(scores, labels)
    ranks = rankdata(scores)
    positives = labels == 1
    n_pos, n_neg = int(positives.sum()), int((~positives).sum())
    return float((ranks[positives].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def pe_threshold(scores: np.ndarray, labels: np.ndarray) -> tuple[float, float]:
    """Return (P_E, threshold) where 'stego' is decided for score > threshold.

    All distinct cut points are scanned, including "everything stego" and
    "everything cover", so P_E <= 0.5.
    """
    scores, labels = _validate(scores, labels)
    order = np.argsort(-scores, kind="stable")
    sorted_scores, sorted_labels = scores[order], labels[order]
    n_pos = int(sorted_labels.sum())
    n_neg = sorted_labels.size - n_pos
    true_pos = np.cumsum(sorted_labels)
    false_pos = np.cumsum(1 - sorted_labels)
    # A cut is valid only after the last element of a block of equal scores.
    last_of_tie = np.r_[sorted_scores[1:] != sorted_scores[:-1], True]
    p_md = np.r_[1.0, 1.0 - true_pos[last_of_tie] / n_pos]
    p_fa = np.r_[0.0, false_pos[last_of_tie] / n_neg]
    errors = 0.5 * (p_fa + p_md)
    best = int(np.argmin(errors))
    cut_scores = sorted_scores[last_of_tie]
    if best == 0:
        threshold = float(sorted_scores[0])
    elif best == cut_scores.size:
        threshold = float(cut_scores[-1]) - 1.0
    else:
        threshold = float(0.5 * (cut_scores[best - 1] + cut_scores[best]))
    return float(errors[best]), threshold


def p_e(scores: np.ndarray, labels: np.ndarray) -> float:
    return pe_threshold(scores, labels)[0]


def summarise(scores: np.ndarray, labels: np.ndarray) -> dict[str, float]:
    return {"auc": roc_auc(scores, labels), "p_e": p_e(scores, labels)}
