"""Tests for reusing the exact source CAVLC length within one block."""

from src.bitstream.bitstream_io import BitstreamWriter
from src.bitstream.cavlc import CAVLCEncoder
from src.core.stego import CAVLCSafetyFilter


def _encoded_length(coeffs, n_c):
    writer = BitstreamWriter()
    CAVLCEncoder(writer).encode_block_cavlc(coeffs, nC=n_c, max_num_coeff=len(coeffs))
    return writer.get_bit_position()


def test_known_original_length_preserves_safety_result_and_skips_source_reencode(monkeypatch):
    original = [0, 3, 0, -2] + [0] * 12
    modified = original.copy()
    modified[1] = 2
    n_c = 0
    source_length = _encoded_length(original, n_c)
    safety_filter = CAVLCSafetyFilter()

    expected = safety_filter._verify_block_bit_length_invariance(
        original, modified, nC=n_c, nal_bit_length=source_length
    )

    encode_calls = []
    original_encode = CAVLCEncoder.encode_block_cavlc

    def counted_encode(self, coeffs, *args, **kwargs):
        encode_calls.append(tuple(coeffs))
        return original_encode(self, coeffs, *args, **kwargs)

    monkeypatch.setattr(CAVLCEncoder, "encode_block_cavlc", counted_encode)
    actual = safety_filter._verify_block_bit_length_invariance(
        original,
        modified,
        nC=n_c,
        nal_bit_length=source_length,
        known_original_bit_length=source_length,
    )

    assert actual == expected
    assert encode_calls == [tuple(modified)]


def test_known_original_length_rejects_mismatch_with_nal_length():
    original = [0, 3, 0, -2] + [0] * 12
    modified = original.copy()
    modified[1] = 2
    actual = CAVLCSafetyFilter()._verify_block_bit_length_invariance(
        original,
        modified,
        nC=0,
        nal_bit_length=999,
        known_original_bit_length=1,
    )

    assert actual == (False, 1, 0)
