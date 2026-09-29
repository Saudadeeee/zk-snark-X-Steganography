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
