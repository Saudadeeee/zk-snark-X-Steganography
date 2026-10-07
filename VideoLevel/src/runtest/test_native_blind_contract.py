"""Cross-language vectors for the native CAVLC blind channel contract (protocol v3).

Every hex constant below is also asserted by native/tests/cavlc_stream_tests.cpp,
so the Python reference and the native implementation are pinned to one value.
"""

import hashlib
import hmac
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.native_blind_contract import (
    FRAME_VERSION,
    ChannelKeys,
    NativeCavlcCandidate,
    bits_to_bytes,
    bytes_to_bits,
    candidate_tier,
    channel_flags,
    derive_channel_keys,
    derive_video_channel_keys,
    embedded_frame_bits,
    hkdf_expand,
    hkdf_extract,
    hkdf_sha256,
    pack_frame,
    parse_candidate_identity,
    recover_payload,
    scan_frequency,
    score_candidate,
    secret_line,
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


def t_candidate_tier_and_scan_frequency() -> None:
    # (category, mb_row, mb_height, freq) -> tier; mirrors native cavlc_candidate_tier.
    cases = {
        (0, 0, 18, 6): 4,   # LumaDC, top third
        (2, 17, 18, 2): 2,  # ChromaDC, bottom third (DC never earns the frequency term)
        (1, 5, 18, 0): 3,   # Luma4x4 top third (15 < 18), low frequency
        (1, 6, 18, 2): 2,   # middle third (18 < 36), freq 2 still counts
        (3, 11, 18, 3): 1,  # ChromaAC middle third, high frequency
        (3, 12, 18, 6): 0,  # bottom third (36 is not < 36)
    }
    for inputs, tier in cases.items():
        assert candidate_tier(*inputs) == tier, (inputs, tier)
    assert max(candidate_tier(c, r, 18, f) for c in range(4) for r in range(18) for f in range(7)) == 4
    expect_value_error(lambda: candidate_tier(1, -1, 18, 0))
    # Last non-zero coefficient in scan order -> i + j of its raster position.
    assert scan_frequency(1, [5, 0, -1] + [0] * 13) == 1           # zig-zag 2 = (1, 0)
    assert scan_frequency(1, [1, 0, 0, 0, 0, 1] + [0] * 10) == 2   # zig-zag 5 = (0, 2)
    assert scan_frequency(1, [0] * 15 + [1]) == 6                  # zig-zag 15 = (3, 3)
    assert scan_frequency(3, [0, 0, 0, 0, -1] + [0] * 10) == 2     # AC: scan 4 = zig-zag 5
    assert scan_frequency(1, [1] + [0] * 14) == 1                  # I16x16 AC: scan 0 = zig-zag 1
    assert scan_frequency(2, [3, 0, 1, 0]) == 1                    # ChromaDC c2 = (1, 0)
    assert scan_frequency(0, [0, 0, 0, 1] + [0] * 12) == 2         # LumaDC uses the 4x4 zig-zag
    expect_value_error(lambda: scan_frequency(1, [0] * 16))
    expect_value_error(lambda: scan_frequency(2, [1] * 16))


def t_low_drift_selection_orders_by_tier() -> None:
    candidates = [NativeCavlcCandidate(4, mb, 1, block, 100 * mb + block) for mb in range(6) for block in range(4)]
    tiers = {c: (c.macroblock_address + c.block_index) % 4 for c in candidates}
    selected = select_candidates(candidates, KEY, 10, "low-drift", tiers)
    expected = sorted(candidates, key=lambda c: (tiers[c], score_candidate(c, KEY), c.serialize()))[:10]
    assert selected == expected
    assert [tiers[c] for c in selected] == sorted(tiers[c] for c in selected)
    assert max(tiers[c] for c in selected) <= min(tiers[c] for c in candidates if c not in selected)
    # Random ignores tiers; low-drift with equal tiers is the random order.
    assert select_candidates(candidates, KEY, 10) == select_candidates(candidates, KEY, 10, "random", tiers)
    assert select_candidates(candidates, KEY, 10, "low-drift", {c: 3 for c in candidates}) == \
        select_candidates(candidates, KEY, 10)
    expect_value_error(lambda: select_candidates(candidates, KEY, 3, "low-drift"))
    expect_value_error(lambda: select_candidates(candidates, KEY, 3, "lowest"))
    # segment_schedule reads the tier inputs from the --segments JSON.
    document = _segments_json([candidates])
    for item, candidate in zip(document["segments"][0]["candidates"], candidates):
        item.update({"mb_row": tiers[candidate], "mb_height": 3, "freq": 6})  # tier = r: 2/1/0
    native_tiers = {c: candidate_tier(c.category, tiers[c], 3, 6) for c in candidates}
    placements = segment_schedule(document, KEY, 7, 10, "low-drift")
    assert [p.candidate.identity for p in placements] == select_candidates(candidates, KEY, 7, "low-drift", native_tiers)
    tampered = json.loads(json.dumps(document))
    tampered["segments"][0]["candidates"][0]["tier"] = 5
    expect_value_error(lambda: segment_schedule(tampered, KEY, 3, 10, "low-drift"))
    expect_value_error(lambda: segment_schedule(_segments_json([candidates]), KEY, 3, 10, "low-drift"))


def t_per_video_keys_and_token() -> None:
    nonce = hashlib.sha256(b"video").digest()
    keys = derive_video_channel_keys(KEY, nonce)
    # Single-block HKDF written out: PRK, video_key, then the two subkeys.
    prk = hmac.new(b"zkstego-cavlc-v4-salt", KEY, hashlib.sha256).digest()
    video_key = hmac.new(prk, b"zkstego/cavlc/v4/video" + nonce + b"\x01", hashlib.sha256).digest()
    assert keys.schedule_key == hmac.new(video_key, b"zkstego/cavlc/v4/schedule\x01", hashlib.sha256).digest()
    assert keys.whitening_key == hmac.new(video_key, b"zkstego/cavlc/v4/whitening\x01", hashlib.sha256).digest()
    master = derive_channel_keys(KEY)
    assert len({keys.schedule_key, keys.whitening_key, master.schedule_key, master.whitening_key}) == 4
    assert derive_video_channel_keys(KEY, hashlib.sha256(b"other").digest()) != keys
    assert derive_video_channel_keys(WRONG_KEY, nonce) != keys
    expect_value_error(lambda: derive_video_channel_keys(KEY, nonce[:31]))
    # Token round trip; derived keys drive every keyed function like the master key does.
    token = keys.token()
    assert len(token) == 64 and ChannelKeys.from_token(token) == keys
    expect_value_error(lambda: ChannelKeys.from_token(token[:63]))
    assert score_candidate(CANDIDATES[0], master) == score_candidate(CANDIDATES[0], KEY)
    assert whitening_keystream(master, 40).hex() == KEYSTREAM_40_HEX
    assert recover_payload(embedded_frame_bits(b"proof", keys), ChannelKeys.from_token(token), 32) == b"proof"
    document = _segments_json([[NativeCavlcCandidate(4, mb, 1, 0, mb) for mb in range(8)]])
    assert segment_schedule(document, master, 5, 8) == segment_schedule(document, KEY, 5, 8)
    assert segment_schedule(document, keys, 5, 8) != segment_schedule(document, KEY, 5, 8)
    # Native CLI stdin line and flags: defaults add nothing; a token needs per-video.
    assert channel_flags() == []
    assert channel_flags("low-drift", "per-video") == ["--select", "low-drift", "--key-mode", "per-video"]
    assert secret_line(KEY) == KEY.hex().encode("ascii") + b"\n"
    assert secret_line(token, "per-video") == b"token:" + token.hex().encode("ascii") + b"\n"
    expect_value_error(lambda: secret_line(token))
    expect_value_error(lambda: secret_line(KEY[:31]))
    expect_value_error(lambda: channel_flags("lowdrift"))


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
        run_test("low-drift tier and scan frequency", t_candidate_tier_and_scan_frequency),
        run_test("low-drift selection orders by tier", t_low_drift_selection_orders_by_tier),
        run_test("per-video keys and verification token", t_per_video_keys_and_token),
    ]
    sys.exit(summarise(results, "Native blind contract"))
