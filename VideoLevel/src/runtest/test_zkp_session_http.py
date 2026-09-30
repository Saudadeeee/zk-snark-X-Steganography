"""Loopback HTTP tests for verifier-issued ZK session challenges."""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
import threading
from queue import Queue
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from src.zkp_session_http import create_session_server
from src.zkp_sessions import SessionChallengeStore


@pytest.fixture
def running_session_server(tmp_path):
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=45)
    binding = b"v" * 32
    server = create_session_server(store, context_binding=binding)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        yield server, store, binding, base_url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_post_issues_verifier_bound_short_lived_challenge(running_session_server):
    _server, store, binding, base_url = running_session_server
    request = Request(
        f"{base_url}/api/v1/zkp/sessions",
        data=b"",
        headers={"Content-Length": "0"},
        method="POST",
    )

    with urlopen(request, timeout=3) as response:
        grant = json.loads(response.read())
        assert response.status == 201
        assert response.headers["Content-Type"] == "application/json; charset=utf-8"
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    assert set(grant) == {"challenge", "issued_at", "expires_at"}
    assert re.fullmatch(r"[0-9a-f]{64}", grant["challenge"])
    assert grant["expires_at"] - grant["issued_at"] == 45
    assert store.is_active(bytes.fromhex(grant["challenge"]), context_binding=binding)
    assert not store.is_active(
        bytes.fromhex(grant["challenge"]), context_binding=b"x" * 32
    )


@pytest.mark.parametrize(
    ("method", "path", "body", "expected_status"),
    [
        ("GET", "/api/v1/zkp/sessions", None, 405),
        ("HEAD", "/api/v1/zkp/sessions", None, 405),
        ("POST", "/not-a-route", b"", 404),
        ("POST", "/api/v1/zkp/sessions", b"unexpected", 400),
    ],
)
def test_invalid_http_requests_do_not_issue_challenge(
    running_session_server, method, path, body, expected_status
):
    _server, store, _binding, base_url = running_session_server
    request = Request(
        f"{base_url}{path}",
        data=body,
        headers={"Content-Length": str(len(body or b""))},
        method=method,
    )

    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=3)

    assert error.value.code == expected_status
    if method == "HEAD":
        assert error.value.read() == b""
    with sqlite3.connect(store.database_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM zkp_session_challenges WHERE consumed_at IS NULL"
        ).fetchone()[0]
    assert count == 0


def test_session_server_refuses_non_loopback_bind(tmp_path):
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3")

    with pytest.raises(ValueError, match="loopback"):
        create_session_server(store, context_binding=b"l" * 32, host="0.0.0.0")


def test_module_cli_runs_http_session_issuer(tmp_path):
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "src.zkp_session_http",
            "--database",
            str(tmp_path / "cli-sessions.sqlite3"),
            "--context-binding-hex",
            (b"c" * 32).hex(),
            "--ttl-seconds",
            "30",
            "--port",
            "0",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    output_line: Queue[str] = Queue()
    reader = threading.Thread(
        target=lambda: output_line.put(process.stdout.readline()), daemon=True
    )
    reader.start()
    try:
        startup = output_line.get(timeout=5)
        match = re.search(r"http://127\.0\.0\.1:(\d+)", startup)
        assert match is not None, startup
        request = Request(
            f"http://127.0.0.1:{match.group(1)}/api/v1/zkp/sessions",
            data=b"",
            headers={"Content-Length": "0"},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            grant = json.loads(response.read())
        assert re.fullmatch(r"[0-9a-f]{64}", grant["challenge"])
    finally:
        process.terminate()
        process.wait(timeout=5)
