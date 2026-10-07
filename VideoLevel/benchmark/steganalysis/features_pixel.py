"""Pixel-domain features on the decoded luma plane: SPAM-686 and SRM-lite.

SPAM-686 (Pevny, Bas, Fridrich 2010): second-order Markov transition
probabilities of neighbouring-pixel differences truncated to T = 3, averaged
over the 4 straight directions (343) and the 4 diagonal directions (343).

SRM-lite (reduced Spatial Rich Model after Fridrich & Kodovsky 2012): each
residual is quantised as clip(round(R / (q * c)), -2, 2) with q in {1, 2} and
c the kernel's central coefficient, and summarised by 4th-order
co-occurrences of horizontally and vertically adjacent residual samples. For
directional kernels the horizontal co-occurrence uses the horizontal residual
and the vertical co-occurrence the transposed residual; H and V are merged.
Linear residuals are sign- and direction-symmetrised (169 bins); min/max
residuals merge C_min(d) with C_max(-d) and are direction-symmetrised (325
bins). Submodels, each for q = 1 then q = 2 (order of the output vector):

  linear  (169 each): s1 (1st order, c=1), s2 (2nd, c=2), s3 (3rd, c=3),
                      edge3x3 (c=4), square3x3 KB (c=4), square5x5 KV (c=12)
  min/max (325 each): s1 minmax over 4 neighbours (c=1),
                      s2 minmax over H/V (c=2), edge3x3 minmax over 4 orientations (c=4)

Dimension: 2 * (6 * 169 + 3 * 325) = 3978. Everything is vectorised numpy /
OpenCV; a 1920x1080 frame needs about one second on one core.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import cv2
import numpy as np

SPAM_T = 3
SPAM_DIM = 686
SRM_T = 2
SRM_Q = (1.0, 2.0)
_BINS = 2 * SRM_T + 1

_S1 = np.array([[0, -1, 1]], np.float32)
_S2 = np.array([[1, -2, 1]], np.float32)
_S3 = np.array([[0, 1, -3, 3, -1]], np.float32)
_EDGE3 = np.array([[-1, 2, -1], [2, -4, 2], [0, 0, 0]], np.float32)
_KB = np.array([[-1, 2, -1], [2, -4, 2], [-1, 2, -1]], np.float32)
_KV = np.array([[-1, 2, -2, 2, -1], [2, -6, 8, -6, 2], [-2, 8, -12, 8, -2],
                [2, -6, 8, -6, 2], [-1, 2, -2, 2, -1]], np.float32)
_BORDER = 2

LINEAR_SUBMODELS: tuple[tuple[str, np.ndarray, float, bool], ...] = (
    ("s1", _S1, 1.0, True), ("s2", _S2, 2.0, True), ("s3", _S3, 3.0, True),
    ("edge3x3", _EDGE3, 4.0, True), ("square3x3", _KB, 4.0, False), ("square5x5", _KV, 12.0, False),
)


def _symmetry_maps() -> tuple[np.ndarray, int, np.ndarray, int, np.ndarray]:
    """Class index of every 4-tuple under sign+reversal and under reversal only."""
    values = np.array(np.meshgrid(*[np.arange(-SRM_T, SRM_T + 1)] * 4, indexing="ij")).reshape(4, -1).T

    def index(tuples: np.ndarray) -> np.ndarray:
        shifted = tuples + SRM_T
        return ((shifted[:, 0] * _BINS + shifted[:, 1]) * _BINS + shifted[:, 2]) * _BINS + shifted[:, 3]

    plain, reverse = index(values), index(values[:, ::-1])
    sign_dir = np.minimum.reduce([plain, reverse, index(-values), index(-values[:, ::-1])])
    direction = np.minimum(plain, reverse)
    _, sign_dir_class = np.unique(sign_dir, return_inverse=True)
    _, dir_class = np.unique(direction, return_inverse=True)
    negated = index(-values)
    return sign_dir_class, int(sign_dir_class.max()) + 1, dir_class, int(dir_class.max()) + 1, negated


_SIGN_DIR_CLASS, SIGN_DIR_BINS, _DIR_CLASS, DIR_BINS, _NEGATED = _symmetry_maps()
SRM_DIM = len(SRM_Q) * (len(LINEAR_SUBMODELS) * SIGN_DIR_BINS + 3 * DIR_BINS)


def _filter(image: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Correlation with a centred kernel; the border is cropped so only valid samples remain."""
    response = cv2.filter2D(image, cv2.CV_32F, kernel, borderType=cv2.BORDER_REFLECT)
    return response[_BORDER:-_BORDER, _BORDER:-_BORDER]


def _quantise(residual: np.ndarray, step: float) -> np.ndarray:
    """clip(round(R / step), -T, T) shifted to 0..2T as uint8."""
    scaled = np.multiply(residual, np.float32(1.0 / step))
    np.rint(scaled, out=scaled)
    np.clip(scaled, -SRM_T, SRM_T, out=scaled)
    scaled += SRM_T
    return scaled.astype(np.uint8)


def _cooc_h(quantised: np.ndarray) -> np.ndarray:
    """Counts of horizontally adjacent 4-tuples of a residual already shifted to 0..2T."""
    pairs = quantised[:, :-1] * np.uint8(_BINS) + quantised[:, 1:]
    code = pairs[:, :-2].astype(np.int16) * (_BINS * _BINS) + pairs[:, 2:]
    return np.bincount(code.ravel(), minlength=_BINS ** 4).astype(np.float64)


