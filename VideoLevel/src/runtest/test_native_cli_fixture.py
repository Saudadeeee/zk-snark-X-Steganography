"""Cross-platform fixture E2E for the native keyed CAVLC segment protocol (v3).

1. ``zkstego_blind_bits embed-stream-auth-stdin`` / ``extract-stream-auth`` round
   trip on a real H.264 fixture, strict FFmpeg decode, wrong key rejected.
2. The Python ``segment_schedule`` reproduces the native encoder exactly from
   ``zkstego_inspect --segments``: every placed stego sign equals
   ``frame_bit XOR keystream_bit`` and every other candidate sign is unchanged.
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
    embedded_frame_bits,
    pack_frame,
    segment_schedule,
    whitening_keystream_bits,
)
from src.runtest._helpers import SKIP, run_test, section, summarise


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "data" / "encoded" / "foreman_cif_q18_g1_300f.h264"
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


def _embed(cli: Path, cover: Path, stego: Path) -> None:
    embed = subprocess.run(
        [str(cli), "embed-stream-auth-stdin", str(cover), str(stego), str(MAX_BITS_PER_IDR)],
        input=SECRET_KEY.hex().encode("ascii") + b"\n" + PAYLOAD.hex().encode("ascii") + b"\n",
        capture_output=True,
        check=False,
        timeout=180,
    )
    assert embed.returncode == 0, embed.stderr.decode("utf-8", errors="replace")
    assert stego.is_file() and stego.stat().st_size > 0


def _extract(cli: Path, stego: Path, key: bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [str(cli), "extract-stream-auth", str(stego), "-", "4096", str(MAX_BITS_PER_IDR)],
        input=key.hex().encode("ascii") + b"\n",
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


def main() -> None:
    section("Native keyed CAVLC segment protocol fixture E2E")
    results = [
        run_test("native_cli_stream_fixture_e2e", t_native_cli_stream_embed_extract_and_strict_decode),
        run_test("python_segment_schedule_matches_native", t_python_segment_schedule_matches_native_encoder),
    ]
    sys.exit(summarise(results, "Native CLI fixture E2E"))


if __name__ == "__main__":
    main()
