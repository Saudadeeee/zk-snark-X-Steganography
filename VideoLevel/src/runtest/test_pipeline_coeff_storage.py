from __future__ import annotations

from types import SimpleNamespace

from src.core import pipeline
from src.core.stego import PayloadEmbedder


def test_extracted_coefficients_share_decoded_block_storage(monkeypatch) -> None:
    """Avoid duplicating each luma coefficient vector in whole-video analysis."""
    decoded_coefficients = [0, 3, -2] + [0] * 13
    blocks = {(0, 0): decoded_coefficients}
    offsets = {
        (0, 0): {
            "bit_length": 12,
            "start_bit": 4,
            "end_bit": 16,
            "nC": 2,
            "max_num_coeff": 16,
        }
    }
    nal_units = [
        SimpleNamespace(nal_unit_type=7),
        SimpleNamespace(nal_unit_type=8),
        SimpleNamespace(nal_unit_type=5, rbsp_byte=b"\x00"),
    ]
    parser = SimpleNamespace(nal_units=nal_units)
    sps = SimpleNamespace(pic_width_in_mbs_minus1=0, pic_height_in_map_units_minus1=0)
    pps = SimpleNamespace()

    class FakeReconstructor:
        def _parse_sps_from_nal(self, _nal):
            return sps

        def _parse_pps_from_nal(self, _nal):
            return pps

    class FakeTraceableParser:
        def extract_with_offsets(self, _nal, _sps, _pps, *, global_mb_idx):
            assert global_mb_idx == 0
            return {
                "parse_trusted": True,
                "blocks": blocks,
                "offsets": offsets,
            }

    monkeypatch.setattr(pipeline, "TraceableCAVLCParser", FakeTraceableParser)

    coefficients, frame_data, _nc, _lengths, _t1 = pipeline.extract_all_idr_blocks(
        "unused.h264", FakeReconstructor(), parser=parser
    )

    original_blocks = frame_data[0][1]
    assert coefficients[0][2] is original_blocks[(0, 0)]


def test_embedder_keeps_shared_source_vectors_immutable() -> None:
    source_vectors = [[0, 2, 0] + [0] * 13 for _ in range(8)]
    coefficients = [(index, 0, vector) for index, vector in enumerate(source_vectors)]
    original = [tuple(vector) for vector in source_vectors]
    positions = [(index, 0, 1) for index in range(8)]

    modified, bits_embedded = PayloadEmbedder().embed_payload(
        coefficients,
        b"x",
        pre_validated_positions=positions,
    )

    assert bits_embedded == 8
    assert modified
    assert [tuple(vector) for vector in source_vectors] == original
