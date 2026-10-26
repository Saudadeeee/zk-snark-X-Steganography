"""Robustness of the CABAC parser and transport against crafted or corrupted input.

Pinned decoder bounds (``headers.MAX_*``) reject oversized SPS geometry before
any slice is walked, a slice never decodes more macroblocks than its picture
holds, and every fault a malformed slice can trigger in the decoder or in the
carrier-position packing reaches the pipeline as ``ValueError`` (the rejection
path of ``video_pipeline.verify_video_proof``), never as another exception.
"""

from __future__ import annotations

import random
import struct
import time
from types import SimpleNamespace

import pytest

from src.bitstream.cabac import (
    AnnexBUnit, BitWriter, CabacError, UnsupportedStream, collect_parameter_sets, decode_slice,
    encode_slice, join_annexb, split_annexb,
)
from src.bitstream.cabac import headers
from src.bitstream.cabac.headers import (
    MAX_HEIGHT_MBS, MAX_MBS_PER_PICTURE, MAX_NAL_BYTES, MAX_WIDTH_MBS, NAL_SPS, escape, parse_sps,
)
from src.runtest.cabac_media import cabac_clip
from src.transport.cabac_sync import (
    MAX_TRANSPORT_MBS_PER_PICTURE, CabacMagnitudeContract, _analyze, _extract_segment,
    _reject_malformed, inspect_cabac_segment, segment_capacity_bits,
)

KEY = bytes(range(32))
CONTRACT = CabacMagnitudeContract()
POLICY = "all-intra"
CLIP = "foreman_cif_cabac_main_g1_30f.h264"  # 22 x 18 MBs, one IDR slice per picture
FUZZ_ITERATIONS = 200


# --- synthetic SPS -----------------------------------------------------------------

def _ue(writer: BitWriter, value: int) -> None:
    code = value + 1
    length = code.bit_length()
    writer.write_bits(0, length - 1)
    writer.write_bits(code, length)


def _sps_rbsp(width_mbs: int, height_mbs: int, *, log2_max_frame_num_minus4: int = 0,
              poc_type: int = 2, log2_max_poc_lsb_minus4: int = 0, poc_cycle: int = 0) -> bytes:
    """Main profile SPS RBSP declaring ``width_mbs x height_mbs`` progressive macroblocks."""
    writer = BitWriter()
    writer.write_bits(77, 8)  # profile_idc Main
    writer.write_bits(0, 8)  # constraint_set flags
    writer.write_bits(62, 8)  # level_idc 6.2
    _ue(writer, 0)  # seq_parameter_set_id
    _ue(writer, log2_max_frame_num_minus4)
    _ue(writer, poc_type)
    if poc_type == 0:
        _ue(writer, log2_max_poc_lsb_minus4)
    elif poc_type == 1:
        writer.write(0)  # delta_pic_order_always_zero_flag
        _ue(writer, 0)  # offset_for_non_ref_pic = se(0)
        _ue(writer, 0)  # offset_for_top_to_bottom_field = se(0)
        _ue(writer, poc_cycle)
        for _ in range(min(poc_cycle, 300)):
            _ue(writer, 0)
    _ue(writer, 1)  # max_num_ref_frames
    writer.write(0)  # gaps_in_frame_num_value_allowed_flag
    _ue(writer, width_mbs - 1)
    _ue(writer, height_mbs - 1)
    writer.write(1)  # frame_mbs_only_flag
    writer.write(1)  # direct_8x8_inference_flag
    writer.write(0)  # frame_cropping_flag
    writer.write(0)  # vui_parameters_present_flag
    writer.write(1)  # rbsp_stop_one_bit
    while not writer.aligned:
        writer.write(0)
    return writer.to_bytes()


