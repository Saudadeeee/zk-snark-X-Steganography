"""Unit tests for the distortion model (pure arithmetic; no FFmpeg or native tools)."""

from __future__ import annotations

import math
import unittest

from benchmark.distortion_model_new import (
    cap_for_target,
    chroma_qp,
    exact_block_flip_sse,
    flip_sse,
    flip_sse_exact,
    flipped_bits,
    flipped_raster,
    kappa,
    max_flips,
    plane_of,
    psnr_from_sse,
    qstep,
)


class ModelTests(unittest.TestCase):
    def test_qstep_table_and_doubling(self) -> None:
        self.assertEqual(qstep(4), 1.0)
        self.assertEqual(qstep(19), 5.5)
        for qp in range(0, 46):
            self.assertAlmostEqual(qstep(qp + 6), 2 * qstep(qp))
        with self.assertRaises(ValueError):
            qstep(52)

    def test_flip_energy_matches_dequantization_exactly_for_dc_class(self) -> None:
        for qp in range(52):
            self.assertAlmostEqual(flip_sse_exact(qp, 0, 0), flip_sse(qp))
            self.assertAlmostEqual(flip_sse_exact(qp, 2, 2), flip_sse(qp))

    def test_kappa_bounds(self) -> None:
        values = [kappa(qp, r, c) for qp in range(52) for r in range(4) for c in range(4)]
        self.assertGreaterEqual(min(values), 0.92)
        self.assertLessEqual(max(values), 1.06)

    def test_exact_block_energy_close_to_model(self) -> None:
        # Demo block (QP 19): scan [1, -1, 0, -1, 1, 0, ...]; its measured residual change has energy 128.
        scan = [1, -1, 0, -1, 1] + [0] * 11
        self.assertEqual(exact_block_flip_sse(scan, 19), 128.0)
        self.assertLess(abs(exact_block_flip_sse(scan, 19) / flip_sse(19) - 1), 0.1)

    def test_flipped_raster_uses_last_nonzero(self) -> None:
        self.assertEqual(flipped_raster([1, -1, 0, -1, 1] + [0] * 11, 1), (1, 1))  # zig-zag 4 -> raster 5
        self.assertEqual(flipped_raster([1] + [0] * 14, 3), (0, 1))  # AC block: scan starts at zig-zag 1
        self.assertEqual(flipped_raster([1, 0, 0, 0], 2), (0, 0))

    def test_chroma_qp_table(self) -> None:
        self.assertEqual(chroma_qp(19, -2), 17)
        self.assertEqual(chroma_qp(30, 0), 29)
        self.assertEqual(chroma_qp(51, 0), 39)
        self.assertEqual(chroma_qp(-5, 0), 0)

    def test_plane_of(self) -> None:
        self.assertEqual([plane_of(0, 0), plane_of(1, 15), plane_of(2, 0), plane_of(2, 1)], [0, 0, 1, 2])
        self.assertEqual([plane_of(3, 3), plane_of(3, 4)], [1, 2])

    def test_inverse_formula_round_trips(self) -> None:
        pixels, qp, gain = 352 * 288, 19, 3.0
        flips = max_flips(45.0, qp, gain, pixels)
        self.assertAlmostEqual(psnr_from_sse(flips * gain * flip_sse(qp), pixels), 45.0)
        self.assertEqual(cap_for_target(45.0, qp, gain, pixels), int(flips / 0.5))
        self.assertTrue(math.isinf(psnr_from_sse(0, pixels)))
        # Six QP steps quadruple the energy: the cap shrinks by four.
        self.assertAlmostEqual(max_flips(45.0, qp + 6, gain, pixels), flips / 4)

    def test_flipped_bits_reads_rbsp_differences(self) -> None:
        cover = b"\x00\x00\x00\x01\x65\x88\x10\x00\x00\x01\x41\xff"
        stego = b"\x00\x00\x00\x01\x65\x88\x11\x00\x00\x01\x41\x7f"
        self.assertEqual(flipped_bits(cover, stego), [(0, 15), (1, 0)])


if __name__ == "__main__":
    unittest.main()
