"""Cost-adaptive syndrome coding over the blind stable carriers.

The stable magnitude carrier set (one ``|level| >= 4`` AC coefficient per luma
4x4 block, LSB replacement) is invariant under its own modification, so the
extractor recomputes the same carriers, in the same keyed order, from the stego
video.  Direct embedding writes one payload bit per carrier and changes about
half of them.  This module instead writes the payload as the *syndrome* of the
carrier bits under a syndrome-trellis code (STC, Filler-Judas-Fridrich 2011):

* the extractor reads every carrier bit ``y`` and computes ``m = H y`` -- no
  costs, no side information, only the pinned code parameters;
* the embedder runs a Viterbi search for the stego bits ``y`` with ``H y = m``
  that minimise the summed cost of the carriers it changes.

With ``n`` carriers for ``m`` bits (rate ``m/n < 1``) this needs far fewer
changes than direct replacement and puts them where the cost model says they
are least detectable.  The parity-check matrix depends only on public code
parameters and on ``(m, n)``; both are recomputable by the extractor.

Costs use only carrier-invariant data (``|level| >> 1``, zero pattern), so they
can also be recomputed from the stego video, although STC extraction itself
never needs them.
"""

from __future__ import annotations

import hashlib
import math
from typing import Iterable, Sequence

import numpy as np

STC_COLUMN_DOMAIN = b"zkstego/adaptive-carriers/stc-columns/v1\x00"
MIN_CONSTRAINT_HEIGHT = 1
MAX_CONSTRAINT_HEIGHT = 12
COST_MODELS = ("uniform", "texture-magnitude-v1")
# Texture scale (in invariant level units summed over a macroblock) at which the
# texture factor halves the cost; fixed so that every party computes the same costs.
TEXTURE_SCALE = 32.0

Position = tuple[int, int, int]


# -- syndrome-trellis code ------------------------------------------------- #

def _require_height(height: int) -> int:
    if isinstance(height, bool) or not isinstance(height, int):
        raise ValueError("constraint height must be an integer")
    if not MIN_CONSTRAINT_HEIGHT <= height <= MAX_CONSTRAINT_HEIGHT:
        raise ValueError(
            f"constraint height must be in [{MIN_CONSTRAINT_HEIGHT}, {MAX_CONSTRAINT_HEIGHT}]"
        )
    return height


def stc_columns(height: int, width: int) -> tuple[int, ...]:
    """Public, deterministic columns of the ``height x width`` STC submatrix.

    Each column is a ``height``-bit integer whose bit ``i`` is row ``j + i`` of
    the parity-check matrix for message bit ``j``.  The lowest and highest bits
    are set, as in the published STC constructions; the lowest bit guarantees
    that every message bit can be reached by its own block (no infeasibility).
    """
    _require_height(height)
    if isinstance(width, bool) or not isinstance(width, int) or width <= 0:
        raise ValueError("submatrix width must be a positive integer")
    top = 1 << (height - 1)
    columns = []
    counter = 0
    while len(columns) < width:
        digest = hashlib.sha256(
            STC_COLUMN_DOMAIN + height.to_bytes(1, "big") + width.to_bytes(4, "big")
            + counter.to_bytes(4, "big")
        ).digest()
        counter += 1
        for offset in range(0, len(digest) - 1, 2):
            if len(columns) == width:
                break
            value = int.from_bytes(digest[offset:offset + 2], "big") & ((1 << height) - 1)
            columns.append(value | 1 | top)
    return tuple(columns)


def stc_block_widths(message_bits: int, carrier_bits: int) -> list[int]:
    """Carriers assigned to each message bit; they sum to ``carrier_bits``."""
    if isinstance(message_bits, bool) or not isinstance(message_bits, int) or message_bits <= 0:
        raise ValueError("message_bits must be a positive integer")
    if isinstance(carrier_bits, bool) or not isinstance(carrier_bits, int):
        raise ValueError("carrier_bits must be an integer")
    if carrier_bits < message_bits:
        raise ValueError(
            f"syndrome coding needs at least one carrier per bit: {carrier_bits} < {message_bits}"
        )
    return [
        ((index + 1) * carrier_bits) // message_bits - (index * carrier_bits) // message_bits
        for index in range(message_bits)
    ]


def _block_layout(message_bits: int, carrier_bits: int, height: int):
    widths = stc_block_widths(message_bits, carrier_bits)
    tables = {width: stc_columns(height, width) for width in set(widths)}
    for index, width in enumerate(widths):
        mask = (1 << min(height, message_bits - index)) - 1
        yield index, width, [column & mask for column in tables[width]]


def _as_bits(name: str, bits: Sequence[int]) -> list[int]:
    values = [int(bit) for bit in bits]
    if any(bit not in (0, 1) for bit in values):
        raise ValueError(f"{name} must contain only 0 or 1")
    return values


