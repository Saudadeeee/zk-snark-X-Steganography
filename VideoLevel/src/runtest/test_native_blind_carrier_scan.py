"""Unit tests for blind carrier traversal in native x264 output."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "native"
    / "x264_fork"
    / "tests"
    / "blind_extract_smoke.py"
)
_SPEC = importlib.util.spec_from_file_location("blind_extract_smoke", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_BLIND_EXTRACTOR = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BLIND_EXTRACTOR)


def test_idr_intra_carriers_follow_raster_scan_order() -> None:
    assert _BLIND_EXTRACTOR.carrier_block_order(5, 0) == tuple(range(16))


def test_p_slice_intra_carriers_follow_raster_scan_order() -> None:
    # P-slice macroblock type 5 is I_NxN (intra 4x4) in H.264.
    assert _BLIND_EXTRACTOR.carrier_block_order(1, 5) == tuple(range(16))


def test_p_slice_inter_carriers_follow_h264_luma_block_scan_order() -> None:
    assert _BLIND_EXTRACTOR.carrier_block_order(1, 0) == tuple(range(16))


def test_non_carrier_macroblock_types_are_skipped() -> None:
    assert _BLIND_EXTRACTOR.carrier_block_order(1, 6) == ()
    assert _BLIND_EXTRACTOR.carrier_block_order(1, None) == ()