@pytest.mark.parametrize("width_mbs,height_mbs", [
    (MAX_WIDTH_MBS + 1, 1),
    (1, MAX_HEIGHT_MBS + 1),
    (MAX_WIDTH_MBS, MAX_HEIGHT_MBS),  # 262 144 > MaxFS of Level 6.2
    (2 ** 16, 2 ** 16),
    (2 ** 32 - 1, 2 ** 32 - 1),  # the largest ue(v) a 32-bit Exp-Golomb code can carry
])
def test_oversized_sps_geometry_is_rejected(width_mbs, height_mbs) -> None:
    with pytest.raises(ValueError, match="pinned limit") as info:
        parse_sps(_sps_rbsp(width_mbs, height_mbs))
    assert not isinstance(info.value, UnsupportedStream)


@pytest.mark.parametrize("width_mbs,height_mbs", [(1, 1), (22, 18), (120, 68), (MAX_WIDTH_MBS, 272)])
def test_sps_geometry_within_the_caps_is_accepted(width_mbs, height_mbs) -> None:
    info = parse_sps(_sps_rbsp(width_mbs, height_mbs))
    assert (info.width_mbs, info.height_mbs) == (width_mbs, height_mbs)
    assert info.mbs_per_picture <= MAX_MBS_PER_PICTURE


def test_sps_fields_that_size_later_reads_are_range_checked() -> None:
    with pytest.raises(ValueError, match="log2_max_frame_num_minus4"):
        parse_sps(_sps_rbsp(22, 18, log2_max_frame_num_minus4=13))
    with pytest.raises(ValueError, match="log2_max_pic_order_cnt_lsb_minus4"):
        parse_sps(_sps_rbsp(22, 18, poc_type=0, log2_max_poc_lsb_minus4=2 ** 20))
    with pytest.raises(ValueError, match="num_ref_frames_in_pic_order_cnt_cycle"):
        parse_sps(_sps_rbsp(22, 18, poc_type=1, poc_cycle=2 ** 31))
    largest = parse_sps(_sps_rbsp(22, 18, log2_max_frame_num_minus4=12, poc_type=0, log2_max_poc_lsb_minus4=12))
    assert (largest.log2_max_frame_num, largest.log2_max_poc_lsb) == (16, 16)
    assert parse_sps(_sps_rbsp(22, 18, poc_type=1, poc_cycle=255)).poc_type == 1


# --- real clip, one canonical IDR picture --------------------------------------------

@pytest.fixture(scope="module")
def base():
    """SPS, PPS (and SEI) of the clip plus its first IDR slice in canonical form."""
    units = split_annexb(cabac_clip(CLIP).read_bytes())
    sps, pps = collect_parameter_sets(units)
    first = next(index for index, unit in enumerate(units) if unit.nal_type == 5)
    idr = AnnexBUnit(units[first].prefix, encode_slice(decode_slice(units[first].nal, sps, pps)))
    kept = units[:first] + [idr]
    data = join_annexb(kept)
    assert inspect_cabac_segment(data, POLICY).coded_slices == 1
    return SimpleNamespace(units=kept, idr=idr, sps=sps, pps=pps, data=data)


def _with_sps(base, sps_rbsp: bytes) -> bytes:
    units = [
        AnnexBUnit(unit.prefix, bytes([unit.nal[0]]) + escape(sps_rbsp)) if unit.nal_type == NAL_SPS else unit
        for unit in base.units
    ]
    return join_annexb(units)


def _with_idr(base, nal: bytes) -> bytes:
    return join_annexb(base.units[:-1] + [AnnexBUnit(base.idr.prefix, nal)])


def _transport_calls(data: bytes, tmp_path):
    path = tmp_path / "segment.h264"
    path.write_bytes(data)
    return {
        "inspect_cabac_segment": lambda: inspect_cabac_segment(data, POLICY),
        "_analyze": lambda: _analyze(data, CONTRACT, POLICY),
        "_extract_segment": lambda: _extract_segment(data, KEY, CONTRACT, POLICY),
        "segment_capacity_bits": lambda: segment_capacity_bits(path, KEY, CONTRACT, POLICY),
    }


