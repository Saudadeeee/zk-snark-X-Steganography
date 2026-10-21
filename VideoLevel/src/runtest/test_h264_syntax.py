"""H.264 syntax parsing: chroma CBP flags, mb_type mapping, P-slice stream, bit reader, NAL parser hot path."""

# --- from test_h264_chroma_cbp_flags.py
import pytest

from src.bitstream.bitstream_io import BitstreamReader
from src.bitstream.h264 import MacroblockData, MacroblockParser


@pytest.mark.parametrize(
    ("coded_block_pattern_chroma", "dc_present", "ac_present"),
    [
        (0, False, False),
        (1, True, False),
        (2, True, True),
        (3, True, True),
    ],
)
def test_chroma_cbp_value_maps_to_dc_and_ac_presence(
    coded_block_pattern_chroma, dc_present, ac_present
):
    macroblock = MacroblockData(mb_type=0, mb_type_enum=None)
    macroblock.coded_block_pattern = coded_block_pattern_chroma << 4

    parser = MacroblockParser(BitstreamReader(b""), slice_type=2)
    parser._decode_cbp_to_blocks(macroblock)

    assert macroblock.chroma_dc_present is dc_present
    assert macroblock.chroma_ac_present is ac_present


# --- from test_h264_mb_type_mapping.py
from src.bitstream.bitstream_io import BitstreamReader, BitstreamWriter
from src.bitstream.h264 import (
    MacroblockParser,
    MBType,
    NALUnit,
    NALUnitType,
    PPSData,
    SliceHeaderParser,
    SPSData,
)


def _p_slice_header(override: bool, override_count: int = 0) -> tuple[NALUnit, SPSData, PPSData]:
    writer = BitstreamWriter()
    writer.write_ue(0)  # first_mb_in_slice
    writer.write_ue(0)  # P slice
    writer.write_ue(0)  # pic_parameter_set_id
    writer.write_bits(4, 0)  # frame_num
    writer.write_bits(1, int(override))
    if override:
        writer.write_ue(override_count)
    writer.write_bits(1, 0)  # ref_pic_list_modification_flag_l0
    writer.write_bits(1, 0)  # adaptive_ref_pic_marking_mode_flag
    writer.write_se(0)  # slice_qp_delta
    writer.write_ue(1)  # disable_deblocking_filter_idc
    nal = NALUnit(0, 3, NALUnitType.SLICE_NON_IDR, writer.get_bytes(), 0, 0)
    sps = SPSData(pic_order_cnt_type=2)
    pps = PPSData(num_ref_idx_l0_default_active_minus1=2)
    return nal, sps, pps


def test_truncated_exp_golomb_with_max_one_uses_inverted_single_bit() -> None:
    parser = MacroblockParser(BitstreamReader(bytes([0b0100_0000])), slice_type=0)

    assert parser._read_te(1) == 1
    assert parser._read_te(1) == 0
    assert parser.reader.position == 2


def test_truncated_exp_golomb_with_larger_max_uses_ue() -> None:
    parser = MacroblockParser(BitstreamReader(bytes([0b0100_0000])), slice_type=0)

    assert parser._read_te(2) == 1
    assert parser.reader.position == 3


def test_truncated_exp_golomb_with_zero_max_consumes_no_bits() -> None:
    parser = MacroblockParser(BitstreamReader(bytes([0b1111_1111])), slice_type=0)

    assert parser._read_te(0) == 0
    assert parser.reader.position == 0


def test_p_slice_partition_types_are_not_misclassified_as_i16x16() -> None:
    parser = MacroblockParser(BitstreamReader(b""), slice_type=0)

    assert not parser._is_i16x16(MBType.P_L0_L0_16x8)
    assert not parser._is_i16x16(MBType.P_L0_L0_8x16)


def test_interpreted_i16x16_type_is_recognized() -> None:
    parser = MacroblockParser(BitstreamReader(b""), slice_type=2)

    assert parser._is_i16x16(MBType.I_16x16_0_0_0)


def test_p_slice_uses_pps_reference_count_when_override_is_false() -> None:
    nal, sps, pps = _p_slice_header(override=False)

    header = SliceHeaderParser(BitstreamReader(nal.rbsp_byte), nal, sps, pps).parse()

    assert header.num_ref_idx_l0_active_minus1 == 2


def test_p_slice_uses_slice_reference_count_when_override_is_true() -> None:
    nal, sps, pps = _p_slice_header(override=True, override_count=1)

    header = SliceHeaderParser(BitstreamReader(nal.rbsp_byte), nal, sps, pps).parse()

    assert header.num_ref_idx_l0_active_minus1 == 1


# --- from test_h264_p_slice_real_stream.py
import shutil
import subprocess

import pytest