def _cooc_hv(horizontal: np.ndarray, vertical: np.ndarray) -> np.ndarray:
    return _cooc_h(horizontal) + _cooc_h(np.ascontiguousarray(vertical.T))


def _symmetrise(counts: np.ndarray, classes: np.ndarray, size: int) -> np.ndarray:
    merged = np.bincount(classes, weights=counts, minlength=size)
    return merged / max(merged.sum(), 1.0)


def _residual_pair(image: np.ndarray, kernel: np.ndarray, directional: bool) -> tuple[np.ndarray, np.ndarray]:
    """Residual used for the horizontal co-occurrence and the one used for the vertical one."""
    horizontal = _filter(image, kernel)
    if not directional:
        return horizontal, horizontal
    return horizontal, _filter(image, np.ascontiguousarray(kernel.T)).copy()


def _minmax_residuals(image: np.ndarray) -> list[tuple[str, list[np.ndarray], float]]:
    """Residual families whose element-wise min and max form a submodel."""
    s1 = [_filter(image, kernel) for kernel in (_S1, _S1[:, ::-1].copy(), _S1.T.copy(), _S1[:, ::-1].T.copy())]
    s2 = [_filter(image, _S2), _filter(image, _S2.T.copy())]
    edges = [np.rot90(_EDGE3, turn).copy() for turn in range(4)]
    return [("s1_minmax", s1, 1.0), ("s2_minmax", s2, 2.0),
            ("edge3x3_minmax", [_filter(image, kernel) for kernel in edges], 4.0)]


def srm_lite(luma: np.ndarray) -> np.ndarray:
    """SRM-lite feature vector (3978,) of one luma plane."""
    if luma.ndim != 2 or min(luma.shape) < 2 * _BORDER + 8:
        raise ValueError(f"luma plane too small or not 2-D: {luma.shape}")
    image = luma.astype(np.float32)
    linear = [(_residual_pair(image, kernel, directional), c) for _, kernel, c, directional in LINEAR_SUBMODELS]
    minmax = [(np.minimum.reduce(family), np.maximum.reduce(family), c) for _, family, c in _minmax_residuals(image)]
    parts: list[np.ndarray] = []
    for q in SRM_Q:
        for (horizontal, vertical), c in linear:
            counts = _cooc_hv(_quantise(horizontal, q * c), _quantise(vertical, q * c))
            parts.append(_symmetrise(counts, _SIGN_DIR_CLASS, SIGN_DIR_BINS))
        for low, high, c in minmax:
            low_q, high_q = _quantise(low, q * c), _quantise(high, q * c)
            counts_min = _cooc_hv(low_q, low_q)
            counts_max = _cooc_hv(high_q, high_q)
            combined = counts_min + counts_max[_NEGATED]
            parts.append(_symmetrise(combined, _DIR_CLASS, DIR_BINS))
    return np.concatenate(parts).astype(np.float32)


def _markov(differences: tuple[np.ndarray, np.ndarray, np.ndarray]) -> np.ndarray:
    """Pr(D3 = u | D2 = v, D1 = w) as a (2T+1)^3 table, rows (w, v), column u."""
    size = 2 * SPAM_T + 1
    first, second, third = (np.clip(d, -SPAM_T, SPAM_T) + SPAM_T for d in differences)
    code = (first * size + second) * size + third
    counts = np.bincount(code.ravel(), minlength=size ** 3).astype(np.float64).reshape(size * size, size)
    totals = counts.sum(axis=1, keepdims=True)
    return np.divide(counts, totals, out=np.zeros_like(counts), where=totals > 0).ravel()


def _straight(image: np.ndarray) -> np.ndarray:
    d = image[:, :-1] - image[:, 1:]
    return _markov((d[:, :-2], d[:, 1:-1], d[:, 2:]))


def _diagonal(image: np.ndarray) -> np.ndarray:
    d = image[:-1, :-1] - image[1:, 1:]
    return _markov((d[:-2, :-2], d[1:-1, 1:-1], d[2:, 2:]))


def spam686(luma: np.ndarray) -> np.ndarray:
    """SPAM-686 feature vector of one luma plane."""
    if luma.ndim != 2 or min(luma.shape) < 4:
        raise ValueError(f"luma plane too small or not 2-D: {luma.shape}")
    image = luma.astype(np.int16)
    flips = (image, image[:, ::-1], image[::-1, :], image[::-1, ::-1])
    straight = np.mean([_straight(image), _straight(image[:, ::-1]),
                        _straight(image.T), _straight(image.T[:, ::-1])], axis=0)
    diagonal = np.mean([_diagonal(flipped) for flipped in flips], axis=0)
    return np.concatenate([straight, diagonal]).astype(np.float32)


EXTRACTORS: dict[str, tuple[Callable[[np.ndarray], np.ndarray], int]] = {
    "spam": (spam686, SPAM_DIM),
    "srmlite": (srm_lite, SRM_DIM),
}


def extract_pixel_features(planes: Sequence[np.ndarray], kind: str) -> np.ndarray:
    """Stack the ``kind`` ('spam' or 'srmlite') features of several luma planes."""
    extractor, dimension = EXTRACTORS[kind]
    if not planes:
        return np.zeros((0, dimension), np.float32)
    return np.stack([extractor(plane) for plane in planes])
