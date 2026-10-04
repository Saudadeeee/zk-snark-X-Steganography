"""Unit tests for the benchmark analysis helpers (no native tools, FFmpeg or Node.js needed)."""

from __future__ import annotations

import unittest

from benchmark.e2e_benchmark_new import file_offset_of_rbsp_bit, flip_sign_bit
from benchmark.media_benchmark_new import is_frame_not_found, sign_statistics, verify_zk_payload
from benchmark.reports_new import _paginate, _per, _wrap_row, num
from src.native_blind_contract import segment_schedule

KEY = bytes(range(32))


def _segments(bits_per_segment: list[list[int]]) -> dict:
    """segments-1 JSON with one Luma4x4 candidate per block, as zkstego_inspect prints it."""
    segments = []
    for index, bits in enumerate(bits_per_segment):
        nal = 3 + 2 * index
        candidates = [{"id": f"{nal + 1}:{block}:1:{block}:{100 + 10 * block}", "nal_index": nal,
                       "rbsp_bit_offset": 100 + 10 * block, "bit": bit} for block, bit in enumerate(bits)]
        segments.append({"segment": index, "idr_nal_index": nal, "analysis_nal_index": nal + 1,
                         "candidate_count": len(bits), "capacity": min(4, len(bits)), "candidates": candidates})
    return {"schema": "segments-1", "segments": segments}


def _flip(segments: dict, positions: set[tuple[int, int]]) -> dict:
    flipped = {"schema": segments["schema"], "segments": []}
    for segment in segments["segments"]:
        candidates = [{**item, "bit": item["bit"] ^ ((item["nal_index"], item["rbsp_bit_offset"]) in positions)}
                      for item in segment["candidates"]]
        flipped["segments"].append({**segment, "candidates": candidates})
    return flipped


class SignStatisticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cover = _segments([[0, 1, 0, 1, 1, 0, 0, 1], [1, 1, 0, 0, 1, 0, 1, 0]])
        self.placements = segment_schedule(self.cover, KEY, 6, 4)
        self.scheduled = {(p.candidate.nal_index, p.candidate.rbsp_bit_offset) for p in self.placements}

    def test_counts_only_scheduled_changes(self) -> None:
        changed = set(list(self.scheduled)[:3])
        stats = sign_statistics(self.cover, _flip(self.cover, changed), KEY, 6, 4)
        self.assertEqual(stats["candidate_signs"], 16)
        self.assertEqual(stats["scheduled_positions"], 6)
        self.assertEqual(stats["changed_signs"], 3)
        self.assertEqual(stats["changed_outside_schedule"], 0)
        self.assertAlmostEqual(stats["changed_fraction_of_scheduled"], 0.5)

    def test_reports_a_change_outside_the_schedule(self) -> None:
        all_positions = {(c["nal_index"], c["rbsp_bit_offset"]) for s in self.cover["segments"] for c in s["candidates"]}
        stray = next(iter(all_positions - self.scheduled))
        stats = sign_statistics(self.cover, _flip(self.cover, {stray}), KEY, 6, 4)
        self.assertEqual(stats["changed_outside_schedule"], 1)
        self.assertEqual(stats["idr_segments_with_changes"], 1)

    def test_unchanged_stream_has_zero_delta_and_z(self) -> None:
        stats = sign_statistics(self.cover, self.cover, KEY, 6, 4)
        self.assertEqual(stats["changed_signs"], 0)
        self.assertEqual(stats["negative_sign_fraction_delta"], 0.0)
        self.assertEqual(stats["two_proportion_z"], 0.0)

    def test_rejects_streams_with_different_candidates(self) -> None:
        other = _segments([[0, 1, 0, 1, 1, 0, 0, 1]])
        with self.assertRaises(RuntimeError):
            sign_statistics(self.cover, other, KEY, 4, 4)


class StreamEditTests(unittest.TestCase):
    # start code, IDR header 0x65, then EBSP 00 00 03 01 AA (RBSP 00 00 01 AA)
    DATA = bytes.fromhex("00000001" "65" "00000301aa")
    NAL = {"index": 0, "offset": 0, "start_code_bytes": 4, "ebsp_bytes": 5}

    def test_maps_rbsp_bits_past_an_emulation_prevention_byte(self) -> None:
        self.assertEqual(file_offset_of_rbsp_bit(self.DATA, self.NAL, 0), 5)
        self.assertEqual(file_offset_of_rbsp_bit(self.DATA, self.NAL, 16), 8)
        self.assertEqual(file_offset_of_rbsp_bit(self.DATA, self.NAL, 31), 9)

    def test_flip_changes_exactly_one_bit(self) -> None:
        edited = flip_sign_bit(self.DATA, {0: self.NAL}, 0, 24)
        self.assertEqual(edited[9], 0x2A)
        self.assertEqual(edited[:9], self.DATA[:9])

    def test_bit_outside_the_nal_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            file_offset_of_rbsp_bit(self.DATA, self.NAL, 32)


class VerifyDecisionTests(unittest.TestCase):
    def test_frame_not_found_needs_exit_2_and_a_frame_marker(self) -> None:
        self.assertTrue(is_frame_not_found(2, "error: CAVLC stream version is invalid"))
        self.assertFalse(is_frame_not_found(2, "error: input stream contained no IDR segments"))
        self.assertFalse(is_frame_not_found(1, "CAVLC stream version is invalid"))

    def test_malformed_payload_is_rejected_before_groth16(self) -> None:
        for payload_hex in (b"zz", b"00000005abcd"):
            result = verify_zk_payload(None, payload_hex, KEY)  # type: ignore[arg-type]
            self.assertFalse(result["verified"])
            self.assertEqual(result["reason"], "malformed_proof_payload")


class ReportLayoutTests(unittest.TestCase):
    def test_wrap_keeps_text_and_respects_existing_breaks(self) -> None:
        cells = _wrap_row(["một dòng rất dài " * 6, "a\nb"], [0.1, 0.9], 8)
        self.assertGreater(cells[0].count("\n"), 0)
        self.assertEqual(cells[0].replace("\n", " ").split(), ("một dòng rất dài " * 6).split())
        self.assertEqual(cells[1], "a\nb")

    def test_paginate_splits_by_height_and_keeps_every_row(self) -> None:
        rows = [[str(i), "x"] for i in range(50)]
        pages = _paginate(["h", "h"], rows, 8, 3.0, 40)
        self.assertGreater(len(pages), 1)
        self.assertEqual([row for page in pages for row in page], rows)

    def test_number_formatting(self) -> None:
        self.assertEqual(num(1234.567, 1), "1,234.6")
        self.assertEqual(num(float("inf")), "∞")
        self.assertEqual(num(None), "—")
        self.assertIsNone(_per(10, 0))
        self.assertEqual(_per(10, 4), 2.5)


if __name__ == "__main__":
    unittest.main()
