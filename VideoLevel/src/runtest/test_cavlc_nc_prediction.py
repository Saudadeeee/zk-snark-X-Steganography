import pytest

from src.bitstream.h264 import _predict_cavlc_nc


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
