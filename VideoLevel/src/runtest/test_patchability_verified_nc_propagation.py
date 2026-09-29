from __future__ import annotations

import bisect

from src import embedder as embedder_module
from src.bitstream.bitstream_ops import BitstreamPatcher
from src.embedder import _prune_patchable_positions


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
    monkeypatch.setattr(embedder_module, "bisect_right", bisect_spy, raising=False)

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
    monkeypatch.setattr(embedder_module, "defaultdict", reject_position_buckets)

    candidates = [(0, 0, 1), (0, 0, 2), (1, 0, 3), (2, 0, 4)]
    retained = _prune_patchable_positions(
        candidates,
        frame_verified_data,
        required_bits=2,
        max_modifications_per_block=1,
    )

    assert retained == [(0, 0, 1), (1, 0, 3)]
    assert validated_blocks == [(0, 0), (1, 0)]
