import pytest

from src.bitstream.bitstream_io import BitstreamReader, BitstreamWriter
from src.bitstream.cavlc import (
    CAVLCDecoder,
    CAVLCEncoder,
    find_coeff_token_code,
    find_total_zeros_code,
    get_coeff_token_table,
    get_total_zeros_table,
    get_run_before_table,
)


@pytest.mark.parametrize(
    "nc,total_coeffs,trailing_ones,expected",
    [
        (0, 2, 2, "001"),
        (2, 1, 1, "10"),
        (4, 1, 0, "001111"),
        (7, 1, 0, "001111"),
        (8, 0, 0, "000011"),
        (8, 1, 0, "000000"),
        (8, 16, 3, "111111"),
    ],
)
def test_coeff_token_codes_match_h264_table_9_5(nc, total_coeffs, trailing_ones, expected):
    table = get_coeff_token_table(nc)
    assert table[expected] == (total_coeffs, trailing_ones)
    assert find_coeff_token_code(total_coeffs, trailing_ones, nc) == expected


def test_n_c_4_through_7_share_the_same_coeff_token_vlc():
    expected = get_coeff_token_table(4)
    assert get_coeff_token_table(5) is expected
    assert get_coeff_token_table(6) is expected
    assert get_coeff_token_table(7) is expected


def test_chroma_dc_zero_token_uses_its_dedicated_table():
    assert find_coeff_token_code(0, 0, -1) == "01"


@pytest.mark.parametrize(
    "total_coeff, code, expected_zeros",
    [
        (1, "1", 0),
        (1, "01", 1),
        (1, "001", 2),
        (1, "000", 3),
        (2, "1", 0),
        (2, "01", 1),
        (2, "00", 2),
        (3, "1", 0),
        (3, "0", 1),
    ],
)
def test_chroma_dc_total_zeros_uses_normative_2x2_vlc(
    total_coeff, code, expected_zeros
):
    bits = code.ljust(8, "0")
    reader = BitstreamReader(bytes([int(bits, 2)]))
    decoder = CAVLCDecoder(reader)

    assert get_total_zeros_table(total_coeff, is_chroma_dc=True)[code] == expected_zeros
    assert decoder._decode_total_zeros(
        total_coeff, max_num_coeff=4, is_chroma_dc=True
    ) == expected_zeros
    assert reader.position == len(code)


@pytest.mark.parametrize(
    "total_coeff, total_zeros, expected_code",
    [
        (1, 0, "1"),
        (1, 1, "01"),
        (1, 2, "001"),
        (1, 3, "000"),
        (2, 0, "1"),
        (2, 1, "01"),
        (2, 2, "00"),
        (3, 0, "1"),
        (3, 1, "0"),
    ],
)
def test_chroma_dc_total_zeros_encoder_uses_normative_2x2_vlc(
    total_coeff, total_zeros, expected_code
):
    assert find_total_zeros_code(
        total_zeros, total_coeff, is_chroma_dc=True
    ) == expected_code


def test_truncated_coeff_token_fails_closed_instead_of_becoming_zero_coefficients():
    decoder = CAVLCDecoder(BitstreamReader(b""))

    with pytest.raises(ValueError, match="coeff_token"):
        decoder._decode_coeff_token(nC=0)


def test_truncated_total_zeros_fails_closed_instead_of_becoming_zero():
    decoder = CAVLCDecoder(BitstreamReader(b""))

    with pytest.raises(ValueError, match="total_zeros"):
        decoder._decode_total_zeros(total_coeffs=1, max_num_coeff=16)


def test_truncated_run_before_fails_closed_instead_of_becoming_zero_run():
    decoder = CAVLCDecoder(BitstreamReader(b""))

    with pytest.raises(ValueError, match="run_before"):
        decoder._decode_runs(total_coeffs=2, total_zeros=1)


def test_encoder_rejects_trailing_one_override_that_changes_decoded_coefficients():
    coefficients = [0, -2, -1, -1] + [0] * 12
    writer = BitstreamWriter()

    with pytest.raises(ValueError, match="must match the coefficient block"):
        CAVLCEncoder(writer).encode_block_cavlc(
            coefficients,
            nC=2,
            max_num_coeff=16,
            override_trailing_ones=1,
        )


@pytest.mark.parametrize(
    "zeros_left,run_before,expected_code",
    [(4, 3, "001"), (4, 4, "000"), (7, 7, "0001"), (8, 8, "00001"), (14, 14, "00000000001")],
)
def test_run_before_codes_match_h264_table_9_10(zeros_left, run_before, expected_code):
    assert get_run_before_table(zeros_left)[expected_code] == run_before


@pytest.mark.parametrize(
    "trailing_ones,expected_level",
    [(0, 2), (1, 2), (2, 2), (3, 1)],
)
def test_first_non_trailing_level_uses_h264_first_level_adjustment(
    trailing_ones, expected_level
):
    decoder = CAVLCDecoder(BitstreamReader(bytes([0b10000000])))

    assert decoder._decode_levels(1, trailing_ones, total_coeffs=trailing_ones + 1) == [
        expected_level
    ]


@pytest.mark.parametrize(
    "trailing_ones,expected_level",
    [(0, -2), (3, -1)],
)
def test_first_non_trailing_level_preserves_sign_after_adjustment(
    trailing_ones, expected_level
):
    decoder = CAVLCDecoder(BitstreamReader(bytes([0b01000000])))

    assert decoder._decode_levels(1, trailing_ones, total_coeffs=trailing_ones + 1) == [
        expected_level
    ]


@pytest.mark.parametrize(
    "coefficients",
    [
        [2] + [0] * 15,
        [2, -1] + [0] * 14,
        [2, -1, 1] + [0] * 13,
        [2, -1, 1, -1] + [0] * 12,
        [2, 1, -1, 1] + [0] * 12,
        [2] * 16,
        [2] * 15 + [1],
        [2] * 14 + [1, -1],
        [2] * 13 + [-1, 1, -1],
    ],
)
def test_cavlc_encoder_roundtrips_first_level_for_all_trailing_one_counts(coefficients):
    writer = BitstreamWriter()
    CAVLCEncoder(writer).encode_block_cavlc(coefficients, nC=0)
    encoded_bit_count = writer.get_bit_count()
    reader = BitstreamReader(writer.get_bytes())

    decoded = CAVLCDecoder(reader).decode_block_cavlc(nC=0)

    assert decoded.levels == coefficients
    assert reader.position == encoded_bit_count
