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
