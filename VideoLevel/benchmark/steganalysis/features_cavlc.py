"""Compressed-domain features of CAVLC trailing-one (T1) signs, one vector per picture.

Notation: a *candidate* is a residual block with >= 1 trailing one; ``s`` is
its first T1 sign (the highest-frequency T1, the bit the embedder rewrites;
0 = '+', 1 = '-'); ``k`` = TrailingOnes (1..3); ``tc`` = TotalCoeff; ``cat`` in
{0 LumaDC, 1 Luma4x4/AC, 2 ChromaDC, 3 ChromaAC}. Histograms are turned into
probabilities with additive smoothing (count + 0.5) / (n + 0.5 * bins), so an
empty group yields the uniform distribution.

Feature list (dimension 323, in this order):

====  ===  ====================================================================
name  dim  definition
====  ===  ====================================================================
F1      5  candidate density per cat (count / (MBs * blocks per MB)) + overall
F2     12  P(k | cat), k = 1..3
F3      4  P(s = '-' | cat)
F4     12  P(s = '-' | cat, k)
F5     24  P(s = '-' | cat, tc class), classes tc = 1, 2, 3, 4-5, 6-8, 9-16
F6     56  joint sign pattern of the k T1s, P(pattern | cat, k): 2 + 4 + 8 per cat
F7     56  P(s, next | cat): next = sign x |level| class {1, 2, >=3} of the first
           non-T1 nonzero coefficient (next in coding order) or "none" (2 x 7)
F8     24  P(s, scan position class of the first T1 | cat), classes by pos/len
           < 0.25, < 0.6, >= 0.6 (2 x 3)
F9     48  P(s, n | cat, dir) for dir in {left, up}; n = first T1 sign of the
           neighbouring block of the same category/component, or "no T1" (2 x 3)
F10    72  P(s, n_left, n_up | cat) (2 x 3 x 3)
F11     8  P(s = n | cat, dir, neighbour has a T1)
F12     2  slice QP / 51, share of candidates inside Intra16x16 macroblocks
====  ===  ====================================================================

Embedding replaces ``s`` by a key-scheduled payload bit, which pulls F3-F5 to
1/2 and decouples ``s`` from the other T1 signs (F6), the next level (F7), the
scan position (F8) and the neighbouring blocks (F9-F11).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .cavlc_trace import CavlcTrace

CATEGORY_COUNT = 4
BLOCKS_PER_MB = np.array([1, 16, 2, 8], dtype=np.float64)
TC_EDGES = np.array([2, 3, 4, 6, 9])
POSITION_EDGES = np.array([0.25, 0.6])
PATTERN_OFFSETS = np.array([0, 0, 2, 6])  # indexed by k; sizes 2, 4, 8
FEATURE_DIM = 323


def _hist(rows: np.ndarray, codes: np.ndarray, size: int, n_rows: int) -> np.ndarray:
    counts = np.bincount(rows * size + codes, minlength=n_rows * size)
    return counts.reshape(n_rows, size).astype(np.float64)


def _normalise(counts: np.ndarray, groups: int) -> np.ndarray:
    """Smoothed probabilities within consecutive equal-size groups of the last axis."""
    shaped = counts.reshape(counts.shape[0], groups, -1)
    bins = shaped.shape[2]
    probabilities = (shaped + 0.5) / (shaped.sum(axis=2, keepdims=True) + 0.5 * bins)
    return probabilities.reshape(counts.shape[0], -1)


def _block_geometry(trace: CavlcTrace, width: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(component, grid y, grid x) of every candidate on its category's block grid."""
    cat, blk = trace.cat.astype(np.int64), trace.blk.astype(np.int64)
    mbx, mby = trace.mb % width, trace.mb // width
    luma_x = ((blk // 4) % 2) * 2 + (blk % 4) % 2
    luma_y = ((blk // 4) // 2) * 2 + (blk % 4) // 2
    component = np.select([cat == 2, cat == 3], [blk, blk // 4], 0)
    grid_y = np.select([cat == 1, cat == 3], [mby * 4 + luma_y, mby * 2 + (blk % 4) // 2], mby)
    grid_x = np.select([cat == 1, cat == 3], [mbx * 4 + luma_x, mbx * 2 + (blk % 4) % 2], mbx)
    return component, grid_y, grid_x


def _neighbour_states(trace: CavlcTrace, width: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """First-T1 state of left / upper neighbour: 0 none, 1 '+', 2 '-'."""
    component, grid_y, grid_x = _block_geometry(trace, width)
    span_x = int(grid_x.max(initial=0)) + 2
    span_y = int(grid_y.max(initial=0)) + 2
    key = ((((trace.frame.astype(np.int64) * CATEGORY_COUNT + trace.cat) * 2 + component)
            * span_y + grid_y) * span_x + grid_x)
    order = np.argsort(key, kind="stable")
    sorted_keys = key[order]
    state = 1 + trace.bit.astype(np.int64)[order]

    def lookup(target: np.ndarray, valid: np.ndarray) -> np.ndarray:
        where = np.clip(np.searchsorted(sorted_keys, target), 0, len(sorted_keys) - 1)
        found = valid & (sorted_keys[where] == target)
        return np.where(found, state[where], 0)

    return lookup(key - 1, grid_x > 0), lookup(key - span_x, grid_y > 0)


def _coefficient_ranks(coeffs: np.ndarray) -> np.ndarray:
    """Rank of each nonzero counted from the highest frequency (1 = last nonzero)."""
    nonzero = coeffs != 0
    return np.cumsum(nonzero[:, ::-1], axis=1)[:, ::-1] * nonzero


def _value_at_rank(coeffs: np.ndarray, ranks: np.ndarray, rank: np.ndarray | int) -> np.ndarray:
    target = ranks == (rank[:, None] if isinstance(rank, np.ndarray) else rank)
    return (coeffs.astype(np.int64) * target).sum(axis=1)


def _per_candidate(trace: CavlcTrace) -> dict[str, np.ndarray]:
    coeffs = trace.coeffs
    ranks = _coefficient_ranks(coeffs)
    k = trace.trailing_ones.astype(np.int64)
    pattern = np.zeros(trace.count, dtype=np.int64)
    for rank in (1, 2, 3):
        negative = (_value_at_rank(coeffs, ranks, rank) < 0) & (k >= rank)
        pattern |= negative.astype(np.int64) << (rank - 1)
    following = _value_at_rank(coeffs, ranks, k + 1)
    magnitude = np.minimum(np.abs(following), 3) - 1
    next_state = np.where(following == 0, 0, 1 + (following < 0) * 3 + magnitude)
    first_position = np.argmax(ranks == 1, axis=1)
    fraction = first_position / np.maximum(trace.coeff_len.astype(np.float64) - 1, 1)
    return {
        "k": k,
        "tc_class": np.digitize(trace.total_coeff, TC_EDGES),
        "pattern": pattern,
        "next": next_state,
        "position": np.digitize(fraction, POSITION_EDGES),
    }


def extract_cavlc_features(trace: CavlcTrace, frames: Sequence[int]) -> np.ndarray:
    """Return an array (len(frames), 323) of per-picture features."""
    known = set(trace.frame_mb_width)
    unknown = [f for f in frames if f not in known]
    if unknown:
        raise ValueError(f"frames {unknown[:5]} are not IDR pictures of the stream")
    n_rows = len(frames)
    row_of_frame = {frame: row for row, frame in enumerate(frames)}
    width_of = np.array([trace.frame_mb_width.get(int(f), 1) for f in trace.frame], dtype=np.int64)
    left, up = _neighbour_states(trace, width_of) if trace.count else (np.zeros(0, int),) * 2
    rows_all = np.array([row_of_frame.get(int(f), -1) for f in trace.frame], dtype=np.int64)
    keep = rows_all >= 0
    rows = rows_all[keep]
    derived = {name: values[keep] for name, values in _per_candidate(trace).items()}
    cat = trace.cat.astype(np.int64)[keep]
    sign = trace.bit.astype(np.int64)[keep]
    left, up = left[keep], up[keep]
    k = derived["k"]
    macroblocks = np.array([trace.frame_mb_width[f] * trace.frame_mb_height[f] for f in frames], float)

    per_cat = _hist(rows, cat, CATEGORY_COUNT, n_rows)
    density = per_cat / (macroblocks[:, None] * BLOCKS_PER_MB)
    overall = per_cat.sum(axis=1, keepdims=True) / (macroblocks[:, None] * BLOCKS_PER_MB.sum())
    blocks: list[np.ndarray] = [density, overall]
    blocks.append(_normalise(_hist(rows, cat * 3 + k - 1, 12, n_rows), CATEGORY_COUNT))
    blocks.append(_normalise(_hist(rows, cat * 2 + sign, 8, n_rows), 4)[:, 1::2])
    blocks.append(_normalise(_hist(rows, (cat * 3 + k - 1) * 2 + sign, 24, n_rows), 12)[:, 1::2])
    tc_code = (cat * 6 + derived["tc_class"]) * 2 + sign
    blocks.append(_normalise(_hist(rows, tc_code, 48, n_rows), 24)[:, 1::2])

    pattern_counts = _hist(rows, cat * 14 + PATTERN_OFFSETS[k] + derived["pattern"], 56, n_rows)
    for category in range(CATEGORY_COUNT):
        base = category * 14
        for start, size in ((0, 2), (2, 4), (6, 8)):
            group = pattern_counts[:, base + start:base + start + size]
            blocks.append(_normalise(group, 1))

    blocks.append(_normalise(_hist(rows, cat * 14 + sign * 7 + derived["next"], 56, n_rows), 4))
    blocks.append(_normalise(_hist(rows, cat * 6 + sign * 3 + derived["position"], 24, n_rows), 4))
    for neighbour in (left, up):
        blocks.append(_normalise(_hist(rows, cat * 6 + sign * 3 + neighbour, 24, n_rows), 4))
    joint = cat * 18 + sign * 9 + left * 3 + up
    blocks.append(_normalise(_hist(rows, joint, 72, n_rows), 4))
    for neighbour in (left, up):
        present = neighbour > 0
        agree = (neighbour - 1 == sign)[present].astype(np.int64)
        agreement = _hist(rows[present], cat[present] * 2 + agree, 8, n_rows)
        blocks.append(_normalise(agreement, 4)[:, 1::2])

    qp = np.array([trace.frame_qp.get(f, 0) / 51.0 for f in frames])
    intra16 = (trace.mb_type[keep] >= 1) & (trace.mb_type[keep] <= 24)
    intra16_share = (np.bincount(rows, intra16.astype(float), n_rows) + 0.5) / (
        np.bincount(rows, minlength=n_rows) + 1.0)
    blocks.append(np.column_stack([qp, intra16_share]))
    features = np.concatenate(blocks, axis=1)
    if features.shape[1] != FEATURE_DIM:
        raise AssertionError(f"CAVLC feature dimension {features.shape[1]} != {FEATURE_DIM}")
    return features.astype(np.float32)
