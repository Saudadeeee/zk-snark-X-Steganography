"""CAVLC tables and caches: coeff_token tables, encoder lookup cache, nC prediction, VLC prefix cache."""

from __future__ import annotations

# --- from test_cavlc_coeff_token_tables.py
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


# --- from test_cavlc_encoder_lookup_cache.py
from src.bitstream import cavlc


def test_encoder_vlc_lookup_reuses_bounded_immutable_results(monkeypatch) -> None:
    for lookup in (
        cavlc.find_coeff_token_code,
        cavlc.find_total_zeros_code,
        cavlc.find_run_before_code,
    ):
        if hasattr(lookup, "cache_clear"):
            lookup.cache_clear()

    calls = {"coeff": 0, "zeros": 0, "run": 0}
    original_coeff = cavlc.build_reverse_coeff_token_table
    original_zeros = cavlc.build_reverse_total_zeros_table
    original_run = cavlc.build_reverse_run_before_table

    def count_coeff(*args, **kwargs):
        calls["coeff"] += 1
        return original_coeff(*args, **kwargs)

    def count_zeros(*args, **kwargs):
        calls["zeros"] += 1
        return original_zeros(*args, **kwargs)

    def count_run(*args, **kwargs):
        calls["run"] += 1
        return original_run(*args, **kwargs)

    monkeypatch.setattr(cavlc, "build_reverse_coeff_token_table", count_coeff)
    monkeypatch.setattr(cavlc, "build_reverse_total_zeros_table", count_zeros)
    monkeypatch.setattr(cavlc, "build_reverse_run_before_table", count_run)

    coeff_first = cavlc.find_coeff_token_code(1, 0, 0)
    zero_first = cavlc.find_total_zeros_code(0, 1)
    run_first = cavlc.find_run_before_code(0, 1)
    assert cavlc.find_coeff_token_code(1, 0, 0) == coeff_first
    assert cavlc.find_total_zeros_code(0, 1) == zero_first
    assert cavlc.find_run_before_code(0, 1) == run_first

    assert calls == {"coeff": 1, "zeros": 1, "run": 1}


# --- from test_cavlc_nc_prediction.py
import pytest

from src.bitstream.bitstream_io import BitstreamReader
from src.bitstream.h264 import MacroblockParser, TraceableCAVLCParser, _predict_cavlc_nc


@pytest.mark.parametrize(
    "left,top,expected",
    [
        (None, None, 0),
        (5, None, 5),
        (None, 7, 7),
        (4, 7, 6),
        (0, 1, 1),
    ],
)
def test_n_c_uses_only_available_neighbor_counts(left, top, expected):
    assert _predict_cavlc_nc(left, top) == expected


def test_skipped_macroblock_is_cached_as_zero_coeff_neighbor():
    parser = TraceableCAVLCParser()
    blocks = {}
    metadata = {}
    parser.neighbor_coeffs = {}

    parser._record_skipped_macroblock(3, blocks, metadata)
    parser.neighbor_coeffs[(1, 10)] = 6

    mb_parser = MacroblockParser(BitstreamReader(b""), slice_type=0)
    assert mb_parser.calculate_nC(1, 1, 0, parser.neighbor_coeffs, mb_width=3) == 3
    assert parser.neighbor_coeffs[(3, 23)] == 0
    assert metadata[3]["is_skip_mb"] is True


# --- from test_cavlc_vlc_prefix_cache.py
import pytest

from src.bitstream import cavlc
from src.bitstream.bitstream_io import BitstreamReader
from src.bitstream.cavlc import decode_vlc


class CountingVlcTable(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.keys_scans = 0

    def keys(self):
        self.keys_scans += 1
        return super().keys()


def test_mutating_custom_vlc_table_does_not_leave_a_stale_prefix_index():
    table = CountingVlcTable({"0": "short"})

    first_reader = BitstreamReader(bytes([0b01000000]))
    assert decode_vlc(first_reader, table, max_bits=2) == "short"
    assert first_reader.tell() == 1

    table["01"] = "long"
    second_reader = BitstreamReader(bytes([0b01000000]))
    assert decode_vlc(second_reader, table, max_bits=2) == "long"
    assert second_reader.tell() == 2
    assert table.keys_scans == 2


def test_builtin_vlc_table_prefix_index_is_reused(monkeypatch):
    table = cavlc.get_coeff_token_table(0)
    cavlc._longer_vlc_prefixes(table)
    cavlc._VLC_LONGER_PREFIX_CACHE.pop(id(table), None)
    original_builder = cavlc._build_longer_vlc_prefixes
    builds = 0

    def counting_builder(vlc_table):
        nonlocal builds
        builds += 1
        return original_builder(vlc_table)

    monkeypatch.setattr(cavlc, "_build_longer_vlc_prefixes", counting_builder)
    for _ in range(2):
        reader = BitstreamReader(bytes([0b10000000]))
        assert decode_vlc(reader, table, max_bits=16, debug=True) == (0, 0)
        assert reader.tell() == 1

    assert builds == 1


def test_builtin_vlc_tables_cannot_be_mutated_after_prefix_cache(monkeypatch):
    table = cavlc.get_coeff_token_table(0)
    cavlc._longer_vlc_prefixes(table)

    with pytest.raises(TypeError, match="immutable"):
        table["0"] = (99, 0)


def _reader_for_code(code):
    padded = code + "0" * (-len(code) % 8)
    return BitstreamReader(
        bytes(int(padded[offset : offset + 8], 2) for offset in range(0, len(padded), 8))
    )


def test_trie_decoder_matches_every_builtin_vlc_entry():
    seen_tables = set()
    for table in cavlc._VLC_BUILTIN_TABLES.values():
        if id(table) in seen_tables:
            continue
        seen_tables.add(id(table))
        for code, expected in table.items():
            reader = _reader_for_code(code)
            assert decode_vlc(reader, table, max_bits=16) == expected
            assert reader.tell() == len(code)


def test_builtin_vlc_trie_is_built_once_and_reused(monkeypatch):
    table = cavlc.get_coeff_token_table(0)
    cavlc._VLC_TRIE_CACHE.pop(id(table), None)
    original_builder = cavlc._build_vlc_trie
    builds = 0

    def counting_builder(vlc_table):
        nonlocal builds
        builds += 1
        return original_builder(vlc_table)

    monkeypatch.setattr(cavlc, "_build_vlc_trie", counting_builder)
    for _ in range(2):
        reader = BitstreamReader(bytes((0b10000000,)))
        assert decode_vlc(reader, table, max_bits=16) == (0, 0)
        assert reader.tell() == 1

    assert builds == 1