def test_oversized_geometry_is_rejected_through_the_transport(base, tmp_path) -> None:
    data = _with_sps(base, _sps_rbsp(2 ** 20, 2 ** 20))
    for name, call in _transport_calls(data, tmp_path).items():
        with pytest.raises(ValueError, match="pinned limit"):
            call()


def test_transport_pins_mbs_per_picture_below_2_24(base, monkeypatch) -> None:
    """The transport's own pin holds even if the parser caps were ever relaxed."""
    assert MAX_TRANSPORT_MBS_PER_PICTURE == 1 << 24 > MAX_MBS_PER_PICTURE
    monkeypatch.setattr(headers, "MAX_WIDTH_MBS", 1 << 20)
    monkeypatch.setattr(headers, "MAX_HEIGHT_MBS", 1 << 20)
    monkeypatch.setattr(headers, "MAX_MBS_PER_PICTURE", 1 << 40)
    data = _with_sps(base, _sps_rbsp(4097, 4097))  # 4097^2 > 2^24
    with pytest.raises(ValueError, match="transport limit"):
        inspect_cabac_segment(data, POLICY)
    with pytest.raises(ValueError, match="transport limit"):
        _analyze(data, CONTRACT, POLICY)


def test_nal_units_above_the_pinned_size_are_rejected(base, monkeypatch) -> None:
    assert MAX_NAL_BYTES == 64 * 1024 * 1024
    monkeypatch.setattr(headers, "MAX_NAL_BYTES", len(base.idr.nal) - 1)
    with pytest.raises(ValueError, match="exceeds the pinned limit"):
        split_annexb(base.data)
    with pytest.raises(ValueError, match="exceeds the pinned limit"):
        decode_slice(base.idr.nal, base.sps, base.pps)
    with pytest.raises(ValueError, match="exceeds the pinned limit"):
        inspect_cabac_segment(base.data, POLICY)


def test_slice_decoding_stops_at_the_picture_size(base) -> None:
    """A picture of 22 x 9 MBs: the 396-MB slice decodes 198 MBs, then stops."""
    data = _with_sps(base, _sps_rbsp(22, 9))
    units = split_annexb(data)
    sps, pps = collect_parameter_sets(units)
    with pytest.raises(CabacError, match="past the end of the picture"):
        decode_slice(base.idr.nal, sps, pps)
    with pytest.raises(ValueError, match="past the end of the picture") as info:
        _analyze(data, CONTRACT, POLICY)
    assert type(info.value) is ValueError  # CabacError converted at the transport boundary


def test_encoder_refuses_slices_with_invalid_geometry(base) -> None:
    decoded = decode_slice(base.idr.nal, base.sps, base.pps)
    oversized = decoded.copy()
    oversized.width_mbs, oversized.mbs_per_picture = 2 ** 20, 2 ** 40
    with pytest.raises(ValueError, match="pinned limit"):
        encode_slice(oversized)
    ragged = decoded.copy()
    ragged.mbs_per_picture = 397
    with pytest.raises(ValueError, match="whole number"):
        encode_slice(ragged)


# --- truncated and garbage slice payloads ----------------------------------------------

