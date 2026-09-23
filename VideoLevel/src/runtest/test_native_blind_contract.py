"""Cross-language vectors for the native CAVLC blind schedule/frame contract."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.native_blind_contract import (
    NativeCavlcCandidate,
    pack_authenticated_frame,
    score_candidate,
    select_candidates,
    unpack_authenticated_frame,
)
from src.runtest._helpers import run_test, section, summarise

KEY = bytes(range(32))
CANDIDATES = [
    NativeCavlcCandidate(7, 11, 1, 3, 91),
    NativeCavlcCandidate(3, 2, 3, 0, 12),
    NativeCavlcCandidate(7, 11, 1, 2, 90),
]


def t_schedule_matches_native_vector() -> None:
    assert CANDIDATES[0].serialize() == b"7:11:1:3:91"
    assert score_candidate(CANDIDATES[0], KEY).hex() == "8778f4c4c455d75b5f8f6e7aae7765b1f586585e4e82047fb2c5eb9eceaf33f3"
    assert select_candidates(CANDIDATES, KEY, 3) == [CANDIDATES[1], CANDIDATES[2], CANDIDATES[0]]
    try:
        NativeCavlcCandidate(1.0, 2, 1, 0, 3)
    except ValueError:
        pass
    else:
        raise AssertionError("non-integer candidate field must reject")
    try:
        select_candidates([CANDIDATES[0], NativeCavlcCandidate(7, 12, 1, 3, 91)], KEY, 1)
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate physical patch target must reject")


def t_frame_round_trip_and_wrong_key_rejection() -> None:
    frame = pack_authenticated_frame(b"proof", KEY)
    assert frame.hex() == "01000570726f6f66fe20deac399e5f3a59f5bac9eda85136"
    assert unpack_authenticated_frame(frame, KEY, 32) == b"proof"
    try:
        unpack_authenticated_frame(frame, b"\x01" * 32, 32)
    except ValueError:
        return
    raise AssertionError("wrong key must reject authenticated frame")


if __name__ == "__main__":
    section("Native blind contract")
    results = [
        run_test("native schedule vector", t_schedule_matches_native_vector),
        run_test("native authenticated frame", t_frame_round_trip_and_wrong_key_rejection),
    ]
    sys.exit(summarise(results, "Native blind contract"))
