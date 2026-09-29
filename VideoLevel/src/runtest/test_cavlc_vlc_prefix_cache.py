import pytest

from src.bitstream.bitstream_io import BitstreamReader
import src.bitstream.cavlc as cavlc
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
    original_builder = cavlc._build_longer_vlc_prefixes
    builds = 0

    def counting_builder(vlc_table):
        nonlocal builds
        builds += 1
        return original_builder(vlc_table)

    monkeypatch.setattr(cavlc, "_build_longer_vlc_prefixes", counting_builder)
    for _ in range(2):
        reader = BitstreamReader(bytes([0b10000000]))
        assert decode_vlc(reader, table, max_bits=16) == (0, 0)
        assert reader.tell() == 1

    assert builds == 1


def test_builtin_vlc_tables_cannot_be_mutated_after_prefix_cache(monkeypatch):
    table = cavlc.get_coeff_token_table(0)
    cavlc._longer_vlc_prefixes(table)

    with pytest.raises(TypeError, match="immutable"):
        table["0"] = (99, 0)
