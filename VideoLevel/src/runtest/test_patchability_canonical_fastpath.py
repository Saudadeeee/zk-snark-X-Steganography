from __future__ import annotations

from src.bitstream.bitstream_io import BitstreamWriter
from src.bitstream.bitstream_ops import BitstreamPatcher
from src.bitstream.cavlc import CAVLCDecoder, CAVLCEncoder


def test_canonical_block_roundtrip_skips_redundant_predecessor_bit_probes(monkeypatch) -> None:
    writer = BitstreamWriter()
    encoder = CAVLCEncoder(writer)
    ancestor = [0, 3] + [0] * 14
    target = [0, 5] + [0] * 14
    encoder.encode_block_cavlc(ancestor, nC=0)
    ancestor_length = writer.get_bit_count()
    encoder.encode_block_cavlc(target, nC=0)
    target_length = writer.get_bit_count() - ancestor_length
    rbsp = writer.get_bytes()

    ancestor_offset = {
        "start_bit": 0,
        "end_bit": ancestor_length,
        "bit_length": ancestor_length,
        "nC": 0,
        "max_num_coeff": 16,
    }
    target_offset = {
        "start_bit": ancestor_length,
        "end_bit": ancestor_length + target_length,
        "bit_length": target_length,
        "nC": 0,
        "max_num_coeff": 16,
    }

    decode_calls = 0
    original_decode = CAVLCDecoder.decode_block_cavlc

    def count_decodes(self, *args, **kwargs):
        nonlocal decode_calls
        decode_calls += 1
        return original_decode(self, *args, **kwargs)

    monkeypatch.setattr(CAVLCDecoder, "decode_block_cavlc", count_decodes)
    match = BitstreamPatcher().validate_block_patchability(
        rbsp,
        (1, 0),
        target_offset,
        {ancestor_length: ((0, 0), ancestor_offset)},
    )

    assert match is not None
    assert match[2] is None
    assert decode_calls == 1
