"""Keep repeated header/body extraction from reparsing the same stream."""

from types import SimpleNamespace

import pytest

from src.core import pipeline
from src.core.pipeline import _extract_bits_from_decoded_analysis, extract_bits_direct


def test_extractor_accepts_an_already_parsed_h264_parser():
    parser = SimpleNamespace(nal_units=[])

    result = _extract_bits_from_decoded_analysis(
        stego_video_path="not-opened.h264",
        embed_safe_positions=[],
        frame_verified_data={},
        nC_map={},
        payload_bits=0,
        parser=parser,
    )

    assert result == b""


@pytest.mark.parametrize(
    ("data", "start_bit", "end_bit"),
    [
        (b"\xa6\x59", 0, 0),
        (b"\xa6\x59", 1, 5),
        (b"\xa6\x59", 7, 9),
        (b"\xa6\x59", 8, 12),
        (b"\xa6\x59", 15, 16),
        (b"\xa6\x59", 16, 16),
        (b"\xa6\x59", 20, 21),
        (bytes(range(16)), 13, 21),
    ],
)
def test_rbsp_bit_window_matches_bitarray_slice(data, start_bit, end_bit):
    from src.bitstream.bitstream_ops import BitArray

    stop_bit = min(end_bit + 64, len(data) * 8)
    bits = BitArray(data)[start_bit:stop_bit]
    bits.extend([0] * ((8 - len(bits) % 8) % 8))
    expected = bytes(
        sum(bits[index + offset] << (7 - offset) for offset in range(8))
        for index in range(0, len(bits), 8)
    )

    assert pipeline._rbsp_bit_window_to_bytes(data, start_bit, end_bit) == expected


def test_extractor_preserves_payload_bit_order_across_idrs(monkeypatch):
    idr_zero = SimpleNamespace(nal_unit_type=5, rbsp_byte=b"\x80")
    idr_ten = SimpleNamespace(nal_unit_type=5, rbsp_byte=b"\x00")
    parser = SimpleNamespace(nal_units=[idr_zero, idr_ten])
    frame_data = {
        0: ({(0, 0): {"start_bit": 0, "end_bit": 1}}, {}, idr_zero.rbsp_byte),
        10: ({(10, 0): {"start_bit": 0, "end_bit": 1}}, {}, idr_ten.rbsp_byte),
    }

    def decode_first_bit(decoder, _n_c, *, max_num_coeff):
        assert max_num_coeff == 16
        return SimpleNamespace(levels=[decoder.reader.read_bits(1)])

    monkeypatch.setattr(pipeline.CAVLCDecoder, "decode_block_cavlc", decode_first_bit)

    result = extract_bits_direct(
        stego_video_path="not-opened.h264",
        embed_safe_positions=[(10, 0, 0), (0, 0, 0)],
        frame_verified_data=frame_data,
        nC_map={(0, 0): 0, (10, 0): 0},
        payload_bits=2,
        parser=parser,
    )

    assert result == b"\x40"


def test_extractor_can_reuse_decoded_blocks_without_redecoding(monkeypatch):
    idr = SimpleNamespace(nal_unit_type=5, rbsp_byte=b"\x00")
    frame_data = {
        0: (
            {(0, 0): {"start_bit": 0, "end_bit": 1}},
            {(0, 0): [2, -3, 4]},
            idr.rbsp_byte,
        )
    }

    def unexpected_decode(*_args, **_kwargs):
        raise AssertionError("decoded blocks must be reused in fast extraction mode")

    monkeypatch.setattr(pipeline.CAVLCDecoder, "decode_block_cavlc", unexpected_decode)

    result = _extract_bits_from_decoded_analysis(
        stego_video_path="not-opened.h264",
        embed_safe_positions=[(0, 0, 0), (0, 0, 1), (0, 0, ~2)],
        frame_verified_data=frame_data,
        nC_map={(0, 0): 0},
        payload_bits=3,
        max_modifications_per_block=3,
    )

    # abs(2)&1, abs(-3)&1, and the negative-index sign bit for +4.
    assert result == b"\x40"


def test_decoded_block_mode_skips_missing_blocks_without_fallback(monkeypatch):
    idr = SimpleNamespace(nal_unit_type=5, rbsp_byte=b"\x00")
    frame_data = {0: ({(0, 0): {"start_bit": 0, "end_bit": 1}}, {}, idr.rbsp_byte)}
    parser = SimpleNamespace(nal_units=[idr])

    def unexpected_decode(*_args, **_kwargs):
        raise AssertionError("missing cached blocks must not trigger a second decode")

    monkeypatch.setattr(pipeline.CAVLCDecoder, "decode_block_cavlc", unexpected_decode)

    result = _extract_bits_from_decoded_analysis(
        stego_video_path="not-opened.h264",
        embed_safe_positions=[(0, 0, 0)],
        frame_verified_data=frame_data,
        nC_map={(0, 0): 0},
        payload_bits=1,
        parser=parser,
    )

    assert result == b""
