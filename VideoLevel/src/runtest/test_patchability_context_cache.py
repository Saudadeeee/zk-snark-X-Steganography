from __future__ import annotations

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
