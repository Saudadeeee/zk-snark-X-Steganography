"""Shared pytest configuration for VideoLevel.

Some integration tests read local, gitignored H.264 covers under ``data/``.
On a clean checkout (CI, a reviewer's machine before ``scripts/prepare_data``)
those tests are skipped with the missing path as the reason instead of failing.

A test opts in with ``@pytest.mark.needs_data("data/encoded/<file>", ...)``
(the marker is registered in ``pytest.ini``).
Tests written before the marker existed are listed in ``KNOWN_DATA_TESTS``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent

# node id suffix -> data files the test reads (paths relative to VideoLevel/)
KNOWN_DATA_TESTS: dict[str, tuple[str, ...]] = {
    "test_video_only_blind_sync_integration.py::test_stego_video_alone_rederives_carriers_and_extracts_payload": (
        "data/encoded/foreman_cif_g8_300f_b800k.h264",
    ),
}


def _required_paths(item: pytest.Item) -> tuple[str, ...]:
    paths: list[str] = []
    for marker in item.iter_markers(name="needs_data"):
        paths.extend(str(path) for path in marker.args)
    for suffix, known in KNOWN_DATA_TESTS.items():
        if item.nodeid.endswith(suffix):
            paths.extend(known)
    return tuple(paths)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        missing = [path for path in _required_paths(item) if not (ROOT / path).is_file()]
        if missing:
            item.add_marker(pytest.mark.skip(reason=f"local data not present: {', '.join(missing)}"))
