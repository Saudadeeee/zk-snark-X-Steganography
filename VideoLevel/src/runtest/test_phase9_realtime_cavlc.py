"""Contracts for the realtime CAVLC segment controller."""

import os
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.bitstream import bitstream_ops
from src.bitstream.bitstream_io import BitstreamReader, BitstreamWriter
from src.bitstream.bitstream_ops import BitstreamPatcher
from src.bitstream.cavlc import (
    CAVLCDecoder,
    CAVLCEncoder,
    find_coeff_token_code,
    get_run_before_table,
)
from src.bitstream.h264 import NALUnitType, iter_annex_b_nal_units
from src.blind_sync import (
    iter_blind_sign_candidates_from_idr_analysis,
    select_blind_candidates_bounded,
    select_streaming_blind_positions,
)
from src.core.pipeline import (
    extract_selected_sign_bits_streaming,
    iter_idr_luma_analysis,
    iter_idr_slices,
    iter_idr_trace_results,
    patch_selected_sign_positions_streaming,
)
from src.core.stego import CAVLCSafetyFilter
from src.embedder import embed
from src.exceptions import InsufficientCapacityError
from src.realtime_cavlc import CAVLCRealtimeBudget, RealtimeCAVLCScheduler
from src.runtest._helpers import run_test, section, summarise


def t_scheduler_keeps_only_fresh_segments_under_pressure():
    scheduler = RealtimeCAVLCScheduler(CAVLCRealtimeBudget(fps=30.0, max_queue_segments=2), lambda _epoch: b"proof", lambda segment, _proof: segment)
    scheduler.submit(b"old", epoch=1)
    scheduler.submit(b"current", epoch=1)
    scheduler.submit(b"fresh", epoch=1)
    assert scheduler.dropped_segments == 1
    assert scheduler.process_next().output == b"current"
    assert scheduler.process_next().output == b"fresh"


def t_scheduler_bounds_queue_by_bytes_and_rejects_oversized_segment():
    scheduler = RealtimeCAVLCScheduler(
        CAVLCRealtimeBudget(fps=30.0, max_queue_segments=4, max_queued_bytes=5, max_segment_bytes=4),
        lambda _epoch: b"proof",
        lambda segment, _proof: segment,
    )
    scheduler.submit(b"1234", epoch=1)
    scheduler.submit(b"ab", epoch=1)
    assert scheduler.dropped_segments == 1
    assert scheduler.queued_bytes == 2
    try:
        scheduler.submit(b"12345", epoch=1)
    except ValueError as exc:
        assert "maximum" in str(exc)
    else:
        raise AssertionError("oversized segment must be rejected")
    try:
        scheduler.submit(bytearray(b"mut"), epoch=1)
    except TypeError as exc:
        assert "immutable bytes" in str(exc)
    else:
        raise AssertionError("mutable segment input must not bypass the byte bound")
    assert scheduler.queued_bytes == 2
    assert scheduler.process_next().output == b"ab"
    assert scheduler.queued_bytes == 0


def t_scheduler_rejects_epoch_regression():
    scheduler = RealtimeCAVLCScheduler(CAVLCRealtimeBudget(), lambda _epoch: b"p", lambda data, _p: data)
    scheduler.submit(b"new", epoch=3)
    try:
        scheduler.submit(b"old", epoch=2)
    except ValueError as exc:
        assert "monotonic" in str(exc)
    else:
        raise AssertionError("scheduler must reject an epoch regression")


