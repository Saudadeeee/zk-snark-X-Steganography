"""Shared session, logging, and executable helpers for individual demo stages."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import traceback
import contextlib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = Path(__file__).resolve().parent
RUNS_DIR = DEMO_DIR / "runs"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def require_session(session_arg: str | Path) -> tuple[Path, dict[str, Any]]:
    session = Path(session_arg).expanduser().resolve(strict=True)
    state_path = session / "session.json"
    if not state_path.is_file():
        raise FileNotFoundError(f"not a prepared demo session: {session}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    return session, state


def read_key(session: Path) -> bytes:
    key = (session / "secret_key.bin").read_bytes()
    if len(key) != 32:
        raise ValueError("demo session key must contain exactly 32 bytes")
    return key


def native_tool(name: str) -> Path:
    for configuration in ("Release", "Debug"):
        for suffix in (".exe", ""):
            path = ROOT / "native" / "build" / configuration / f"{name}{suffix}"
            if path.is_file():
                return path
    raise FileNotFoundError(f"native tool {name} not found; build native/ before running this stage")


def write_process_log(
    path: Path,
    *,
    title: str,
    command: list[str],
    stdin_description: str,
    result: subprocess.CompletedProcess[bytes],
) -> None:
    command_line = subprocess.list2cmdline(command) if os.name == "nt" else " ".join(command)
    path.write_text(
        f"STEP: {title}\nCOMMAND: {command_line}\nSTDIN: {stdin_description}\n"
        f"EXIT_CODE: {result.returncode}\n\n--- STDOUT ---\n"
        f"{(result.stdout or b'').decode('utf-8', errors='replace')}\n"
        f"--- STDERR ---\n{(result.stderr or b'').decode('utf-8', errors='replace')}",
        encoding="utf-8",
    )


def run_logged(
    session: Path,
    *,
    title: str,
    log_name: str,
    command: list[str],
    stdin_data: bytes | None = None,
    stdin_description: str = "none",
    expected_exit_code: int = 0,
    timeout: float = 300.0,
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        input=stdin_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )
    write_process_log(
        session / log_name,
        title=title,
        command=command,
        stdin_description=stdin_description,
        result=result,
    )
    with (session / log_name).open("a", encoding="utf-8") as log_file:
        log_file.write(
            f"\nEXPECTED_EXIT_CODE: {expected_exit_code}\n"
            f"STAGE_RESULT: {'PASS' if result.returncode == expected_exit_code else 'FAIL'}\n"
        )
    print(f"{title}: {'PASS' if result.returncode == expected_exit_code else 'FAIL'}")
    print(f"log: {session / log_name}")
    if result.returncode != expected_exit_code:
        raise RuntimeError(f"{title} returned {result.returncode}; see {session / log_name}")
    return result


def python_stage_log(session: Path, log_name: str, title: str, lines: list[str]) -> None:
    (session / log_name).write_text(
        f"STEP: {title}\n" + "\n".join(lines) + "\n", encoding="utf-8",
    )


def run_python_logged(session: Path, log_name: str, title: str, action: Any) -> None:
    log_path = session / log_name
    handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    logger = logging.getLogger()
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        with log_path.open("a", encoding="utf-8") as stream:
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                print(f"STEP: {title}")
                action()
                print("STAGE_RESULT: PASS")
    except Exception:
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write("STAGE_RESULT: FAIL\n")
            traceback.print_exc(file=stream)
        raise
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        handler.close()
    print(f"{title}: PASS")
    print(f"log: {log_path}")


def require_artifact(session: Path, name: str) -> Path:
    path = session / name
    if not path.is_file():
        raise FileNotFoundError(f"run the preceding pipeline stage first; missing {path}")
    return path
