from __future__ import annotations

from pathlib import Path

import pytest

from src.core import analysis_cache


@pytest.mark.parametrize("rebuild_same_video", [False, True])
def test_new_video_evicts_previous_analysis_before_parsing(
    tmp_path: Path,
    monkeypatch,
    rebuild_same_video: bool,
) -> None:
    old_video = tmp_path / "previous.h264"
    new_video = old_video if rebuild_same_video else tmp_path / "current.h264"
    old_video.write_bytes(b"old")
    if not rebuild_same_video:
        new_video.write_bytes(b"new")
    old_key = str(old_video.resolve())
    new_key = str(new_video.resolve())

    analysis_cache.clear_video_analysis_cache()
    analysis_cache._VIDEO_ANALYSIS_CACHE[old_key] = ({}, ("large old analysis",))
    analysis_cache._RECONSTRUCTION_CONTEXT_CACHE[old_key] = ({}, {"old": "parser"})

    class FakeParser:
        def __init__(self, _path: str) -> None:
            self.nal_units = []

        def parse(self) -> None:
            assert old_key not in analysis_cache._VIDEO_ANALYSIS_CACHE
            assert old_key not in analysis_cache._RECONSTRUCTION_CONTEXT_CACHE

    class FakeSafetyFilter:
        def get_safe_positions(self, *_args, **_kwargs) -> list:
            return []

    monkeypatch.setattr(analysis_cache, "H264BitstreamParser", FakeParser)
    monkeypatch.setattr(analysis_cache, "CAVLCSafetyFilter", FakeSafetyFilter)
    monkeypatch.setattr(
        analysis_cache,
        "extract_all_idr_blocks",
        lambda *_args, **_kwargs: ([], {}, {}, {}, {}),
    )
    monkeypatch.setattr(
        analysis_cache,
        "_build_reconstruction_context",
        lambda _path, parser=None: {"parser": parser},
    )

    result = analysis_cache.load_or_build_video_analysis(
        new_video,
        force_refresh=rebuild_same_video,
    )

    assert result == ([], {}, {}, {}, {}, [])
    assert list(analysis_cache._VIDEO_ANALYSIS_CACHE) == [new_key]
    assert list(analysis_cache._RECONSTRUCTION_CONTEXT_CACHE) == [new_key]
    analysis_cache.clear_video_analysis_cache()
