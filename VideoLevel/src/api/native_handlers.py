"""FastAPI adapter for the authenticated native CAVLC CLI.

The 32-byte key is delivered only through the child's stdin, never argv or a
temporary key file. Configure ``ZK_STEGO_NATIVE_CLI`` with the built executable.
"""

from __future__ import annotations

import math
import os
import subprocess
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from src.api.app import ApiSettings, create_app


def create_native_app(
    settings: ApiSettings | None = None,
    *,
    cli_path: str | Path | None = None,
    timeout_seconds: float = 120.0,
) -> FastAPI:
    """Create the bounded HTTP service backed by native authenticated CAVLC."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    configured_cli = cli_path or os.environ.get("ZK_STEGO_NATIVE_CLI")
    if not configured_cli:
        raise RuntimeError("ZK_STEGO_NATIVE_CLI must point to zkstego_blind_bits")
    executable = Path(configured_cli).resolve(strict=True)
    if not executable.is_file():
        raise RuntimeError("ZK_STEGO_NATIVE_CLI must point to a regular executable file")

    def invoke(
        arguments: list[str], secret_key: bytes, *, stdin_tail: bytes = b"",
    ) -> subprocess.CompletedProcess[bytes]:
        if len(secret_key) != 32:
            raise ValueError("native CAVLC key must be 32 bytes")
        try:
            result = subprocess.run(
                [str(executable), *arguments],
                input=secret_key.hex().encode("ascii") + b"\n" + stdin_tail,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("native CAVLC operation timed out") from exc
        if result.returncode != 0:
            raise RuntimeError("native CAVLC operation failed")
        return result

    def embed_handler(
        *, video_path: str, message: bytes, output_path: str, secret_key: bytes, **_: Any,
    ) -> dict[str, Any]:
        invoke(
            ["embed-auth-stdin", video_path, output_path],
            secret_key,
            stdin_tail=message.hex().encode("ascii") + b"\n",
        )
        if not Path(output_path).is_file():
            raise RuntimeError("native CAVLC operation did not create output")
        # The native authenticated frame carries 1 version + 2 length + 16 tag bytes.
        return {"valid": True, "bits_embedded": (len(message) + 19) * 8, "output_file": Path(output_path).name}

    def extract_handler(
        *, stego_video_path: str, output_path: str, secret_key: bytes, maximum_payload_bytes: int,
    ) -> dict[str, Any]:
        result = invoke(
            ["extract-auth", stego_video_path, "-", str(maximum_payload_bytes)],
            secret_key,
        )
        try:
            payload = bytes.fromhex(result.stdout.decode("ascii").strip())
        except (UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError("native CAVLC extractor returned malformed payload") from exc
        if len(payload) > maximum_payload_bytes:
            raise RuntimeError("native CAVLC extractor exceeded requested payload bound")
        destination = Path(output_path)
        try:
            with destination.open("xb") as stream:
                stream.write(payload)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        return {"valid": True, "payload_bytes": len(payload)}

    return create_app(
        settings,
        embed_handler=embed_handler,
        verify_handler=None,
        extract_handler=extract_handler,
    )
