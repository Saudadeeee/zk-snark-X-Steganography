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
