"""Cross-platform fixture E2E for the native keyed CAVLC segment protocol (v3).

1. ``zkstego_blind_bits embed-stream-auth-stdin`` / ``extract-stream-auth`` round
   trip on a real H.264 fixture, strict FFmpeg decode, wrong key rejected.
2. The Python ``segment_schedule`` reproduces the native encoder exactly from
   ``zkstego_inspect --segments``: every placed stego sign equals
   ``frame_bit XOR keystream_bit`` and every other candidate sign is unchanged.
3. ``zkstego_blind_bits video-digest`` equals the Python reference
   (``src/video_binding.py``), is the same for the cover and the stego video,
   and changes with its parameters and with any other video.
4. Channel parameters: for every selection policy (random | low-drift) and key
   mode (master | per-video) the Python mirror reproduces the native encoder,
   digest and verification token; the tier inputs in ``--segments`` match the
   full trace; and a low-drift + per-video file round-trips through the CLI with
   the key or the video's token (another video's token fails).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.native_blind_contract import (
    bytes_to_bits,
    channel_flags,
    embedded_frame_bits,
    pack_frame,
    scan_frequency,
    secret_line,
    segment_candidates,
    segment_schedule,
    whitening_keystream_bits,
)
from src.runtest._helpers import SKIP, run_test, section, summarise
from src.video_binding import (
    native_video_digest,
    native_video_token,
    resolve_channel_keys,
    video_digest,
    video_nonce,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "data" / "encoded" / "foreman_cif_q18_g1_300f.h264"
# 50-frame all-IDR fixture: small enough to embed once per channel-parameter combination.
SMALL_FIXTURE = ROOT / "data" / "encoded" / "foreman_cif_q22_g1.h264"
CHANNEL_OPTIONS = [(select, key_mode) for select in ("random", "low-drift") for key_mode in ("master", "per-video")]
_EXE = ".exe" if os.name == "nt" else ""
_BUILD = ROOT / "native" / "build" / "Release" if os.name == "nt" else ROOT / "native" / "edge-build"
DEFAULT_CLI = _BUILD / f"zkstego_blind_bits{_EXE}"
DEFAULT_INSPECT = _BUILD / f"zkstego_inspect{_EXE}"
SECRET_KEY = bytes(range(32))
WRONG_KEY = bytes([0xA7]) * 32
PAYLOAD = b"native-cli-proof-e2e"
MAX_BITS_PER_IDR = 64


def _tool(env_name: str, default: Path) -> Path:
    return Path(os.environ.get(env_name, default))


def _embed(cli: Path, cover: Path, stego: Path, flags: list[str] | None = None) -> None:
    embed = subprocess.run(
        [str(cli), "embed-stream-auth-stdin", str(cover), str(stego), str(MAX_BITS_PER_IDR), *(flags or [])],
        input=SECRET_KEY.hex().encode("ascii") + b"\n" + PAYLOAD.hex().encode("ascii") + b"\n",
        capture_output=True,
        check=False,
        timeout=180,
    )
    assert embed.returncode == 0, embed.stderr.decode("utf-8", errors="replace")
    assert stego.is_file() and stego.stat().st_size > 0


def _extract(cli: Path, stego: Path, key: bytes, flags: list[str] | None = None,
             key_mode: str = "master") -> subprocess.CompletedProcess[bytes]:
    # key is K (32 bytes) or, with key_mode="per-video", a 64-byte verification token.
    line = secret_line(key, key_mode) if len(key) == 64 else key.hex().encode("ascii") + b"\n"
    return subprocess.run(
        [str(cli), "extract-stream-auth", str(stego), "-", "4096", str(MAX_BITS_PER_IDR), *(flags or [])],
        input=line,
        capture_output=True,
        check=False,
        timeout=180,
    )


def _segments(inspect: Path, video: Path) -> dict:
    result = subprocess.run(
        [str(inspect), str(video), "--segments", str(MAX_BITS_PER_IDR)],
        capture_output=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return json.loads(result.stdout)


def t_native_cli_stream_embed_extract_and_strict_decode() -> None:
    cli = _tool("ZK_STEGO_NATIVE_CLI", DEFAULT_CLI)
    if not cli.is_file():
        SKIP("native_cli_stream_fixture_e2e", f"native CLI not found: {cli}")
        return
    if shutil.which("ffmpeg") is None:
        SKIP("native_cli_stream_fixture_e2e", "ffmpeg not found on PATH")
        return
    if not FIXTURE.is_file():
        SKIP("native_cli_stream_fixture_e2e", f"fixture not found: {FIXTURE}")
        return

    with tempfile.TemporaryDirectory(prefix="zkstego-native-cli-e2e-") as temp_dir:
        stego_path = Path(temp_dir) / "stego.h264"
        _embed(cli, FIXTURE, stego_path)

        strict_decode = subprocess.run(
            ["ffmpeg", "-v", "error", "-xerror", "-f", "h264", "-i", str(stego_path), "-f", "null", "-"],
            capture_output=True,
            check=False,
            timeout=120,
        )
        assert strict_decode.returncode == 0, strict_decode.stderr.decode("utf-8", errors="replace")

        correct_key = _extract(cli, stego_path, SECRET_KEY)
        assert correct_key.returncode == 0, correct_key.stderr.decode("utf-8", errors="replace")
        assert correct_key.stdout.strip().decode("ascii") == PAYLOAD.hex()

        wrong_key = _extract(cli, stego_path, WRONG_KEY)
        assert wrong_key.returncode != 0, "native extraction accepted a wrong key"
        print(
            "NATIVE_CLI_FIXTURE_METRICS "
            f"strict_ffmpeg_exit={strict_decode.returncode} "
            f"stego_bytes={stego_path.stat().st_size} max_bits_per_idr={MAX_BITS_PER_IDR} "
            f"payload_bytes={len(PAYLOAD)} correct_key_match=true wrong_key_rejected=true"
        )


def t_python_segment_schedule_matches_native_encoder() -> None:
    cli = _tool("ZK_STEGO_NATIVE_CLI", DEFAULT_CLI)
    inspect = _tool("ZK_STEGO_NATIVE_INSPECT", DEFAULT_INSPECT)
    if not cli.is_file() or not inspect.is_file():
        SKIP("python_segment_schedule_matches_native", f"native tools not found: {cli}, {inspect}")
        return
    if not FIXTURE.is_file():
        SKIP("python_segment_schedule_matches_native", f"fixture not found: {FIXTURE}")
        return

    with tempfile.TemporaryDirectory(prefix="zkstego-native-schedule-") as temp_dir:
        stego_path = Path(temp_dir) / "stego.h264"
        _embed(cli, FIXTURE, stego_path)
        cover = _segments(inspect, FIXTURE)
        stego = _segments(inspect, stego_path)

    # The sign edits keep every segment's candidate identities and locations.
    def layout(document: dict) -> list:
        return [
            (segment["idr_nal_index"], [(c["id"], c["nal_index"], c["rbsp_bit_offset"]) for c in segment["candidates"]])
            for segment in document["segments"]
        ]

    assert layout(cover) == layout(stego)
    assert cover["candidate_capacity_bits"] == sum(
        min(MAX_BITS_PER_IDR, len(segment["candidates"])) for segment in cover["segments"]
    )

    frame_bits = bytes_to_bits(pack_frame(PAYLOAD))
    keystream = whitening_keystream_bits(SECRET_KEY, len(frame_bits))
    embedded = embedded_frame_bits(PAYLOAD, SECRET_KEY)
    placements = segment_schedule(cover, SECRET_KEY, len(frame_bits), MAX_BITS_PER_IDR)
    # A blind receiver rebuilds the same schedule from the stego file alone.
    assert [(p.segment, p.candidate.identity) for p in placements] == [
        (p.segment, p.candidate.identity)
        for p in segment_schedule(stego, SECRET_KEY, len(frame_bits), MAX_BITS_PER_IDR)
    ]
    assert [p.frame_bit_index for p in placements] == list(range(len(frame_bits)))

    stego_bits = {
        (segment["segment"], c["id"]): c["bit"] for segment in stego["segments"] for c in segment["candidates"]
    }
    placed = set()
    for placement in placements:
        key = (placement.segment, placement.candidate.identity.serialize().decode("ascii"))
        index = placement.frame_bit_index
        assert stego_bits[key] == frame_bits[index] ^ keystream[index] == embedded[index], placement
        placed.add(key)

    changed = 0
    for segment in cover["segments"]:
        for candidate in segment["candidates"]:
            key = (segment["segment"], candidate["id"])
            if key in placed:
                changed += candidate["bit"] != stego_bits[key]
            else:
                assert candidate["bit"] == stego_bits[key], f"unscheduled sign changed: {key}"
    assert changed > 0, "embedding flipped no scheduled sign"
    segments_used = len({p.segment for p in placements})
    print(
        "NATIVE_SCHEDULE_MATCH "
        f"frame_bits={len(frame_bits)} segments_used={segments_used} "
        f"placed_signs_flipped={changed} unscheduled_signs_changed=0"
    )


def t_video_digest_matches_reference_and_survives_embedding() -> None:
    cli, inspect = _tool("ZK_STEGO_NATIVE_CLI", DEFAULT_CLI), _tool("ZK_STEGO_NATIVE_INSPECT", DEFAULT_INSPECT)
    if not cli.is_file() or not inspect.is_file() or not FIXTURE.is_file():
        SKIP("video_digest_matches_reference", "native tools or fixture missing")
    frame_bits = len(bytes_to_bits(pack_frame(PAYLOAD)))
    segments = json.loads(subprocess.run([str(inspect), str(FIXTURE), "--segments", str(MAX_BITS_PER_IDR)],
                                         capture_output=True, check=True, timeout=300).stdout)
    native = native_video_digest(cli, FIXTURE, SECRET_KEY, frame_bits, MAX_BITS_PER_IDR)
    assert native == video_digest(FIXTURE.read_bytes(), segments, SECRET_KEY, frame_bits, MAX_BITS_PER_IDR)
    assert native != native_video_digest(cli, FIXTURE, SECRET_KEY, frame_bits + 8, MAX_BITS_PER_IDR)
    assert native != native_video_digest(cli, FIXTURE, SECRET_KEY, frame_bits, MAX_BITS_PER_IDR // 2)
    assert native != native_video_digest(cli, FIXTURE, WRONG_KEY, frame_bits, MAX_BITS_PER_IDR)
    with tempfile.TemporaryDirectory() as temp_dir:
        stego = Path(temp_dir) / "stego.h264"
        _embed(cli, FIXTURE, stego)
        assert native_video_digest(cli, stego, SECRET_KEY, frame_bits, MAX_BITS_PER_IDR) == native, \
            "embedding changed the digest"
        data = stego.read_bytes()
        truncated = Path(temp_dir) / "truncated.h264"
        truncated.write_bytes(data[: len(data) * 3 // 4])
        assert native_video_digest(cli, truncated, SECRET_KEY, frame_bits, MAX_BITS_PER_IDR) != native, \
            "truncation kept the digest"
    print(f"VIDEO_DIGEST frame_bits={frame_bits} digest={native.hex()[:16]}... cover==stego")


def _signs(document: dict) -> dict[tuple[int, int], int]:
    """(file NAL, RBSP bit) -> sign bit of every candidate listed by --segments."""
    return {(c["nal_index"], c["rbsp_bit_offset"]): c["bit"] for s in document["segments"] for c in s["candidates"]}


def t_python_mirror_matches_native_for_channel_options() -> None:
    """Python schedule, whitening, nonce, token and digest == native, for all four parameter sets."""
    cli, inspect = _tool("ZK_STEGO_NATIVE_CLI", DEFAULT_CLI), _tool("ZK_STEGO_NATIVE_INSPECT", DEFAULT_INSPECT)
    if not cli.is_file() or not inspect.is_file() or not SMALL_FIXTURE.is_file():
        SKIP("python_mirror_matches_native_for_channel_options", "native tools or fixture missing")
    cover_bytes = SMALL_FIXTURE.read_bytes()
    cover = _segments(inspect, SMALL_FIXTURE)
    frame_bits = len(bytes_to_bits(pack_frame(PAYLOAD)))
    # Per-video: the nonce is key-independent, Python == native token.
    nonce = video_nonce(cover_bytes, cover)
    per_video_keys = resolve_channel_keys(cover_bytes, cover, SECRET_KEY, "per-video")
    assert native_video_token(cli, SMALL_FIXTURE, SECRET_KEY) == per_video_keys.token()
    assert native_video_token(cli, SMALL_FIXTURE, WRONG_KEY) != per_video_keys.token()
    schedules = {}
    with tempfile.TemporaryDirectory(prefix="zkstego-channel-options-") as temp_dir:
        for select, key_mode in CHANNEL_OPTIONS:
            flags = channel_flags(select, key_mode)
            stego_path = Path(temp_dir) / f"stego-{select}-{key_mode}.h264"
            _embed(cli, SMALL_FIXTURE, stego_path, flags)
            stego = _segments(inspect, stego_path)
            stego_bytes = stego_path.read_bytes()
            keys = resolve_channel_keys(cover_bytes, cover, SECRET_KEY, key_mode)
            if key_mode == "per-video":
                assert video_nonce(stego_bytes, stego) == nonce, "embedding changed the video nonce"
                assert resolve_channel_keys(stego_bytes, stego, SECRET_KEY, key_mode) == keys
            placements = segment_schedule(cover, keys, frame_bits, MAX_BITS_PER_IDR, select)
            # The blind receiver rebuilds the same schedule from the stego file.
            assert [(p.segment, p.candidate.identity) for p in placements] == [
                (p.segment, p.candidate.identity)
                for p in segment_schedule(stego, keys, frame_bits, MAX_BITS_PER_IDR, select)
            ]
            embedded = embedded_frame_bits(PAYLOAD, keys)
            before, after = _signs(cover), _signs(stego)
            placed = {(p.candidate.nal_index, p.candidate.rbsp_bit_offset): p.frame_bit_index for p in placements}
            for location, bit in before.items():
                expected = embedded[placed[location]] if location in placed else bit
                assert after[location] == expected, (select, key_mode, location)
            if select == "low-drift":
                tiers = [p.candidate.tier for p in placements]
                assert all(tiers[i] <= tiers[i + 1] for i in range(len(tiers) - 1)
                           if placements[i].segment == placements[i + 1].segment), "low-drift order"
            # Digest: Python reference == native, cover == stego, token == key.
            native = native_video_digest(cli, SMALL_FIXTURE, SECRET_KEY, frame_bits, MAX_BITS_PER_IDR,
                                         select=select, key_mode=key_mode)
            assert native == video_digest(cover_bytes, cover, SECRET_KEY, frame_bits, MAX_BITS_PER_IDR,
                                          select=select, key_mode=key_mode)
            assert native_video_digest(cli, stego_path, SECRET_KEY, frame_bits, MAX_BITS_PER_IDR,
                                       select=select, key_mode=key_mode) == native
            if key_mode == "per-video":
                assert native_video_digest(cli, stego_path, keys.token(), frame_bits, MAX_BITS_PER_IDR,
                                           select=select, key_mode=key_mode) == native
            schedules[(select, key_mode)] = [(p.segment, p.candidate.identity) for p in placements]
    assert len({tuple(schedule) for schedule in schedules.values()}) == len(CHANNEL_OPTIONS)
    print(f"CHANNEL_OPTIONS_MATCH combinations={len(CHANNEL_OPTIONS)} frame_bits={frame_bits} "
          f"nonce={nonce.hex()[:16]}...")


def t_tier_inputs_match_native_trace() -> None:
    """--segments tier inputs == the full trace (same sign bit), and freq == Python scan_frequency."""
    inspect = _tool("ZK_STEGO_NATIVE_INSPECT", DEFAULT_INSPECT)
    if not inspect.is_file() or not SMALL_FIXTURE.is_file():
        SKIP("tier_inputs_match_native_trace", "native inspect tool or fixture missing")
    result = subprocess.run([str(inspect), str(SMALL_FIXTURE)], capture_output=True, check=False, timeout=300)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    trace = json.loads(result.stdout)
    widths = {s["nal_index"]: (s["mb_width"], s["mb_height"]) for s in trace["slices"]}
    by_location = {}
    for candidate in trace["candidates"]:
        nal, address, category, _block, bit = candidate["id"]
        width, height = widths[nal]
        assert candidate["mb_row"] == address // width and candidate["mb_height"] == height
        assert candidate["freq"] == scan_frequency(category, candidate["coefficients_scan"]), candidate["id"]
        by_location[(nal, bit)] = candidate
    segments = segment_candidates(_segments(inspect, SMALL_FIXTURE))
    tiers = [0] * 6
    for segment in segments:
        for candidate in segment:
            traced = by_location[(candidate.nal_index, candidate.rbsp_bit_offset)]
            assert (candidate.mb_row, candidate.mb_height, candidate.freq) == \
                (traced["mb_row"], traced["mb_height"], traced["freq"])
            assert candidate.tier == traced["tier"]
            tiers[candidate.tier] += 1
    assert sum(tiers) == len(trace["candidates"]) and tiers[0] > 0 and tiers[5] == 0
    print(f"TIER_TRACE_MATCH candidates={sum(tiers)} tier_histogram={tiers}")


def t_native_cli_low_drift_per_video_e2e() -> None:
    """embed/extract/digest/video-token with --select low-drift --key-mode per-video on the 300-frame fixture."""
    cli = _tool("ZK_STEGO_NATIVE_CLI", DEFAULT_CLI)
    if not cli.is_file() or not FIXTURE.is_file() or not SMALL_FIXTURE.is_file():
        SKIP("native_cli_low_drift_per_video_e2e", "native CLI or fixtures missing")
    flags = channel_flags("low-drift", "per-video")
    frame_bits = len(bytes_to_bits(pack_frame(PAYLOAD)))
    with tempfile.TemporaryDirectory(prefix="zkstego-low-drift-per-video-") as temp_dir:
        stego = Path(temp_dir) / "stego.h264"
        _embed(cli, FIXTURE, stego, flags)
        if shutil.which("ffmpeg") is not None:
            decode = subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-f", "h264", "-i", str(stego), "-f", "null", "-"],
                                    capture_output=True, check=False, timeout=120)
            assert decode.returncode == 0, decode.stderr.decode("utf-8", errors="replace")
        with_key = _extract(cli, stego, SECRET_KEY, flags)
        assert with_key.returncode == 0, with_key.stderr.decode("utf-8", errors="replace")
        assert with_key.stdout.strip().decode("ascii") == PAYLOAD.hex()
        # The verification token of this video extracts it without K; cover and stego share it.
        token = native_video_token(cli, stego, SECRET_KEY)
        assert token == native_video_token(cli, FIXTURE, SECRET_KEY)
        with_token = _extract(cli, stego, token, flags, "per-video")
        assert with_token.returncode == 0, with_token.stderr.decode("utf-8", errors="replace")
        assert with_token.stdout == with_key.stdout
        # Default parameters, a token without per-video, and another video's token all fail.
        def misses(result: subprocess.CompletedProcess[bytes]) -> bool:
            return result.returncode != 0 or result.stdout.strip() != PAYLOAD.hex().encode("ascii")

        assert misses(_extract(cli, stego, SECRET_KEY))
        assert misses(_extract(cli, stego, SECRET_KEY, channel_flags("low-drift", "master")))
        token_line_master = subprocess.run(
            [str(cli), "extract-stream-auth", str(stego), "-", "4096", str(MAX_BITS_PER_IDR), "--select", "low-drift"],
            input=b"token:" + token.hex().encode("ascii") + b"\n", capture_output=True, check=False, timeout=180)
        assert token_line_master.returncode != 0 and b"per-video" in token_line_master.stderr
        other_token = native_video_token(cli, SMALL_FIXTURE, SECRET_KEY)
        assert other_token != token
        assert misses(_extract(cli, stego, other_token, flags, "per-video"))
        # Digest: key == token, cover == stego; other parameters mark other carriers.
        digest = native_video_digest(cli, FIXTURE, SECRET_KEY, frame_bits, MAX_BITS_PER_IDR,
                                     select="low-drift", key_mode="per-video")
        assert native_video_digest(cli, stego, token, frame_bits, MAX_BITS_PER_IDR,
                                   select="low-drift", key_mode="per-video") == digest
        assert native_video_digest(cli, FIXTURE, SECRET_KEY, frame_bits, MAX_BITS_PER_IDR) != digest
        bad_flag = subprocess.run([str(cli), "video-digest", str(stego), str(frame_bits), str(MAX_BITS_PER_IDR),
                                   "--select", "lowest"], input=SECRET_KEY.hex().encode("ascii") + b"\n",
                                  capture_output=True, check=False, timeout=60)
        assert bad_flag.returncode != 0 and b"usage" not in bad_flag.stderr.lower()
    print(f"LOW_DRIFT_PER_VIDEO_E2E payload_bytes={len(PAYLOAD)} token_extract=true other_token_rejected=true "
          f"digest={digest.hex()[:16]}...")


def main() -> None:
    section("Native keyed CAVLC segment protocol fixture E2E")
    results = [
        run_test("native_cli_stream_fixture_e2e", t_native_cli_stream_embed_extract_and_strict_decode),
        run_test("python_segment_schedule_matches_native", t_python_segment_schedule_matches_native_encoder),
        run_test("video_digest_matches_reference_and_survives_embedding",
                 t_video_digest_matches_reference_and_survives_embedding),
        run_test("python_mirror_matches_native_for_channel_options",
                 t_python_mirror_matches_native_for_channel_options),
        run_test("tier_inputs_match_native_trace", t_tier_inputs_match_native_trace),
        run_test("native_cli_low_drift_per_video_e2e", t_native_cli_low_drift_per_video_e2e),
    ]
    sys.exit(summarise(results, "Native CLI fixture E2E"))


if __name__ == "__main__":
    main()
