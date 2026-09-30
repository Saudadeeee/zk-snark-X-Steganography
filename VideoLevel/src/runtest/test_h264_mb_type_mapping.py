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
