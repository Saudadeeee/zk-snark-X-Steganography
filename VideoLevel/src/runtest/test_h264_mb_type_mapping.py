from src.bitstream.bitstream_io import BitstreamReader
from src.bitstream.h264 import MacroblockParser, MBType


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
