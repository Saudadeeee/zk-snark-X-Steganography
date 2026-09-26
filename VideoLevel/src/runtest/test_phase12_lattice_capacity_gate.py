"""Tests for the proof-size versus measured in-video capacity gate."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from benchmark.lattice_in_video_feasibility import assess_capacity


class LatticeInVideoCapacityGateTests(unittest.TestCase):
    def test_exact_fit_includes_framing_bytes(self):
        result = assess_capacity(proof_bytes=10, capacity_bits=104, framing_bytes=3)

        self.assertTrue(result.fits)
        self.assertEqual(result.required_bits, 104)
        self.assertEqual(result.remaining_bits, 0)

    def test_shortfall_is_reported_in_bits_and_ratio(self):
        result = assess_capacity(proof_bytes=100, capacity_bits=800, framing_bytes=4)

        self.assertFalse(result.fits)
        self.assertEqual(result.required_bits, 832)
        self.assertEqual(result.shortfall_bits, 32)
        self.assertEqual(result.required_to_capacity_ratio, 1.04)

    def test_capacity_is_not_rounded_to_whole_bytes(self):
        result = assess_capacity(proof_bytes=1, capacity_bits=7)

        self.assertFalse(result.fits)
        self.assertEqual(result.shortfall_bits, 1)

    def test_rejects_invalid_measurements(self):
        for kwargs in (
            {"proof_bytes": 0, "capacity_bits": 8},
            {"proof_bytes": 1, "capacity_bits": -1},
            {"proof_bytes": 1, "capacity_bits": 8, "framing_bytes": -1},
            {"proof_bytes": True, "capacity_bits": 8},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                assess_capacity(**kwargs)


if __name__ == "__main__":
    unittest.main()
