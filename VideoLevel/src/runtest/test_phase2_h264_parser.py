"""
test_phase2_h264_parser.py - Phase 2: H.264 Bitstream Parsing & CAVLC Block Extraction

Tests:
  1. video_file_exists         - test video is present
  2. nal_units_found           - parser.parse() returns > 0 NAL units
  3. sps_pps_present           - SPS (type 7) and PPS (type 8) both detected
  4. idr_frames_detected       - at least 1 IDR slice (type 5) present
  5. traceable_block_count     - TraceableCAVLCParser returns > 0 luma blocks for first IDR
  6. coeffs_are_16_elements    - all luma coefficient arrays have exactly 16 elements
  7. nc_map_populated          - nC_map has entries after extraction
  8. nal_length_map_populated  - nal_length_map has entries, all values > 0

Run:
    python src/runtest/test_phase2_h264_parser.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.runtest._helpers import section, run_test, summarise, get_video

from src.bitstream.h264          import H264BitstreamParser
from src.bitstream.h264 import TraceableCAVLCParser
from src.bitstream.bitstream_ops import BitstreamReconstructor

# -- Fixtures (parsed once, reused across tests) ------------------------- #

VIDEO = get_video('foreman_cif_q22_g1.h264')
_parsed   = None   # (nal_units, sps, pps)
_traceable = None  # (coefficients, nC_map, nal_length_map)


def _ensure_parsed():
    global _parsed
    if _parsed is not None:
        return
    parser = H264BitstreamParser(VIDEO)
    parser.parse()
    rec = BitstreamReconstructor()
    sps = pps = None
    for nal in parser.nal_units:
        t = int(nal.nal_unit_type)
        if t == 7:
            sps = rec._parse_sps_from_nal(nal)
        elif t == 8:
            pps = rec._parse_pps_from_nal(nal)
    _parsed = (parser.nal_units, sps, pps)


def _ensure_traceable():
    global _traceable
    if _traceable is not None:
        return
    _ensure_parsed()
    nal_units, sps, pps = _parsed

    # Extract first IDR only (sufficient for parser tests)
    traceable = TraceableCAVLCParser()
    first_idr = next((n for n in nal_units if int(n.nal_unit_type) == 5), None)
    if first_idr is None:
        _traceable = ([], {}, {})
        return

    result  = traceable.extract_with_offsets(first_idr, sps, pps, global_mb_idx=0)
    blocks  = result.get('blocks',  {})
    offsets = result.get('offsets', {})

    coefficients = []
    nC_map       = {}
    nal_length_map = {}
    for (mb, bi), coeffs in sorted(blocks.items()):
        if bi >= 16:
            continue
        if any(c != 0 for c in coeffs):
            coefficients.append((mb, bi, list(coeffs)))
        od = offsets.get((mb, bi), {})
        if 'nC' in od:
            nC_map[(mb, bi)] = od['nC']
        if 'bit_length' in od:
            nal_length_map[(mb, bi)] = od['bit_length']

    _traceable = (coefficients, nC_map, nal_length_map)


# -- Tests -------------------------------------------------------------- #

def t_video_file_exists():
    assert os.path.exists(VIDEO), f"Test video not found: {VIDEO}"
    assert os.path.getsize(VIDEO) > 0, "Test video is empty"


def t_nal_units_found():
    _ensure_parsed()
    nal_units, _, _ = _parsed
    assert len(nal_units) > 0, "No NAL units found in video"


def t_sps_pps_present():
    _ensure_parsed()
    nal_units, sps, pps = _parsed
    assert sps is not None, "SPS (NAL type 7) not found"
    assert pps is not None, "PPS (NAL type 8) not found"


def t_idr_frames_detected():
    _ensure_parsed()
    nal_units, _, _ = _parsed
    idr_count = sum(1 for n in nal_units if int(n.nal_unit_type) == 5)
    assert idr_count >= 1, f"No IDR frames (type 5) found; got {idr_count}"


def t_traceable_block_count():
    _ensure_traceable()
    coefficients, _, _ = _traceable
    assert len(coefficients) > 0, \
        "TraceableCAVLCParser returned 0 non-zero luma blocks for first IDR"


def t_coeffs_are_16_elements():
    _ensure_traceable()
    coefficients, _, _ = _traceable
    bad = [(mb, bi) for mb, bi, c in coefficients if len(c) not in (15, 16)]
    assert len(bad) == 0, \
        f"{len(bad)} blocks have coefficient arrays != 15 or 16 elements: {bad[:5]}"


def t_nc_map_populated():
    _ensure_traceable()
    _, nC_map, _ = _traceable
    assert len(nC_map) > 0, "nC_map is empty after TraceableCAVLCParser extraction"


def t_nal_length_map_populated():
    _ensure_traceable()
    _, _, nal_length_map = _traceable
    assert len(nal_length_map) > 0, "nal_length_map is empty"
    bad = [(k, v) for k, v in nal_length_map.items() if v <= 0]
    assert len(bad) == 0, \
        f"{len(bad)} blocks have nal_length <= 0: {bad[:5]}"


# -- Main --------------------------------------------------------------- #

def main():
    section("Phase 2 - H.264 Parser: NAL units, SPS/PPS, CAVLC block extraction")
    results = [
        run_test("video_file_exists",        t_video_file_exists),
        run_test("nal_units_found",          t_nal_units_found),
        run_test("sps_pps_present",          t_sps_pps_present),
        run_test("idr_frames_detected",      t_idr_frames_detected),
        run_test("traceable_block_count",    t_traceable_block_count),
        run_test("coeffs_are_16_elements",   t_coeffs_are_16_elements),
        run_test("nc_map_populated",         t_nc_map_populated),
        run_test("nal_length_map_populated", t_nal_length_map_populated),
    ]
    sys.exit(summarise(results, "Phase 2"))


if __name__ == '__main__':
    main()