from src.bitstream.bitstream_ops import BitstreamReconstructor
from src.bitstream.h264 import H264BitstreamParser, TraceableCAVLCParser


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_real_baseline_p_slices_parse_with_skip_neighbor_context(tmp_path):
    video_path = tmp_path / "testsrc2-baseline-cavlc.h264"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=176x144:rate=5:duration=2",
            "-frames:v",
            "10",
            "-an",
            "-c:v",
            "libx264",
            "-profile:v",
            "baseline",
            "-preset",
            "medium",
            "-x264-params",
            "cabac=0:bframes=0:ref=1:keyint=10:min-keyint=10:scenecut=0:weightp=0",
            "-f",
            "h264",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    nal_units = H264BitstreamParser(str(video_path)).parse()
    reconstructor = BitstreamReconstructor()
    sps = next(
        reconstructor._parse_sps_from_nal(nal)
        for nal in nal_units
        if int(nal.nal_unit_type) == 7
    )
    pps = next(
        reconstructor._parse_pps_from_nal(nal)
        for nal in nal_units
        if int(nal.nal_unit_type) == 8
    )
    p_slices = [nal for nal in nal_units if int(nal.nal_unit_type) == 1]

    assert len(p_slices) == 9
    for nal in p_slices:
        parsed = TraceableCAVLCParser().extract_with_offsets(nal, sps, pps)
        assert parsed["parse_trusted"] is True, parsed["parse_integrity_issues"]
        assert parsed["parse_integrity_issues"] == []


# --- from test_bitstream_reader_read_bits.py
import pytest

from src.bitstream.bitstream_io import BitstreamReader


@pytest.mark.parametrize("start", range(24))
@pytest.mark.parametrize("width", range(17))
def test_read_bits_matches_msb_first_reference_across_byte_boundaries(start, width):
    data = bytes((0xB6, 0x4D, 0xC3))
    bit_string = "".join(f"{byte:08b}" for byte in data)
    if start + width > len(bit_string):
        pytest.skip("requested window extends beyond fixture")

    reader = BitstreamReader(data)
    reader.seek(start)

    expected_bits = bit_string[start : start + width]
    expected = int(expected_bits, 2) if expected_bits else 0
    assert reader.read_bits(width) == expected
    assert reader.tell() == start + width


def test_read_bits_eof_preserves_legacy_partial_consumption():
    reader = BitstreamReader(bytes((0b10110110,)))
    reader.seek(3)

    with pytest.raises(EOFError):
        reader.read_bits(7)

    assert reader.tell() == 8


def test_read_bits_zero_or_negative_width_does_not_advance():
    reader = BitstreamReader(bytes((0b10110110,)))
    reader.seek(3)

    assert reader.read_bits(0) == 0
    assert reader.read_bits(-2) == 0
    assert reader.tell() == 3


def test_peek_bits_restores_position_after_success_and_eof():
    reader = BitstreamReader(bytes((0b10110110,)))
    reader.seek(2)

    assert reader.peek_bits(4) == 0b1101
    assert reader.tell() == 2
    with pytest.raises(EOFError):
        reader.peek_bits(7)
    assert reader.tell() == 2


# --- from test_nal_parser_hotpath.py: Equivalence tests for the optimized Annex-B NAL parsing helpers.
from src.bitstream.h264 import NALParser


def _reference_find_start_codes(data: bytes) -> list[tuple[int, int]]:
    positions = []
    index = 0
    while index < len(data) - 3:
        if data[index : index + 4] == b"\x00\x00\x00\x01":
            positions.append((index + 4, 4))
            index += 4
        elif data[index : index + 3] == b"\x00\x00\x01":
            positions.append((index + 3, 3))
            index += 3
        else:
            index += 1
    return positions


def _reference_remove_emulation_prevention(data: bytes) -> bytes:
    result = bytearray()
    index = 0
    while index < len(data):
        if (
            index + 2 < len(data)
            and data[index : index + 2] == b"\x00\x00"
            and data[index + 2] == 0x03
        ):
            result.extend(data[index : index + 2])
            index += 3
        else:
            result.append(data[index])
            index += 1
    return bytes(result)


def test_find_start_codes_matches_legacy_scan_with_zero_runs_and_trailing_prefixes():
    parser = NALParser(b"")
    fixtures = []
    for prefix_zeros in range(9):
        for between_zeros in range(6):
            fixtures.append(
                b"A" + b"\x00" * prefix_zeros + b"\x01\x65"
                + b"B" + b"\x00" * between_zeros + b"\x01\x41"
            )
    fixtures.extend((b"\x00\x00\x01", b"\x00\x00\x00\x01", b"\x00\x00\x01\x65"))

    for data in fixtures:
        parser.data = data
        assert parser._find_start_codes() == _reference_find_start_codes(data)


def test_remove_emulation_prevention_matches_legacy_scan_for_all_byte_values():
    parser = NALParser(b"")
    fixtures = [bytes(range(256))]
    fixtures.extend(
        b"\x00\x00\x03" + bytes((following,))
        for following in range(256)
    )
    fixtures.extend((b"\x00\x00\x03", b"\x00\x00\x03\x03", b"\x00\x00\x00\x03"))

    for data in fixtures:
        assert parser._remove_emulation_prevention(data) == _reference_remove_emulation_prevention(data)
