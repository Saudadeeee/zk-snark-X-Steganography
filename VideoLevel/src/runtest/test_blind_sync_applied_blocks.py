from __future__ import annotations

from pathlib import Path

import pytest

from src import blind_sync
from src.bitstream.bitstream_ops import BitstreamReconstructor


def test_blind_embed_fails_closed_when_reconstruction_skips_a_changed_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "cover.h264"
    source.write_bytes(b"cover fixture")
    output = tmp_path / "stego.h264"
    contract = blind_sync.BlindOperatingContract(
        require_bitstream_patchable=True,
        stable_carriers_only=True,
    )
    metadata = blind_sync.BlindPublicMetadata(
        version="test-v1",
        codec="h264",
        profile="baseline-cavlc",
        idr_count=1,
        raw_safe_bits=1,
        patchable_block_count=1,
        stable_candidate_count=1,
        candidate_fingerprint="0" * 64,
    )

    monkeypatch.setattr(
        blind_sync,
        "load_or_build_video_analysis",
        lambda *_args, **_kwargs: ([(0, 0, [0, 4])], {0: ({}, {}, b"")}, {}, {}, {}, []),
    )
    monkeypatch.setattr(
        blind_sync,
        "derive_blind_positions_operating_contract",
        lambda _path, _key, required_bits, *_args, **_kwargs: (
            [(0, 0, 1)] * required_bits,
            metadata,
        ),
    )

    class FakeEmbedder:
        def __init__(self, **_kwargs) -> None:
            self.last_modified_safe_positions = [(0, 0, 1)]

        def embed_payload(self, _coefficients, envelope, **_kwargs):
            return [(0, 0, [0, 5])], len(envelope) * 8

    monkeypatch.setattr("src.core.stego.PayloadEmbedder", FakeEmbedder)

    def reconstruct_video(_self, _source, _modified, candidate, **_kwargs):
        Path(candidate).write_bytes(b"valid-looking but unchanged candidate")
        return {
            "success": True,
            "applied_block_keys": [],
            "skipped_block_reasons": {
                (0, 0): "modified_bits_break_predecessor_decode_boundary"
            },
        }

    monkeypatch.setattr(BitstreamReconstructor, "reconstruct_video", reconstruct_video)
    monkeypatch.setattr(
        "src.embedder._strict_validate_h264_decode",
        lambda _path: None,
    )

    with pytest.raises(
        RuntimeError,
        match="modified_bits_break_predecessor_decode_boundary",
    ):
        blind_sync.embed_blind_video_payload(
            str(source), str(output), b"payload", b"sync-key", contract
        )

    assert not output.exists()