def t_realtime_budget_rejects_non_finite_values():
    for kwargs in ({"fps": float("nan")}, {"fps": float("inf")}, {"max_p95_latency_s": float("nan")}):
        try:
            CAVLCRealtimeBudget(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid realtime budget accepted: {kwargs}")


def t_scheduler_reuses_one_proof_when_consumers_race():
    calls = 0
    calls_lock = threading.Lock()

    def proof(_epoch):
        nonlocal calls
        with calls_lock:
            calls += 1
        return b"proof"

    scheduler = RealtimeCAVLCScheduler(CAVLCRealtimeBudget(), proof, lambda data, _proof: data)
    scheduler.submit(b"one", epoch=4)
    scheduler.submit(b"two", epoch=4)
    results = []
    workers = [threading.Thread(target=lambda: results.append(scheduler.process_next())) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=2)
        assert not worker.is_alive()
    assert calls == 1
    assert len(results) == 2 and all(result is not None for result in results)
    assert scheduler.queued_bytes == 0


def t_scheduler_bounds_epoch_cache_and_latency_sample_history():
    proof_calls = []
    scheduler = RealtimeCAVLCScheduler(
        CAVLCRealtimeBudget(max_cached_epochs=2, max_latency_samples=2),
        lambda epoch: proof_calls.append(epoch) or b"proof",
        lambda data, _proof: data,
    )
    for epoch in (1, 1, 2, 3, 3):
        scheduler.submit(b"x", epoch=epoch)
        assert scheduler.process_next() is not None
    report = scheduler.report()
    assert proof_calls == [1, 2, 3]
    assert report.processed_segments == 5
    assert len(scheduler._latencies) == 2


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


def t_cavlc_level_coding_round_trips_both_trailing_one_branches():
    """The first non-trailing level must round-trip for both H.264 branches."""
    for n_c, coeffs in (
        (0, [2, 0, 1] + [0] * 13),
        (0, [-2, 0, 1] + [0] * 13),
        (0, [4, 1, 1, 1] + [0] * 12),
        (0, [-4, 1, 1, 1] + [0] * 12),
        (8, [2, 0, 1] + [0] * 13),
        (8, [4, 1, 1, 1] + [0] * 12),
        (8, [0] * 16),
        (0, [2] * 11 + [0] * 5),
        (0, [2] * 8 + [1, 1, 1] + [0] * 5),
    ):
        writer = BitstreamWriter()
        CAVLCEncoder(writer).encode_block_cavlc(coeffs, nC=n_c)
        decoded = CAVLCDecoder(BitstreamReader(writer.get_bytes())).decode_block_cavlc(nC=n_c)
        assert decoded.levels == coeffs


def t_cavlc_flc_table_9_5e_literals_and_invalid_tokens_are_fail_closed():
    assert find_coeff_token_code(0, 0, nC=8) == "000011"
    assert find_coeff_token_code(1, 0, nC=8) == "000000"
    assert find_coeff_token_code(1, 1, nC=8) == "000001"
    assert find_coeff_token_code(16, 0, nC=8) == "111100"
    assert find_coeff_token_code(16, 3, nC=8) == "111111"
    try:
        CAVLCDecoder(BitstreamReader(bytes([0b00001000])))._decode_coeff_token(nC=8)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid FLC6 coeff_token must not decode as an empty block")


def t_patcher_keeps_decoded_trailing_one_count_on_standard_round_trip():
    """A standard exact round-trip must not discard a trailing-one sign flip."""
    original_decoder = bitstream_ops.CAVLCDecoder

    class Decoder:
        def __init__(self, reader):
            self.reader = reader

        def _decode_coeff_token(self, _n_c):
            self.reader.pos = 2
            return 1, 1

        def decode_block_cavlc(self, _n_c, max_num_coeff=16):
            self.reader.pos = 3
            return SimpleNamespace(levels=[1] + [0] * (max_num_coeff - 1), trailing_ones=1)

    bitstream_ops.CAVLCDecoder = Decoder
    try:
        patcher = BitstreamPatcher()
        patcher._encode_coefficients_to_bits = lambda *_args, **_kwargs: [0, 1, 0]
        nal = SimpleNamespace(
            forbidden_zero_bit=0,
            nal_ref_idc=3,
            nal_unit_type=NALUnitType.SLICE_IDR,
            rbsp_byte=bytes.fromhex("4180"),
            start_pos=0,
            start_code_size=4,
        )
        patched = patcher.patch_slice(
            nal,
            [(0, 0, [-1] + [0] * 15)],
            sps=SimpleNamespace(),
            pps=SimpleNamespace(),
            pre_computed_offsets={(0, 0): {
                "start_bit": 0, "end_bit": 3, "bit_length": 3, "nC": 0,
                "max_num_coeff": 16,
            }},
            pre_computed_blocks={(0, 0): [1] + [0] * 15},
        )
    finally:
        bitstream_ops.CAVLCDecoder = original_decoder
    assert patched.applied_block_keys == [(0, 0)]
    assert patched.rbsp_byte[0] == 0x61


def t_streaming_sign_patcher_writes_only_verified_idr_patch():
    class Reconstructor:
        @staticmethod
        def _parse_sps_from_nal(_nal):
            return SimpleNamespace(pic_width_in_mbs_minus1=0, pic_height_in_map_units_minus1=0)

        @staticmethod
        def _parse_pps_from_nal(_nal):
            return SimpleNamespace()

        @staticmethod
        def _add_emulation_prevention(rbsp):
            return rbsp

    class Traceable:
        def extract_with_offsets(self, _nal, _sps, _pps, global_mb_idx):
            assert global_mb_idx == 0
            return {
                "blocks": {(0, 0): [0] * 7 + [1] + [0] * 8},
                "offsets": {(0, 0): {"start_bit": 0, "end_bit": 3, "bit_length": 3, "nC": 0}},
            }

    class Patcher:
        def patch_slice(self, nal, modifications, **_kwargs):
            assert modifications == [(0, 0, [0] * 7 + [-1] + [0] * 8)]
            return SimpleNamespace(
                forbidden_zero_bit=nal.forbidden_zero_bit,
                nal_ref_idc=nal.nal_ref_idc,
                nal_unit_type=nal.nal_unit_type,
                rbsp_byte=b"\xaa",
                start_code_size=nal.start_code_size,
                applied_block_keys=[(0, 0)],
            )

    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "cover.h264"
        output = Path(directory) / "stego.h264"
        source.write_bytes(
            b"\x00\x00\x00\x01\x67\x42"
            b"\x00\x00\x00\x01\x68\xce"
            b"\x00\x00\x00\x01\x65\x41\x80"
        )
        decoder_inputs = []

        def decoder_validator(path):
            decoder_inputs.append((path, path.exists()))

        stats = patch_selected_sign_positions_streaming(
            str(source),
            str(output),
            {(0, 0, ~7): 1},
            reconstructor=Reconstructor(),
            traceable_factory=Traceable,
            patcher_factory=Patcher,
            decoder_validator=decoder_validator,
        )
        assert output.read_bytes().endswith(b"\x00\x00\x00\x01\x65\xaa")
        assert len(decoder_inputs) == 1
        assert decoder_inputs[0][0] != output
        assert decoder_inputs[0][1]
    assert stats == {"idr_slices": 1, "selected_positions": 1, "applied_positions": 1}


def t_streaming_sign_extractor_preserves_requested_schedule_order():
    class Reconstructor:
        @staticmethod
        def _parse_sps_from_nal(_nal):
            return SimpleNamespace(pic_width_in_mbs_minus1=0, pic_height_in_map_units_minus1=0)

        @staticmethod
        def _parse_pps_from_nal(_nal):
            return SimpleNamespace()

    class Traceable:
        def extract_with_offsets(self, _nal, _sps, _pps, global_mb_idx):
            return {
                "blocks": {
                    (0, 0): [0] * 7 + [-1] + [0] * 8,
                    (0, 1): [0] * 8 + [1] + [0] * 7,
                },
                "offsets": {
                    (0, 0): {"nC": 0, "bit_length": 3},
                    (0, 1): {"nC": 0, "bit_length": 3},
                },
            }

    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "stego.h264"
        source.write_bytes(
            b"\x00\x00\x00\x01\x67\x42"
            b"\x00\x00\x00\x01\x68\xce"
            b"\x00\x00\x00\x01\x65\x41\x80"
        )
        extracted = extract_selected_sign_bits_streaming(
            str(source),
            [(0, 1, ~8), (0, 0, ~7)],
            reconstructor=Reconstructor(),
            traceable_factory=Traceable,
        )
    assert extracted == bytes([0b01000000])


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


def t_streaming_blind_candidates_are_filtered_per_idr_record():
    class SafetyFilter:
        @staticmethod
        def get_safe_positions(*_args, **_kwargs):
            return [(5, 2, ~7), (5, 2, 3)]

    coefficients = [(5, 2, [0] * 7 + [1] + [0] * 8)]
    frame_data = {0: ({(5, 2): {"start_bit": 0}}, {(5, 2): [0] * 7 + [1] + [0] * 8}, b"")}
    records = [(0, coefficients, {(5, 2): 0}, {(5, 2): 1}, frame_data)]
    assert list(iter_blind_sign_candidates_from_idr_analysis(records, safety_filter=SafetyFilter())) == [(5, 2, ~7)]


def t_streaming_blind_candidates_prefer_sign_only_gate():
    class SafetyFilter:
        @staticmethod
        def get_safe_sign_positions(*_args, **_kwargs):
            return [(5, 2, ~7)]

        @staticmethod
        def get_safe_positions(*_args, **_kwargs):
            raise AssertionError("generic LSB gate must not run in sign-only mode")

    records = [(0, [], {}, {}, {})]
    assert list(iter_blind_sign_candidates_from_idr_analysis(records, safety_filter=SafetyFilter())) == [(5, 2, ~7)]


def t_streaming_blind_candidates_keep_one_sign_per_block():
    class SafetyFilter:
        @staticmethod
        def get_safe_sign_positions(*_args, **_kwargs):
            return [(5, 2, ~7), (5, 2, ~8), (6, 2, ~9)]

    records = [(0, [], {}, {}, {})]
    assert list(iter_blind_sign_candidates_from_idr_analysis(records, safety_filter=SafetyFilter())) == [
        (5, 2, ~7),
        (6, 2, ~9),
    ]


def t_streaming_blind_candidates_use_validated_filter_for_real_cavlc_filter():
    class SafetyFilter(CAVLCSafetyFilter):
        def get_safe_sign_positions(self, *_args, **_kwargs):
            raise AssertionError("fast sign scan omits patchability validation")

        def get_safe_positions(self, *_args, **_kwargs):
            self._lazy_patchability_cache[(5, 2)] = (0, None, None)
            return [(5, 2, ~7), (5, 2, ~8), (6, 2, 3)]

    records = [(0, [], {}, {}, {})]
    safety_filter = SafetyFilter()
    assert list(iter_blind_sign_candidates_from_idr_analysis(records, safety_filter=safety_filter)) == [(5, 2, ~7)]
    assert safety_filter._lazy_patchability_cache == {}


def t_bitstream_patcher_exposes_lazy_patchability_contract():
    patcher = BitstreamPatcher()
    assert callable(patcher.validate_block_patchability)
    assert callable(patcher.get_unpatchable_blocks)


def t_bounded_blind_selector_matches_full_hmac_ordering():
    candidates = [(5, 2, ~7), (1, 4, ~8), (3, 1, ~9), (9, 0, ~10)]
    ordering_key = b"k" * 32
    selected = select_blind_candidates_bounded(iter(candidates), ordering_key, required_bits=2)
    import hashlib
    import hmac
    expected = sorted(
        candidates,
        key=lambda pos: hmac.new(ordering_key, f"{pos[0]}:{pos[1]}:{pos[2]}".encode("ascii"), hashlib.sha256).digest(),
    )[:2]
    assert selected == expected


def t_streaming_blind_positions_use_a_stable_key_domain():
    records = [
        (0, [], {}, {}, {}),
    ]

    class SafetyFilter:
        @staticmethod
        def get_safe_sign_positions(*_args, **_kwargs):
            return [(5, 2, ~7), (1, 4, ~8), (3, 1, ~9)]

    selected = select_streaming_blind_positions(
        records,
        secret_key=b"s" * 32,
        required_bits=2,
        safety_filter=SafetyFilter(),
    )
    expected = select_blind_candidates_bounded(
        [(5, 2, ~7), (1, 4, ~8), (3, 1, ~9)],
        b"blind-stream-v2\x00" + b"s" * 32,
        required_bits=2,
    )
    assert selected == expected


def t_embed_forwards_analysis_cache_options_to_resolver():
    analysis = ([], {}, {}, {}, {}, [])

    class ProofBridge:
        def generate_proof_for_payload(self, _message, _key):
            return {}, {}

        def proof_to_bytes(self, _proof):
            return bytes(129)

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        video = root / "cover.h264"
        video.write_bytes(b"test")
        circuits = root / "circuits"
        circuits.mkdir()
        for cache_enabled in (False, True):
            with (
                patch("src.embedder.analyze_stream_profile", return_value=SimpleNamespace(
                    is_all_intra=True, inferred_gop_class="all_intra",
                )),
                patch("src.embedder._get_bridge", return_value=ProofBridge()),
                patch("src.embedder.load_or_build_video_analysis", return_value=analysis) as loader,
            ):
                try:
                    embed(
                        video_path=str(video), message=b"x", output_path=str(root / "stego.h264"),
                        circuits_dir=str(circuits), secret_key=bytes(32), precomputed_positions=[],
                        use_analysis_cache=cache_enabled,
                    )
                except InsufficientCapacityError:
                    pass
                else:
                    raise AssertionError("empty test analysis must fail closed for payload capacity")
                loader.assert_called_once_with(
                    str(video), use_cache=cache_enabled, force_refresh=False, cache_dir=None,
                )


def main():
    section("Phase 9 - Realtime CAVLC Controller")
    results = [
        run_test("scheduler_keeps_only_fresh_segments_under_pressure", t_scheduler_keeps_only_fresh_segments_under_pressure),
        run_test("scheduler_bounds_queue_by_bytes_and_rejects_oversized_segment", t_scheduler_bounds_queue_by_bytes_and_rejects_oversized_segment),
        run_test("scheduler_rejects_epoch_regression", t_scheduler_rejects_epoch_regression),
        run_test("realtime_budget_rejects_non_finite_values", t_realtime_budget_rejects_non_finite_values),
        run_test("scheduler_reuses_one_proof_when_consumers_race", t_scheduler_reuses_one_proof_when_consumers_race),
        run_test("scheduler_bounds_epoch_cache_and_latency_sample_history", t_scheduler_bounds_epoch_cache_and_latency_sample_history),
        run_test("scheduler_reuses_one_proof_per_epoch_and_reports_budget", t_scheduler_reuses_one_proof_per_epoch_and_reports_budget),
        run_test("embed_forwards_analysis_cache_options_to_resolver", t_embed_forwards_analysis_cache_options_to_resolver),
        run_test("cavlc_run_before_tables_match_h264_reference_vlcs", t_cavlc_run_before_tables_match_h264_reference_vlcs),
        run_test("cavlc_level_coding_round_trips_both_trailing_one_branches", t_cavlc_level_coding_round_trips_both_trailing_one_branches),
        run_test("cavlc_flc_table_9_5e_literals_and_invalid_tokens_are_fail_closed", t_cavlc_flc_table_9_5e_literals_and_invalid_tokens_are_fail_closed),
        run_test("patcher_keeps_decoded_trailing_one_count_on_standard_round_trip", t_patcher_keeps_decoded_trailing_one_count_on_standard_round_trip),
        run_test("streaming_sign_patcher_writes_only_verified_idr_patch", t_streaming_sign_patcher_writes_only_verified_idr_patch),
        run_test("streaming_sign_extractor_preserves_requested_schedule_order", t_streaming_sign_extractor_preserves_requested_schedule_order),
        run_test("annex_b_iterator_streams_nals_and_removes_epb", t_annex_b_iterator_streams_nals_and_removes_epb),
        run_test("idr_iterator_tracks_streaming_macroblock_offsets", t_idr_iterator_tracks_streaming_macroblock_offsets),
        run_test("idr_trace_iterator_releases_each_slice_result_to_caller", t_idr_trace_iterator_releases_each_slice_result_to_caller),
        run_test("idr_luma_analysis_uses_global_keys_without_retaining_other_slices", t_idr_luma_analysis_uses_global_keys_without_retaining_other_slices),
        run_test("streaming_blind_candidates_are_filtered_per_idr_record", t_streaming_blind_candidates_are_filtered_per_idr_record),
        run_test("streaming_blind_candidates_prefer_sign_only_gate", t_streaming_blind_candidates_prefer_sign_only_gate),
        run_test("streaming_blind_candidates_keep_one_sign_per_block", t_streaming_blind_candidates_keep_one_sign_per_block),
        run_test("streaming_blind_candidates_use_validated_filter_for_real_cavlc_filter", t_streaming_blind_candidates_use_validated_filter_for_real_cavlc_filter),
        run_test("bitstream_patcher_exposes_lazy_patchability_contract", t_bitstream_patcher_exposes_lazy_patchability_contract),
        run_test("bounded_blind_selector_matches_full_hmac_ordering", t_bounded_blind_selector_matches_full_hmac_ordering),
        run_test("streaming_blind_positions_use_a_stable_key_domain", t_streaming_blind_positions_use_a_stable_key_domain),
    ]
    sys.exit(summarise(results, "Phase 9"))


if __name__ == "__main__":
    main()