def _corruptions(nal: bytes):
    rng = random.Random(1)
    filler = bytes(rng.randrange(256) for _ in range(len(nal)))
    yield "nal header only", nal[:1]
    yield "two bytes", nal[:2]
    yield "slice header only", nal[:4]
    yield "quarter", nal[: len(nal) // 4]
    yield "half", nal[: len(nal) // 2]
    yield "last byte missing", nal[:-1]
    yield "zeros", nal[:1] + bytes(len(nal) - 1)
    yield "ones", nal[:1] + b"\xff" * (len(nal) - 1)
    yield "random", nal[:1] + filler[1:]
    yield "random after slice header", nal[:4] + filler[4:]
    yield "random tail", nal[: len(nal) // 2] + filler[len(nal) // 2:]


def _value_error_or_result(label: str, name: str, call) -> bool:
    """Run ``call``; True if it returned, False on ``ValueError``; fail on any other exception."""
    try:
        call()
    except ValueError as error:
        assert not isinstance(error, CabacError), f"{label}: {name} leaked CabacError: {error}"
        return False
    except Exception as error:  # noqa: BLE001 - any other exception is the failure under test
        pytest.fail(f"{label}: {name} raised {type(error).__name__}: {error}")
    return True


def test_truncated_and_garbage_slices_give_value_error(base, tmp_path) -> None:
    """Analysis may legitimately decode a short slice out of garbage; extraction must reject."""
    for label, nal in _corruptions(base.idr.nal):
        calls = _transport_calls(_with_idr(base, nal), tmp_path)
        passed = [
            name for name in ("inspect_cabac_segment", "_analyze", "segment_capacity_bits")
            if _value_error_or_result(label, name, calls[name])
        ]
        with pytest.raises(ValueError) as info:
            calls["_extract_segment"]()
        assert not isinstance(info.value, CabacError), f"{label}: _extract_segment leaked CabacError"
        print(f"{label}: passed {passed or 'nothing'}; extract rejected: {str(info.value)[:60]}")


# --- fuzz: random byte flips in the IDR NAL --------------------------------------------

def test_random_byte_flips_in_the_idr_nal_only_ever_raise_value_error(base) -> None:
    rng = random.Random(20261026)
    original = base.idr.nal
    outcomes = {"inspect": 0, "analyze": 0, "extract": 0, "decoded": 0}
    start = time.perf_counter()
    for iteration in range(FUZZ_ITERATIONS):
        mutated = bytearray(original)
        for _ in range(rng.choice((1, 1, 1, 2, 3))):
            mutated[rng.randrange(len(mutated))] ^= 1 << rng.randrange(8)
        if rng.random() < 0.1:
            del mutated[rng.randrange(1, len(mutated)):]
        data = _with_idr(base, bytes(mutated))
        stage = "inspect"
        try:
            inspect_cabac_segment(data, POLICY)
            stage = "analyze"
            segment = _analyze(data, CONTRACT, POLICY)
            stage = "extract"
            _extract_segment(data, KEY, CONTRACT, POLICY, segment)
        except ValueError as error:
            assert not isinstance(error, CabacError), f"iteration {iteration}: CabacError leaked: {error}"
            outcomes[stage] += 1
        except Exception as error:  # noqa: BLE001 - any other exception is the failure under test
            pytest.fail(f"iteration {iteration} ({stage}): {type(error).__name__}: {error}")
        else:
            outcomes["decoded"] += 1
    elapsed = time.perf_counter() - start
    assert sum(outcomes.values()) == FUZZ_ITERATIONS
    assert outcomes["analyze"] > 0  # the slice decoder itself was exercised, not only the framing checks
    print(f"{FUZZ_ITERATIONS} mutations in {elapsed:.1f}s: rejected at {outcomes}")


# --- the conversion itself ----------------------------------------------------------------

@pytest.mark.parametrize("error", [
    struct.error("pack"), IndexError("index"), KeyError("key"), OverflowError("overflow"),
    ZeroDivisionError("zero"), CabacError("cabac"),
])
def test_parser_faults_become_value_errors(error) -> None:
    @_reject_malformed
    def fault():
        raise error

    with pytest.raises(ValueError, match="malformed CABAC stream") as info:
        fault()
    assert type(info.value) is ValueError and info.value.__cause__ is error


def test_other_errors_pass_through_the_boundary_unchanged() -> None:
    @_reject_malformed
    def unsupported():
        raise UnsupportedStream("feature")

    @_reject_malformed
    def self_check():
        raise RuntimeError("self-check")

    with pytest.raises(UnsupportedStream, match="feature"):
        unsupported()
    with pytest.raises(RuntimeError, match="self-check"):
        self_check()
