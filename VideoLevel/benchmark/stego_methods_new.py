"""Embedding methods compared in the evaluation, all inside a trailing-one-sign-only channel.

A method receives the candidates of one IDR picture (one per block that has a trailing
one; ``Candidate.signs`` lists every trailing-one sign of the block), the number of
message bits wanted, a per-frame key and the message bits, and returns the sign bits to
flip. Rules use only syntax that sign flips never change, so a receiver can re-derive
the positions from the stego stream.

Ours:
    random     this system's schedule: a keyed uniform choice of first trailing-one signs
               (native: HMAC ranking per IDR segment, ``--select random``)
    low-drift  cost-aware schedule: lowest drift tier first, keyed order inside a tier
               (native ``--select low-drift``)
Re-implemented baselines (selection and mapping rules only; see the paper for deviations):
    kim2007    Kim et al., ICIAR 2007: the highest-frequency trailing one of luma blocks in
               decoding order carries one bit as its sign
    lin2012    Lin et al., MINES 2012: keyed luma blocks; one bit = XOR of all trailing-one
               signs of the block; on mismatch flip one keyed trailing one
    wang2018   Wang & Ma, CSA 2018: one host luma block per E candidates; T1 in {1, 2}
               carries one bit in its first sign, T1 = 3 carries two bits with the (1, 3, 2)
               matrix code (c1^c2, c2^c3) and at most one flip; E is adapted so the payload fits
    liao2009   Liao et al., MINES 2009 / Telecommun. Syst. 2012 ("Liao-style"): one bit per
               intra MB = XOR of the luma trailing-one signs; on mismatch flip the first
               trailing one of a keyed luma block of the MB
    sequential naive unkeyed rule: first N candidates of any category in decoding order
"""
from __future__ import annotations

import hashlib
import hmac

from benchmark.distortion_model_new import flipped_raster
from benchmark.stego_embed_new import BitSource, Candidate, keyed_order, write_first_signs

Flips = list[tuple[int, int]]
LUMA_BLOCKS = 1  # category Luma4x4 / Intra16x16 luma AC (LumaDC is category 0)


def _keyed_index(key: bytes, label: bytes, size: int) -> int:
    return int.from_bytes(hmac.new(key, label, hashlib.sha256).digest()[:8], "big") % size


def _decode_order(items: list[Candidate]) -> list[Candidate]:
    return sorted(items, key=lambda c: (c.mb, c.category, c.block))


# ------------------------------------------------------------------ ours

def random_keyed(items: list[Candidate], count: int, key: bytes, bit: BitSource) -> tuple[Flips, int]:
    chosen = keyed_order(items, key)[:count]
    return write_first_signs(chosen, bit), len(chosen)


def drift_tier(cand: Candidate) -> int:
    """Cost tier (same rule as native ``--select low-drift``): r + d + f, 0 (cheapest) to 5.

    r: 2 top third of the picture, 1 middle third, 0 bottom third (more blocks predict from upper rows);
    d: 2 for DC paths (LumaDC, ChromaDC), whose change spreads over a whole MB component;
    f: 1 when the flipped AC coefficient has i + j <= 2 (low frequency changes block edges).
    """
    r = 2 if cand.mb_row * 3 < cand.mb_height else 1 if cand.mb_row * 3 < 2 * cand.mb_height else 0
    d = 2 if cand.category in (0, 2) else 0
    f = 0
    if cand.category in (1, 3):
        row, col = flipped_raster(list(cand.scan), cand.category)
        f = 1 if row + col <= 2 else 0
    return r + d + f


def low_drift(items: list[Candidate], count: int, key: bytes, bit: BitSource) -> tuple[Flips, int]:
    chosen = sorted(keyed_order(items, key), key=drift_tier)[:count]  # stable: keyed order inside a tier
    return write_first_signs(chosen, bit), len(chosen)


# ------------------------------------------------------------------ baselines

