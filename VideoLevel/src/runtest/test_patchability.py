"""Block patchability: canonical fast path, context cache, window decode, verified nC propagation."""

from __future__ import annotations

# --- from test_patchability_canonical_fastpath.py
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


# --- from test_patchability_context_cache.py
from src.core.stego import CAVLCSafetyFilter
from src.bitstream.bitstream_ops import BitstreamPatcher


def test_filter_reuses_one_predecessor_index_for_blocks_in_same_idr(monkeypatch) -> None:
    offsets = {
        (0, 0): {"start_bit": 0, "end_bit": 8, "bit_length": 8, "nC": 0},
        (0, 1): {"start_bit": 8, "end_bit": 16, "bit_length": 8, "nC": 0},
    }
    frame_data = {0: (offsets, {}, b"\x00\x00\x00")}
    coefficients = [
        (0, 0, [0, 4] + [0] * 14),
        (0, 1, [0, 6] + [0] * 14),
    ]
    end_indexes = []

    def validate(_self, _rbsp, key, offset, end_to_block):
        end_indexes.append(end_to_block)
        return 0, coefficients[key[1]][2], None

    monkeypatch.setattr(BitstreamPatcher, "validate_block_patchability", validate)
    safety_filter = CAVLCSafetyFilter(enable_bit_length_check=False)

    positions = safety_filter.get_safe_positions(
        coefficients,
        nC_map={(0, 0): 0, (0, 1): 0},
        nal_length_map={(0, 0): 8, (0, 1): 8},
        frame_verified_data=frame_data,
    )

    assert len(positions) == 2
    assert len(end_indexes) == 2
    assert end_indexes[0] is end_indexes[1]


# --- from test_patchability_window_decode.py
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


# --- from test_patchability_verified_nc_propagation.py
import bisect

from src.core import carrier_gate as gate_module
from src.bitstream.bitstream_ops import BitstreamPatcher
from src.core.carrier_gate import prune_patchable_positions as _prune_patchable_positions


def test_patchability_pruning_propagates_verified_nc_to_reconstruction(monkeypatch):
    offset = {
        "start_bit": 0,
        "end_bit": 8,
        "bit_length": 8,
        "nC": 0,
    }
    frame_verified_data = {
        0: (
            {(0, 0): offset},
            {(0, 0): [0, 4] + [0] * 14},
            b"\x00",
        )
    }

    def validated_match(_self, _rbsp, _block_key, offset_data, _end_to_block):
        assert offset_data["nC"] == 0
        return 4, [0, 4] + [0] * 14, None

    monkeypatch.setattr(BitstreamPatcher, "validate_block_patchability", validated_match)

    retained = _prune_patchable_positions(
        [(0, 0, 1)],
        frame_verified_data,
        required_bits=1,
    )

    assert retained == [(0, 0, 1)]
    assert offset["nC"] == 4
    assert offset["validated_nC"] == 4


def test_patchability_pruning_selects_nearest_preceding_idr_in_input_order(monkeypatch):
    frame_verified_data = {}
    expected_rbsp = {}
    for idr_offset, mb, label in (
        (200, 210, b"C"),
        (0, 10, b"A"),
        (100, 150, b"B"),
    ):
        frame_verified_data[idr_offset] = (
            {(mb, 0): {"bit_length": 8, "end_bit": 8}},
            {(mb, 0): [0, 1] + [0] * 14},
            label,
        )
        expected_rbsp[idr_offset] = label

    validated_rbsp = []
    lookups = []

    def bisect_spy(ordered_idr_offsets, macroblock):
        lookups.append(macroblock)
        return bisect.bisect_right(ordered_idr_offsets, macroblock)

    def validated_match(_self, rbsp, _block_key, _offset_data, _end_to_block):
        validated_rbsp.append(rbsp)
        return 0, [0, 1] + [0] * 14, None

    monkeypatch.setattr(BitstreamPatcher, "validate_block_patchability", validated_match)
    monkeypatch.setattr(gate_module, "bisect_right", bisect_spy, raising=False)

    positions = [(210, 0, 1), (10, 0, 1), (150, 0, 1), (90, 0, 1)]
    retained = _prune_patchable_positions(
        positions,
        frame_verified_data,
        required_bits=3,
    )

    assert retained == positions[:3]
    assert validated_rbsp == [
        expected_rbsp[200],
        expected_rbsp[0],
        expected_rbsp[100],
    ]
    assert lookups == [210, 10, 150]


def test_single_carrier_pruning_does_not_materialize_position_buckets(monkeypatch):
    offset_0 = {"bit_length": 8, "end_bit": 8, "nC": 0}
    offset_1 = {"bit_length": 8, "end_bit": 16, "nC": 0}
    frame_verified_data = {
        0: (
            {(0, 0): offset_0, (1, 0): offset_1},
            {(0, 0): [0, 1] + [0] * 14, (1, 0): [0, 1] + [0] * 14},
            b"\x00\x00",
        )
    }
    validated_blocks = []

    def validate(_self, _rbsp, block_key, _offset, _end_to_block):
        validated_blocks.append(block_key)
        return 0, [0, 1] + [0] * 14, None

    def reject_position_buckets(*_args, **_kwargs):
        raise AssertionError("single-carrier path should stream candidates by block")

    monkeypatch.setattr(BitstreamPatcher, "validate_block_patchability", validate)
    monkeypatch.setattr(gate_module, "defaultdict", reject_position_buckets, raising=False)

    candidates = [(0, 0, 1), (0, 0, 2), (1, 0, 3), (2, 0, 4)]
    retained = _prune_patchable_positions(
        candidates,
        frame_verified_data,
        required_bits=2,
        max_modifications_per_block=1,
    )

    assert retained == [(0, 0, 1), (1, 0, 3)]
    assert validated_blocks == [(0, 0), (1, 0)]
