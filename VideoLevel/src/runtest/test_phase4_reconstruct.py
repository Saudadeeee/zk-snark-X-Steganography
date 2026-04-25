"""
test_phase4_reconstruct.py — Phase 4: Bitstream Reconstruction (Patcher)

Tests:
  1. output_file_created      — stego video file is written and non-empty
  2. output_valid_h264        — output starts with H.264 Annex B start code
  3. patcher_zero_skips       — embed 10 bytes → patcher applies 100% of patches
  4. file_size_within_bounds  — stego file size within ±2% of original
  5. reconstruct_stats_ok     — reconstruct_video returns success=True with expected fields

Run:
    python src/runtest/test_phase4_reconstruct.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.runtest._helpers      import section, run_test, summarise, get_video, get_output
from src.core.pipeline import extract_all_idr_blocks

from src.core.stego import PayloadEmbedder
from src.bitstream.bitstream_ops import BitstreamReconstructor

# ── Fixtures ─────────────────────────────────────────────────────────── #

VIDEO      = get_video('foreman_cif_g8.h264')
STEGO_OUT  = get_output('test_phase4_stego.h264')

_fixture = None   # (modified_coeffs, frame_verified_data, safe_positions, stats)

PAYLOAD   = b"Phase4TestAB"   # 12 bytes = 96 bits — fast to embed


def _build_fixture():
    global _fixture
    if _fixture is not None:
        return _fixture

    rec = BitstreamReconstructor()
    coefficients, fvd, nC_map, nal_length_map, t1_map = extract_all_idr_blocks(
        VIDEO, rec)

    embedder = PayloadEmbedder()
    modified, bits_embedded = embedder.embed_payload(
        coefficients, PAYLOAD,
        nC_map=nC_map, nal_length_map=nal_length_map,
        t1_override_map=t1_map,
    )
    assert bits_embedded == len(PAYLOAD) * 8, \
        f"Embed incomplete: {bits_embedded}/{len(PAYLOAD)*8} bits"

    # Capture patcher output via logging handler
    import logging as _logging
    log_records = []
    class _ListHandler(_logging.Handler):
        def emit(self, record):
            log_records.append(self.format(record))
    handler = _ListHandler()
    handler.setLevel(_logging.DEBUG)
    root_logger = _logging.getLogger('src.bitstream.bitstream_ops')
    root_logger.setLevel(_logging.DEBUG)
    root_logger.addHandler(handler)
    try:
        stats = rec.reconstruct_video(
            VIDEO, modified, STEGO_OUT,
            max_slices=None,
            frame_verified_data=fvd,
        )
    finally:
        root_logger.removeHandler(handler)

    patcher_log = '\n'.join(log_records)
    _fixture = (modified, fvd, nC_map, nal_length_map, stats, patcher_log)
    return _fixture


# ── Tests ─────────────────────────────────────────────────────────────── #

def t_output_file_created():
    _build_fixture()
    assert os.path.exists(STEGO_OUT), f"Stego file not created: {STEGO_OUT}"
    assert os.path.getsize(STEGO_OUT) > 0, "Stego file is empty"


def t_output_valid_h264():
    _build_fixture()
    with open(STEGO_OUT, 'rb') as f:
        header = f.read(4)
    assert header == b'\x00\x00\x00\x01', \
        f"Stego file does not start with NAL start code, got {header.hex()}"


def t_patcher_zero_skips():
    _, _, _, _, _, patcher_log = _build_fixture()
    lines = [l.strip() for l in patcher_log.splitlines() if '[PATCHER]' in l]
    for line in lines:
        if 'SKIP' in line:
            assert False, f"Unexpected patcher SKIP: {line}"
    # At least one patcher line should report success
    success_lines = [l for l in lines if 'Successfully patched' in l]
    assert len(success_lines) > 0, f"No '[PATCHER] Successfully patched' lines found"


def t_file_size_within_bounds():
    _build_fixture()
    orig_size  = os.path.getsize(VIDEO)
    stego_size = os.path.getsize(STEGO_OUT)
    ratio = abs(stego_size - orig_size) / orig_size
    assert ratio <= 0.02, \
        f"File size change {ratio*100:.2f}% exceeds 2% threshold " \
        f"(orig={orig_size}, stego={stego_size})"


def t_reconstruct_stats_ok():
    _, _, _, _, stats, _ = _build_fixture()
    assert stats.get('success') is True, \
        f"reconstruct_video returned success=False: {stats}"
    assert 'slices_reconstructed' in stats
    assert 'blocks_modified' in stats
    assert stats['blocks_modified'] > 0, \
        "No blocks modified — embedding may not have taken effect"


# ── Cleanup ──────────────────────────────────────────────────────────── #

def _cleanup():
    if os.path.exists(STEGO_OUT):
        try:
            os.remove(STEGO_OUT)
        except OSError:
            pass


# ── Main ─────────────────────────────────────────────────────────────── #

def main():
    section("Phase 4 — Bitstream Reconstruction: patcher, output validity")
    results = [
        run_test("output_file_created",     t_output_file_created),
        run_test("output_valid_h264",       t_output_valid_h264),
        run_test("patcher_zero_skips",      t_patcher_zero_skips),
        run_test("file_size_within_bounds", t_file_size_within_bounds),
        run_test("reconstruct_stats_ok",    t_reconstruct_stats_ok),
    ]
    _cleanup()
    sys.exit(summarise(results, "Phase 4"))


if __name__ == '__main__':
    main()