def kim2007(items: list[Candidate], count: int, key: bytes, bit: BitSource) -> tuple[Flips, int]:
    del key
    chosen = _decode_order([c for c in items if c.category == LUMA_BLOCKS])[:count]
    return write_first_signs(chosen, bit), len(chosen)


def lin2012(items: list[Candidate], count: int, key: bytes, bit: BitSource) -> tuple[Flips, int]:
    blocks = keyed_order([c for c in items if c.category == LUMA_BLOCKS], key)[:count]
    flips: Flips = []
    for index, block in enumerate(blocks):
        parity = 0
        for _, sign in block.signs:
            parity ^= sign
        if parity != bit(index):
            offset, _ = block.signs[_keyed_index(key, block.identity(), len(block.signs))]
            flips.append((block.nal, offset))
    return flips, len(blocks)


def wang2018_hosts(luma: list[Candidate], count: int) -> list[Candidate]:
    """Hosts spread evenly over the whole picture: one per E candidates, with E chosen from the
    expected bits per host (two for T1 = 3, else one) so the payload fits without bunching at the top.
    The paper fixes E in 12..20; we adapt it to the payload."""
    bits_per_host = sum(2 if len(c.signs) >= 3 else 1 for c in luma) / len(luma)
    spacing = max(1, int(len(luma) * bits_per_host // count))
    hosts = luma[::spacing]
    capacity = sum(2 if len(c.signs) >= 3 else 1 for c in hosts)
    if capacity < count:  # rare shortfall: add the remaining blocks in decoding order
        chosen = set(id(c) for c in hosts)
        hosts += [c for c in luma if id(c) not in chosen]
    return hosts


def wang2018(items: list[Candidate], count: int, key: bytes, bit: BitSource) -> tuple[Flips, int]:
    del key
    luma = _decode_order([c for c in items if c.category == LUMA_BLOCKS])
    if not luma or count == 0:
        return [], 0
    flips: Flips = []
    placed = 0
    for host in wang2018_hosts(luma, count):
        if placed >= count:
            break
        signs = host.signs
        if len(signs) < 3 or placed + 2 > count:
            if bit(placed) != signs[0][1]:
                flips.append((host.nal, signs[0][0]))
            placed += 1
            continue
        (o1, c1), (o2, c2), (o3, c3) = signs[:3]
        b1, b2 = bit(placed), bit(placed + 1)
        wrong1, wrong2 = (c1 ^ c2) != b1, (c2 ^ c3) != b2
        if wrong1 and wrong2:
            flips.append((host.nal, o2))
        elif wrong1:
            flips.append((host.nal, o1))
        elif wrong2:
            flips.append((host.nal, o3))
        placed += 2
    return flips, placed


def liao2009(items: list[Candidate], count: int, key: bytes, bit: BitSource) -> tuple[Flips, int]:
    by_mb: dict[int, list[Candidate]] = {}
    for cand in _decode_order([c for c in items if c.category == LUMA_BLOCKS]):
        by_mb.setdefault(cand.mb, []).append(cand)
    flips: Flips = []
    placed = 0
    for mb, blocks in sorted(by_mb.items()):
        if placed >= count:
            break
        parity = 0
        for block in blocks:
            for _, sign in block.signs:
                parity ^= sign
        if parity != bit(placed):
            target = blocks[_keyed_index(key, f"mb{mb}".encode(), len(blocks))]
            flips.append((target.nal, target.signs[0][0]))
        placed += 1
    return flips, placed


def sequential(items: list[Candidate], count: int, key: bytes, bit: BitSource) -> tuple[Flips, int]:
    del key
    chosen = _decode_order(items)[:count]
    return write_first_signs(chosen, bit), len(chosen)


METHODS = {"random": random_keyed, "low-drift": low_drift, "kim2007": kim2007, "lin2012": lin2012,
           "wang2018": wang2018, "liao2009": liao2009, "sequential": sequential}
