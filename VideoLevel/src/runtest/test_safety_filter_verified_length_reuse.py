from __future__ import annotations

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