def stc_extract(stego_bits: Sequence[int], message_bits: int, height: int) -> list[int]:
    """Syndrome ``H y`` of the carrier bits: the embedded message."""
    _require_height(height)
    bits = _as_bits("stego_bits", stego_bits)
    message = []
    state = 0
    cursor = 0
    for _index, width, columns in _block_layout(message_bits, len(bits), height):
        for column in columns:
            if bits[cursor]:
                state ^= column
            cursor += 1
        message.append(state & 1)
        state >>= 1
    return message


def stc_embed(
    cover_bits: Sequence[int], message: Sequence[int], costs: Sequence[float], height: int,
) -> list[int]:
    """Minimum-cost stego bits ``y`` with ``stc_extract(y) == message`` (Viterbi)."""
    _require_height(height)
    cover = _as_bits("cover_bits", cover_bits)
    target = _as_bits("message", message)
    weights = np.asarray(costs, dtype=np.float64)
    if weights.shape != (len(cover),):
        raise ValueError("one cost per carrier is required")
    if not np.all(np.isfinite(weights)) or np.any(weights < 0):
        raise ValueError("costs must be finite and non-negative")
    states = 1 << height
    index = np.arange(states)
    cost = np.full(states, np.inf)
    cost[0] = 0.0
    choices = np.zeros((len(cover), states), dtype=np.bool_)
    layout = list(_block_layout(len(target), len(cover), height))
    cursor = 0
    for bit_index, _width, columns in layout:
        for column in columns:
            weight = weights[cursor]
            keep = cost + (weight if cover[cursor] else 0.0)
            flip = cost[index ^ column] + (0.0 if cover[cursor] else weight)
            chosen = flip < keep
            cost = np.where(chosen, flip, keep)
            choices[cursor] = chosen
            cursor += 1
        shifted = np.full(states, np.inf)
        shifted[: states // 2] = cost[target[bit_index]::2]
        cost = shifted
    if not math.isfinite(cost[0]):
        raise RuntimeError("syndrome-trellis search found no solution")
    stego = [0] * len(cover)
    state = 0
    cursor = len(cover) - 1
    for bit_index, _width, columns in reversed(layout):
        state = (state << 1) | target[bit_index]
        for column in reversed(columns):
            if choices[cursor, state]:
                stego[cursor] = 1
                state ^= column
            cursor -= 1
    if state != 0:
        raise RuntimeError("syndrome-trellis backtrack did not return to the start state")
    return stego


# -- carrier-invariant cost model ------------------------------------------ #

def invariant_level(value: int) -> int:
    """Per-coefficient value that no carrier modification changes.

    Carriers only toggle the LSB of a magnitude ``>= 4`` (or, for sign
    carriers, the sign of a trailing one), so ``|level| >> 1`` and the zero
    pattern are preserved for every coefficient of the block.
    """
    magnitude = abs(int(value))
    return (magnitude >> 1) + (1 if magnitude else 0)


def macroblock_texture(coefficients: Iterable[tuple[int, int, Sequence[int]]]) -> dict[int, int]:
    """Invariant AC activity of each macroblock's 16 luma 4x4 blocks."""
    texture: dict[int, int] = {}
    for macroblock, block, levels in coefficients:
        if block >= 16:
            continue
        texture[int(macroblock)] = texture.get(int(macroblock), 0) + sum(
            invariant_level(level) for level in list(levels)[1:]
        )
    return texture


def carrier_costs(
    positions: Sequence[Position],
    coefficients: Sequence[tuple[int, int, Sequence[int]]],
    model: str,
) -> list[float]:
    """Detectability cost of changing each carrier, from invariant data only.

    ``texture-magnitude-v1``: ``1 / (q * (1 + T / TEXTURE_SCALE))`` where ``q``
    is the carrier's ``|level| >> 1`` (a +-1 change is relatively smaller on a
    large level and moves fewer histogram bins) and ``T`` the macroblock's
    invariant AC activity (changes hide better in textured content).
    """
    if model not in COST_MODELS:
        raise ValueError(f"unknown cost model: {model!r}")
    if model == "uniform":
        return [1.0] * len(positions)
    blocks = {(int(mb), int(blk)): list(levels) for mb, blk, levels in coefficients}
    texture = macroblock_texture(coefficients)
    costs = []
    for macroblock, block, coefficient in positions:
        levels = blocks.get((int(macroblock), int(block)))
        if levels is None:
            raise ValueError(f"no coefficients for carrier block {(macroblock, block)}")
        index = coefficient if coefficient >= 0 else ~coefficient
        quantum = max(1, abs(int(levels[index])) >> 1) if coefficient >= 0 else 1
        activity = texture.get(int(macroblock), 0)
        costs.append(1.0 / (quantum * (1.0 + activity / TEXTURE_SCALE)))
    return costs
