"""CAVLCSafetyFilter: num_coeff bound, original-length cache, verified-length reuse."""

from __future__ import annotations

# --- from test_safety_filter_max_num_coeff.py
from src.core.stego import CAVLCSafetyFilter


def test_bit_length_safety_uses_cavlc_max_num_coeff_from_bitstream():
    source = [9, -9, -9, -2, -11, -9, -7, 10, 19, -13, 18, -23, 19, -8, -9, 0]
    modified = list(source)
    modified[1] = -8

    is_safe, source_bits, modified_bits = CAVLCSafetyFilter()._verify_block_bit_length_invariance(
        source,
        modified,
        nC=15,
        nal_bit_length=102,
        max_num_coeff=15,
    )

    assert source_bits == 102
    assert modified_bits == 101
    assert is_safe is False


# --- from test_safety_filter_original_length_cache.py: Tests for reusing the exact source CAVLC length within one block.
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


# --- from test_safety_filter_verified_length_reuse.py
from src.bitstream.bitstream_io import BitstreamWriter
from src.bitstream.bitstream_ops import BitstreamPatcher
from src.bitstream.cavlc import CAVLCEncoder
from src.core.stego import CAVLCSafetyFilter


def test_filter_reuses_length_from_successful_patchability_validation(monkeypatch) -> None:
    coefficients = [0, 10] + [0] * 14
    writer = BitstreamWriter()
    CAVLCEncoder(writer).encode_block_cavlc(coefficients, nC=0)
    rbsp = writer.get_bytes()
    bit_length = writer.get_bit_position()
    offsets = {
        (0, 1): {
            "start_bit": 0,
            "end_bit": bit_length,
            "bit_length": bit_length,
            "nC": 0,
            "max_num_coeff": 16,
        }
    }
    frame_data = {0: (offsets, {}, rbsp)}
    source_encode_calls = 0
    original_encode = CAVLCEncoder.encode_block_cavlc

    def count_source_encodes(self, block, *args, **kwargs):
        nonlocal source_encode_calls
        if list(block) == coefficients:
            source_encode_calls += 1
        return original_encode(self, block, *args, **kwargs)

    monkeypatch.setattr(CAVLCEncoder, "encode_block_cavlc", count_source_encodes)
    monkeypatch.setattr(
        BitstreamPatcher,
        "validate_block_patchability",
        lambda *_args, **_kwargs: (0, coefficients, None),
    )

    safe = CAVLCSafetyFilter().get_safe_positions(
        [(0, 1, coefficients)],
        nC_map={(0, 1): 0},
        nal_length_map={(0, 1): bit_length},
        frame_verified_data=frame_data,
    )

    assert safe
    # One source encode is the exact round-trip performed by the patchability
    # validator. Re-encoding it again in the safety filter is redundant.
    assert source_encode_calls == 0
