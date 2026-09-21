"""Contracts for the realtime CAVLC segment controller."""

import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.realtime_cavlc import CAVLCRealtimeBudget, RealtimeCAVLCScheduler
from src.bitstream.cavlc import get_run_before_table
from src.bitstream.h264 import NALUnitType, iter_annex_b_nal_units
from src.core.pipeline import iter_idr_slices, iter_idr_trace_results, iter_idr_luma_analysis
from src.runtest._helpers import run_test, section, summarise


def t_scheduler_keeps_only_fresh_segments_under_pressure():
    scheduler = RealtimeCAVLCScheduler(CAVLCRealtimeBudget(fps=30.0, max_queue_segments=2), lambda _epoch: b"proof", lambda segment, _proof: segment)
    scheduler.submit(b"old", epoch=1)
    scheduler.submit(b"current", epoch=1)
    scheduler.submit(b"fresh", epoch=1)
    assert scheduler.dropped_segments == 1
    assert scheduler.process_next().output == b"current"
    assert scheduler.process_next().output == b"fresh"


def t_scheduler_reuses_one_proof_per_epoch_and_reports_budget():
    calls = 0

    def proof(epoch: int) -> bytes:
        nonlocal calls
        calls += 1
        return f"proof-{epoch}".encode()

    scheduler = RealtimeCAVLCScheduler(CAVLCRealtimeBudget(fps=30.0), proof, lambda segment, _proof: segment)
    scheduler.submit(b"a", epoch=7)
    scheduler.submit(b"b", epoch=7)
    scheduler.process_next()
    scheduler.process_next()
    assert calls == 1
    assert scheduler.report().accepted


def t_cavlc_run_before_tables_match_h264_reference_vlcs():
    assert get_run_before_table(4) == {
        "11": 0, "10": 1, "01": 2, "001": 3, "000": 4,
    }
    assert get_run_before_table(5) == {
        "11": 0, "10": 1, "011": 2, "010": 3, "001": 4, "000": 5,
    }
    assert get_run_before_table(6) == {
        "11": 0, "000": 1, "001": 2, "011": 3, "010": 4, "101": 5, "100": 6,
    }
    assert get_run_before_table(7)["00000000001"] == 14


def t_annex_b_iterator_streams_nals_and_removes_epb():
    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory) / "fixture.h264"
        fixture.write_bytes(
            b"\x00\x00\x00\x01\x67\x42\xc0"
            b"\x00\x00\x01\x65\x00\x00\x03\x01\x80"
        )
        units = list(iter_annex_b_nal_units(str(fixture), chunk_size=2))
    assert [unit.nal_unit_type for unit in units] == [NALUnitType.SPS, NALUnitType.SLICE_IDR]
    assert units[0].rbsp_byte == b"\x42\xc0"
    assert units[1].rbsp_byte == b"\x00\x00\x01\x80"


def t_idr_iterator_tracks_streaming_macroblock_offsets():
    class Reconstructor:
        @staticmethod
        def _parse_sps_from_nal(_nal):
            return SimpleNamespace(pic_width_in_mbs_minus1=1, pic_height_in_map_units_minus1=2)

        @staticmethod
        def _parse_pps_from_nal(_nal):
            return object()

    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory) / "fixture.h264"
        fixture.write_bytes(
            b"\x00\x00\x01\x67\x01"
            b"\x00\x00\x01\x68\x02"
            b"\x00\x00\x01\x65\x03"
            b"\x00\x00\x01\x41\x04"
            b"\x00\x00\x01\x65\x05"
        )
        slices = list(iter_idr_slices(str(fixture), Reconstructor()))
    assert [offset for _nal, _sps, _pps, offset in slices] == [0, 12]


def t_idr_trace_iterator_releases_each_slice_result_to_caller():
    class Reconstructor:
        @staticmethod
        def _parse_sps_from_nal(_nal):
            return SimpleNamespace(pic_width_in_mbs_minus1=0, pic_height_in_map_units_minus1=0)

        @staticmethod
        def _parse_pps_from_nal(_nal):
            return object()

    seen_offsets = []

    class Traceable:
        def extract_with_offsets(self, _nal, _sps, _pps, *, global_mb_idx):
            seen_offsets.append(global_mb_idx)
            return {"blocks": {(0, 0): [1] + [0] * 15}, "offsets": {(0, 0): {"nC": 0}}}

    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory) / "fixture.h264"
        fixture.write_bytes(
            b"\x00\x00\x01\x67\x01"
            b"\x00\x00\x01\x68\x02"
            b"\x00\x00\x01\x65\x03"
            b"\x00\x00\x01\x65\x04"
        )
        results = list(iter_idr_trace_results(str(fixture), Reconstructor(), traceable_factory=Traceable))
    assert [offset for _nal, _sps, _pps, offset, _result in results] == [0, 1]
    assert seen_offsets == [0, 1]


def t_idr_luma_analysis_uses_global_keys_without_retaining_other_slices():
    class Reconstructor:
        @staticmethod
        def _parse_sps_from_nal(_nal):
            return SimpleNamespace(pic_width_in_mbs_minus1=0, pic_height_in_map_units_minus1=0)

        @staticmethod
        def _parse_pps_from_nal(_nal):
            return object()

    class Traceable:
        def extract_with_offsets(self, _nal, _sps, _pps, *, global_mb_idx):
            return {
                "blocks": {(0, 0): [2] + [0] * 15, (0, 16): [1] * 16},
                "offsets": {(0, 0): {"nC": 3, "bit_length": 9}},
            }

    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory) / "fixture.h264"
        fixture.write_bytes(
            b"\x00\x00\x01\x67\x01"
            b"\x00\x00\x01\x68\x02"
            b"\x00\x00\x01\x65\x03"
            b"\x00\x00\x01\x65\x04"
        )
        records = list(iter_idr_luma_analysis(str(fixture), Reconstructor(), traceable_factory=Traceable))
    assert [record[0] for record in records] == [0, 1]
    assert records[1][1] == [(1, 0, [2] + [0] * 15)]
    assert records[1][2] == {(1, 0): 3}
    assert records[1][3] == {(1, 0): 9}
    assert set(records[1][4]) == {1}


def main():
    section("Phase 9 - Realtime CAVLC Controller")
    results = [
        run_test("scheduler_keeps_only_fresh_segments_under_pressure", t_scheduler_keeps_only_fresh_segments_under_pressure),
        run_test("scheduler_reuses_one_proof_per_epoch_and_reports_budget", t_scheduler_reuses_one_proof_per_epoch_and_reports_budget),
        run_test("cavlc_run_before_tables_match_h264_reference_vlcs", t_cavlc_run_before_tables_match_h264_reference_vlcs),
        run_test("annex_b_iterator_streams_nals_and_removes_epb", t_annex_b_iterator_streams_nals_and_removes_epb),
        run_test("idr_iterator_tracks_streaming_macroblock_offsets", t_idr_iterator_tracks_streaming_macroblock_offsets),
        run_test("idr_trace_iterator_releases_each_slice_result_to_caller", t_idr_trace_iterator_releases_each_slice_result_to_caller),
        run_test("idr_luma_analysis_uses_global_keys_without_retaining_other_slices", t_idr_luma_analysis_uses_global_keys_without_retaining_other_slices),
    ]
    sys.exit(summarise(results, "Phase 9"))


if __name__ == "__main__":
    main()
