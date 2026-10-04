"""Cross-language vectors for the native CAVLC blind channel contract (protocol v3).

Every hex constant below is also asserted by native/tests/cavlc_stream_tests.cpp,
so the Python reference and the native implementation are pinned to one value.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.native_blind_contract import (
    FRAME_VERSION,
    NativeCavlcCandidate,
    bits_to_bytes,
    bytes_to_bits,
    derive_channel_keys,
    embedded_frame_bits,
    hkdf_expand,
    hkdf_extract,
    hkdf_sha256,
    pack_frame,
    parse_candidate_identity,
    recover_payload,
    score_candidate,
    segment_schedule,
    select_candidates,
    unpack_frame,
    unwhiten_bits,
    whiten_bits,
    whiten_frame,
    whitening_keystream,
    whitening_keystream_bits,
)
from src.runtest._helpers import run_test, section, summarise

KEY = bytes(range(32))
WRONG_KEY = b"\x01" * 32
CANDIDATES = [
    NativeCavlcCandidate(7, 11, 1, 3, 91),
    NativeCavlcCandidate(3, 2, 3, 0, 12),
    NativeCavlcCandidate(7, 11, 1, 2, 90),
]
# Shared with native/tests/cavlc_stream_tests.cpp.
SCHEDULE_KEY_HEX = "4a1b2cca526bfa4c0520204dcc4217d272ccedff432f3867de33802a02688abe"
WHITENING_KEY_HEX = "488d024d53ee15a468b5659cefa82f9be00d2e9820f29df8bf60f61361ab5a74"
FIRST_SCORE_HEX = "bf5e312df3c9d85bfbbcaa20bbc605fdccdaa9ce1d5f9b16ea68aceed407d83b"
FRAME_HEX = "03000570726f6f66"
WHITENED_FRAME_HEX = "487a9db6a217155e"
KEYSTREAM_40_HEX = "4b7a98c6d0787a381bbbb861c9a124af090cdb9b1870d7ee14f74a01635401e68660dff97f10007b"


def expect_value_error(operation) -> None:
    try:
        operation()
    except ValueError:
        return
    raise AssertionError("operation must raise ValueError")


def t_hkdf_rfc5869_case_1() -> None:
    ikm, salt, info = b"\x0b" * 22, bytes(range(13)), bytes(range(0xF0, 0xFA))
    prk = hkdf_extract(salt, ikm)
    assert prk.hex() == "077709362c2e32df0ddc3f0dc47bba6390b6c73bb50f9c3122ec844ad7c2b3e5"
    okm = "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865"
    assert hkdf_expand(prk, info, 42).hex() == okm
    assert hkdf_sha256(salt, ikm, info, 42).hex() == okm


def t_subkeys_match_native_vector() -> None:
    keys = derive_channel_keys(KEY)
    assert keys.schedule_key.hex() == SCHEDULE_KEY_HEX
    assert keys.whitening_key.hex() == WHITENING_KEY_HEX
    assert len({keys.schedule_key, keys.whitening_key, KEY}) == 3
    expect_value_error(lambda: derive_channel_keys(b"\x00" * 31))


def t_schedule_matches_native_vector() -> None:
    assert CANDIDATES[0].serialize() == b"7:11:1:3:91"
    assert score_candidate(CANDIDATES[0], KEY).hex() == FIRST_SCORE_HEX
    assert select_candidates(CANDIDATES, KEY, 3) == [CANDIDATES[1], CANDIDATES[0], CANDIDATES[2]]
    assert select_candidates(CANDIDATES, WRONG_KEY, 1) == [CANDIDATES[2]]
    expect_value_error(lambda: NativeCavlcCandidate(1.0, 2, 1, 0, 3))
    expect_value_error(lambda: select_candidates([CANDIDATES[0], NativeCavlcCandidate(7, 12, 1, 3, 91)], KEY, 1))


def t_frame_round_trip_and_header_checks() -> None:
    frame = pack_frame(b"proof")
    assert frame[0] == FRAME_VERSION == 3
    assert frame.hex() == FRAME_HEX
    assert unpack_frame(frame, 32) == b"proof"
    # The v3 frame has no MAC: only the header is checked. A v2 frame, a payload
    # above the maximum and a length that disagrees with the frame are refused.
    expect_value_error(lambda: unpack_frame(b"\x02" + frame[1:], 32))
    expect_value_error(lambda: unpack_frame(frame, 4))
    expect_value_error(lambda: unpack_frame(frame[:-1], 32))
    expect_value_error(lambda: pack_frame(bytes(0x10000)))


def t_whitening_vector_and_round_trip() -> None:
    assert whitening_keystream(KEY, 40).hex() == KEYSTREAM_40_HEX
    # Keystream offsets are global: a window starting mid-block equals the slice.
    assert whitening_keystream(KEY, 13, 27) == bytes.fromhex(KEYSTREAM_40_HEX)[27:40]
    assert whitening_keystream_bits(KEY, 20, 37) == bytes_to_bits(bytes.fromhex(KEYSTREAM_40_HEX))[37:57]
    frame = bytes.fromhex(FRAME_HEX)
    assert whiten_frame(frame, KEY).hex() == WHITENED_FRAME_HEX
    embedded = embedded_frame_bits(b"proof", KEY)
    assert bits_to_bytes(embedded).hex() == WHITENED_FRAME_HEX
    assert bits_to_bytes(unwhiten_bits(embedded, KEY)) == frame
    # Whitening split across segments (bit index stays global) equals one pass.
    split = whiten_bits(bytes_to_bits(frame)[:29], KEY) + whiten_bits(bytes_to_bits(frame)[29:], KEY, 29)
    assert split == embedded
    assert recover_payload(embedded, KEY, 32) == b"proof"


def t_wrong_key_rejects_whitened_frame() -> None:
    embedded = embedded_frame_bits(b"proof", KEY)
    header = bits_to_bytes(unwhiten_bits(embedded[:24], WRONG_KEY))
    assert header[0] != FRAME_VERSION
    try:
        recover_payload(embedded, WRONG_KEY, 32)
    except ValueError as error:
        assert "CAVLC frame" in str(error)
    else:
        raise AssertionError("wrong key must reject a whitened frame")


def t_header_bits_look_unrelated() -> None:
    # Same key, two payloads: plaintext headers share the version byte, but
    # the embedded bits differ only where the plaintext differs (fixed
    # keystream) and the embedded version byte is no longer the constant 0x03.
    first = bits_to_bytes(embedded_frame_bits(b"proof", KEY))
    second = bits_to_bytes(embedded_frame_bits(bytes(300), KEY))
    assert first[0] == second[0] != FRAME_VERSION
    assert first[1:3] != second[1:3]
    # Across keys the embedded header changes completely.
    other = bits_to_bytes(embedded_frame_bits(b"proof", WRONG_KEY))
    assert other[:3] != first[:3]
    # Over many keys the embedded version byte is spread, not pinned to 0x03.
    versions = {whiten_frame(pack_frame(b"x"), bytes([seed]) * 32)[0]
                for seed in range(64)}
    assert len(versions) > 32


def _segments_json(segment_candidates: list[list[NativeCavlcCandidate]]) -> dict:
    """Synthetic zkstego_inspect --segments document (file NAL = 10 * segment + 3)."""
    return {
        "schema": "segments-1",
        "segments": [
            {
                "segment": index,
                "idr_nal_index": 10 * index + 3,
                "candidates": [
                    {"id": c.serialize().decode("ascii"), "nal_index": 10 * index + 3,
                     "rbsp_bit_offset": c.rbsp_bit_offset, "bit": c.rbsp_bit_offset % 2}
                    for c in candidates
                ],
            }
            for index, candidates in enumerate(segment_candidates)
        ],
    }


def t_segment_schedule_matches_per_segment_selection() -> None:
    first = [NativeCavlcCandidate(4, mb, 1, block, 100 * mb + block) for mb in range(3) for block in range(4)]
    second = [NativeCavlcCandidate(4, mb, 3, block, 50 * mb + block) for mb in range(2) for block in range(3)]
    third = [NativeCavlcCandidate(4, 0, 0, 0, 7)]
    document = _segments_json([first, [], second, third])
    placements = segment_schedule(document, KEY, 11, 5)
    # Segment 0 carries 5 bits, the empty segment none, segment 2 caps at 5,
    # segment 3 carries the last bit; frame-bit indices continue globally.
    assert [p.frame_bit_index for p in placements] == list(range(11))
    expected = (
        [(0, c) for c in select_candidates(first, KEY, 5)]
        + [(2, c) for c in select_candidates(second, KEY, 5)]
        + [(3, third[0])]
    )
    assert [(p.segment, p.candidate.identity) for p in placements] == expected
    assert placements[0].candidate.nal_index == 3 and placements[5].candidate.nal_index == 23
    # A frame ending mid-segment uses a prefix of that segment's schedule.
    short = segment_schedule(document, KEY, 3, 5)
    assert [p.candidate.identity for p in short] == select_candidates(first, KEY, 3)
    assert segment_schedule(document, KEY, 0, 5) == []
    # The JSON may also arrive as text, exactly as the tool prints it.
    assert segment_schedule(json.dumps(document), KEY, 3, 5) == short
    # Different key, different schedule; capacity and input validation.
    assert [p.candidate.identity for p in segment_schedule(document, WRONG_KEY, 5, 5)] !=         [p.candidate.identity for p in placements[:5]]
    expect_value_error(lambda: segment_schedule(document, KEY, 12, 5))  # capacity is 11
    expect_value_error(lambda: segment_schedule(document, KEY, 3, 0))
    expect_value_error(lambda: segment_schedule({**document, "schema": 1}, KEY, 3, 5))
    tampered = _segments_json([first])
    tampered["segments"][0]["candidates"][0]["rbsp_bit_offset"] += 1
    expect_value_error(lambda: segment_schedule(tampered, KEY, 3, 5))
    assert parse_candidate_identity("7:11:1:3:91") == CANDIDATES[0]
    expect_value_error(lambda: parse_candidate_identity("7:11:1:3"))
    expect_value_error(lambda: parse_candidate_identity("07:11:1:3:91"))


if __name__ == "__main__":
    section("Native blind contract (protocol v3)")
    results = [
        run_test("HKDF-SHA256 RFC 5869 test case 1", t_hkdf_rfc5869_case_1),
        run_test("subkey vector", t_subkeys_match_native_vector),
        run_test("native schedule vector", t_schedule_matches_native_vector),
        run_test("native v3 frame and header checks", t_frame_round_trip_and_header_checks),
        run_test("whitening vector and round trip", t_whitening_vector_and_round_trip),
        run_test("wrong key rejects whitened frame", t_wrong_key_rejects_whitened_frame),
        run_test("embedded header bits are keystream-masked", t_header_bits_look_unrelated),
        run_test("segment schedule reproduces per-IDR selection", t_segment_schedule_matches_per_segment_selection),
    ]
    sys.exit(summarise(results, "Native blind contract"))
