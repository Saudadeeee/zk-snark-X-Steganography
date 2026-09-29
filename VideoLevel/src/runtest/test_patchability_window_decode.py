from __future__ import annotations

import numpy as np

from src.bitstream.bitstream_io import BitstreamWriter
from src.bitstream.bitstream_ops import BitstreamPatcher
from src.bitstream.cavlc import CAVLCEncoder


def test_patchability_validation_unpacks_only_the_local_cavlc_window(monkeypatch) -> None:
    writer = BitstreamWriter()
    encoder = CAVLCEncoder(writer)
    coefficients = [0, 5] + [0] * 14
    encoder.encode_block_cavlc(coefficients, nC=0)
    block_bytes = writer.get_bytes()
    block_bits = writer.get_bit_count()

    prefix = bytes(1_000_000)
    rbsp = prefix + block_bytes
    start_bit = len(prefix) * 8
    offset = {
        "start_bit": start_bit,
        "end_bit": start_bit + block_bits,
        "bit_length": block_bits,
        "nC": 0,
        "max_num_coeff": 16,
    }

    unpacked_lengths: list[int] = []
    original_unpackbits = np.unpackbits

    def record_unpack_length(values, *args, **kwargs):
        unpacked_lengths.append(len(values))
        return original_unpackbits(values, *args, **kwargs)

    monkeypatch.setattr(np, "unpackbits", record_unpack_length)
    match = BitstreamPatcher().validate_block_patchability(
        rbsp,
        (0, 0),
        offset,
    )

    assert match is not None
    assert match[1] == coefficients
    assert unpacked_lengths
    assert max(unpacked_lengths) <= len(block_bytes) + 8
