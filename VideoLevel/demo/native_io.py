"""Native tool calls shared by terminal_demo.py and its step modules.

Every helper runs through ``session.run`` so each subprocess leaves
``<label>.stdout``/``<label>.stderr`` and a timing in the run folder.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_PAYLOAD_BYTES = 4096


@dataclass(frozen=True)
class Tools:
    native: Path   # zkstego_blind_bits: segment-protocol embed/extract
    inspect: Path  # zkstego_inspect: read-only JSON traces


def native_tool(name: str) -> Path:
    """Locate a native tool in multi-config (Release/Debug) or single-config build dirs."""
    build = ROOT / "native" / "build"
    for folder in (build / "Release", build / "Debug", build):
        for suffix in (".exe", ""):
            path = folder / f"{name}{suffix}"
            if path.is_file():
                return path
    raise FileNotFoundError(f"native tool {name} not found; build native/ (or run demo/terminal_demo.py --setup) first")


def find_tools() -> Tools:
    return Tools(native_tool("zkstego_blind_bits"), native_tool("zkstego_inspect"))


def trace_video(session, tool: Path, path: Path, label: str) -> dict:
    """``zkstego_inspect <video>``: JSON schema 1 (NALs, IDR slices, whole-file candidates)."""
    trace = json.loads(session.run(label, [tool, path]).stdout)
    session.save(label + ".json", trace)
    return trace


def inspect_segments(session, tool: Path, path: Path, max_bits: int, label: str) -> dict:
    """``zkstego_inspect <video> --segments MAX``: JSON segments-1 (per-IDR schedule input)."""
    segments = json.loads(session.run(label, [tool, path, "--segments", max_bits]).stdout)
    session.save(label + ".json", segments)
    return segments


def native_embed(session, tools: Tools, cover: Path, output: Path, key: bytes, payload: bytes,
                 max_bits: int, label: str) -> subprocess.CompletedProcess:
    """``embed-stream-auth-stdin``: the key and payload travel only through stdin."""
    return session.run(label, [tools.native, "embed-stream-auth-stdin", cover.relative_to(ROOT),
                               output.relative_to(ROOT), max_bits],
                       data=(key.hex() + "\n" + payload.hex() + "\n").encode())


def native_extract(session, tools: Tools, video: Path, key: bytes, max_bits: int, label: str,
                   *, allow_failure: bool = False) -> subprocess.CompletedProcess:
    """``extract-stream-auth <video> - MAX_PAYLOAD MAX_BITS``: blind, key on stdin."""
    return session.run(label, [tools.native, "extract-stream-auth", video.relative_to(ROOT), "-",
                               MAX_PAYLOAD_BYTES, max_bits],
                       data=(key.hex() + "\n").encode(), allow_failure=allow_failure)


def verify_groth16(session, proof: dict, public: list, label: str) -> bool:
    """snarkjs groth16 verify; an infrastructure error is never counted as a valid rejection."""
    session.save(label + "_proof.json", proof)
    session.save(label + "_public.json", public)
    cli = ROOT / "circuits/node_modules/snarkjs/build/cli.cjs"
    result = session.run(label, ["node", cli, "groth16", "verify", ROOT / "circuits/build/verification_key.json",
                                 session.folder / (label + "_public.json"), session.folder / (label + "_proof.json")],
                         allow_failure=True)
    output = re.sub(r"\x1b\[[0-9;]*m", "", (result.stdout + result.stderr).decode("utf-8", errors="replace"))
    if result.returncode == 0 and re.search(r"\bOK!", output):
        return True
    if "Invalid proof" in output:
        return False
    raise RuntimeError(f"{label}: verifier infrastructure error, khong duoc tinh la reject hop le:\n{output[-2000:]}")
