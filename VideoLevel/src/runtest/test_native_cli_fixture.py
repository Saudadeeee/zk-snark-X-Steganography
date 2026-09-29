"""Cross-platform fixture E2E for the native authenticated CAVLC CLI."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.runtest._helpers import SKIP, run_test, section, summarise


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "data" / "encoded" / "foreman_cif_q18_g1_300f.h264"
DEFAULT_CLI = (
    ROOT / "native" / "build" / "Release" / "zkstego_blind_bits.exe"
    if os.name == "nt"
    else ROOT / "native" / "edge-build" / "zkstego_blind_bits"
)
SECRET_KEY = bytes(range(32))
WRONG_KEY = bytes([0xA7]) * 32
PAYLOAD = b"native-cli-proof-e2e"


def t_native_cli_authenticated_embed_extract_and_strict_decode() -> None:
    cli = Path(os.environ.get("ZK_STEGO_NATIVE_CLI", DEFAULT_CLI))
    if not cli.is_file():
        SKIP("native_cli_authenticated_fixture_e2e", f"native CLI not found: {cli}")
        return
    if shutil.which("ffmpeg") is None:
        SKIP("native_cli_authenticated_fixture_e2e", "ffmpeg not found on PATH")
        return
    if not FIXTURE.is_file():
        SKIP("native_cli_authenticated_fixture_e2e", f"fixture not found: {FIXTURE}")
        return

    with tempfile.TemporaryDirectory(prefix="zkstego-native-cli-e2e-") as temp_dir:
        stego_path = Path(temp_dir) / "stego.h264"
        embed = subprocess.run(
            [str(cli), "embed-auth-stdin", str(FIXTURE), str(stego_path)],
            input=SECRET_KEY.hex().encode("ascii") + b"\n" + PAYLOAD.hex().encode("ascii") + b"\n",
            capture_output=True,
            check=False,
            timeout=120,
        )
        assert embed.returncode == 0, embed.stderr.decode("utf-8", errors="replace")
        assert stego_path.is_file() and stego_path.stat().st_size > 0

        strict_decode = subprocess.run(
            ["ffmpeg", "-v", "error", "-xerror", "-f", "h264", "-i", str(stego_path), "-f", "null", "-"],
            capture_output=True,
            check=False,
            timeout=60,
        )
        assert strict_decode.returncode == 0, strict_decode.stderr.decode("utf-8", errors="replace")

        correct_key = subprocess.run(
            [str(cli), "extract-auth", str(stego_path), "-", "4096"],
            input=SECRET_KEY.hex().encode("ascii") + b"\n",
            capture_output=True,
            check=False,
            timeout=120,
        )
        assert correct_key.returncode == 0, correct_key.stderr.decode("utf-8", errors="replace")
        assert correct_key.stdout.strip().decode("ascii") == PAYLOAD.hex()

        wrong_key = subprocess.run(
            [str(cli), "extract-auth", str(stego_path), "-", "4096"],
            input=WRONG_KEY.hex().encode("ascii") + b"\n",
            capture_output=True,
            check=False,
            timeout=120,
        )
        assert wrong_key.returncode != 0, "native authenticated extraction accepted a wrong key"
        print(
            "NATIVE_CLI_FIXTURE_METRICS "
            f"strict_ffmpeg_exit={strict_decode.returncode} "
            f"stego_bytes={stego_path.stat().st_size} "
            f"payload_bytes={len(PAYLOAD)} correct_key_match=true wrong_key_rejected=true"
        )


def main() -> None:
    section("Native authenticated CAVLC CLI fixture E2E")
    results = [
        run_test(
            "native_cli_authenticated_fixture_e2e",
            t_native_cli_authenticated_embed_extract_and_strict_decode,
        ),
    ]
    sys.exit(summarise(results, "Native CLI fixture E2E"))


if __name__ == "__main__":
    main()
