"""Unit tests: every compared method embeds exactly the message bits it claims (synthetic candidates)."""

from __future__ import annotations

import random
import unittest

from benchmark.stego_embed_new import Candidate, rbsp_to_ebsp
from benchmark.stego_methods_new import METHODS, drift_tier, keyed_order, wang2018_hosts
from src.video_binding import ebsp_to_rbsp


def _candidate(index: int, rng: random.Random, category: int = 1) -> Candidate:
    t1 = rng.randint(1, 3)
    signs = tuple((1000 + 10 * index + k, rng.randint(0, 1)) for k in range(t1))
    scan = [0] * 15 + [0]
    for k, (_, sign) in enumerate(signs):
        scan[10 - k] = -1 if sign else 1
    mb = index // 6
    return Candidate(frame=0, nal=3, rbsp_bit=signs[0][0], mb=mb, mb_row=mb // 4, mb_col=mb % 4, mb_height=6,
                     category=category, block=index % 6, mb_type=0, total_coeff=t1, trailing_ones=t1,
                     scan=tuple(scan), bit=signs[0][1], signs=signs)


def _apply(items: list[Candidate], flips: list[tuple[int, int]]) -> dict[int, int]:
    """Sign value per RBSP offset after flipping."""
    values = {offset: sign for c in items for offset, sign in c.signs}
    for _, offset in flips:
        values[offset] ^= 1
    return values


def _decode(method: str, items: list[Candidate], count: int, key: bytes, values: dict[int, int]) -> list[int]:
    luma = sorted((c for c in items if c.category == 1), key=lambda c: (c.mb, c.category, c.block))
    if method in ("random", "low-drift", "kim2007", "sequential"):
        if method == "random":
            chosen = keyed_order(items, key)[:count]
        elif method == "low-drift":
            chosen = sorted(keyed_order(items, key), key=drift_tier)[:count]
        elif method == "kim2007":
            chosen = luma[:count]
        else:
            chosen = sorted(items, key=lambda c: (c.mb, c.category, c.block))[:count]
        return [values[c.rbsp_bit] for c in chosen]
    if method == "lin2012":
        blocks = keyed_order(luma, key)[:count]
        return [sum(values[o] for o, _ in b.signs) % 2 for b in blocks]
    if method == "wang2018":
        bits: list[int] = []
        for host in wang2018_hosts(luma, count):
            if len(bits) >= count:
                break
            if len(host.signs) < 3 or len(bits) + 2 > count:
                bits.append(values[host.signs[0][0]])
            else:
                c1, c2, c3 = (values[o] for o, _ in host.signs[:3])
                bits += [c1 ^ c2, c2 ^ c3]
        return bits
    by_mb: dict[int, int] = {}
    for c in luma:
        by_mb[c.mb] = by_mb.get(c.mb, 0) ^ (sum(values[o] for o, _ in c.signs) % 2)
    return [by_mb[mb] for mb in sorted(by_mb)][:count]


class MethodRoundTripTests(unittest.TestCase):
    def test_every_method_embeds_its_message(self) -> None:
        rng = random.Random(7)
        items = [_candidate(i, rng, category=rng.choice((0, 1, 1, 1, 2, 3))) for i in range(240)]
        key = b"k" * 36
        for method, place in METHODS.items():
            for count in (1, 13, 40):
                message = [rng.randint(0, 1) for _ in range(count)]
                flips, embedded = place(items, count, key, lambda i, m=message: m[i])
                self.assertEqual(embedded, count, method)
                decoded = _decode(method, items, count, key, _apply(items, flips))
                self.assertEqual(decoded, message, f"{method} count={count}")

    def test_matrix_code_flips_at_most_one_sign_per_host(self) -> None:
        rng = random.Random(3)
        items = [_candidate(i, rng) for i in range(120)]
        flips, _ = METHODS["wang2018"](items, 60, b"x" * 36, lambda i: i % 2)
        hosts = {offset // 10 for _, offset in flips}
        self.assertEqual(len(hosts), len(flips))

    def test_wang2018_hosts_span_the_picture(self) -> None:
        rng = random.Random(5)
        items = [_candidate(i, rng) for i in range(600)]
        luma = sorted(items, key=lambda c: (c.mb, c.category, c.block))
        flips, placed = METHODS["wang2018"](items, 64, b"y" * 36, lambda i: i % 2)
        self.assertEqual(placed, 64)
        used = [c for c in wang2018_hosts(luma, 64)]
        self.assertGreater(max(c.mb for c in used), 0.8 * max(c.mb for c in luma))

    def test_rbsp_escaping_round_trips(self) -> None:
        for data in (b"\x00\x00\x00\x01", b"\x65\x00\x00\x03\x00\x00\x02\xff", bytes(range(256)) * 2):
            self.assertEqual(ebsp_to_rbsp(rbsp_to_ebsp(data)), bytearray(data))


if __name__ == "__main__":
    unittest.main()
