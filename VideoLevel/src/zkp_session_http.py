"""Loopback HTTP issuance for verifier-owned ZK session challenges.

This service only issues session challenges. It deliberately has no proof
verification route: the repository's lattice proof artifacts are still
research-only, and must not be accepted by this endpoint.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
from collections.abc import Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from typing import Any, cast

from src.zkp_sessions import SessionChallengeStore

_SESSION_PATH = "/api/v1/zkp/sessions"
_MAX_REJECTED_BODY_BYTES = 64 * 1024


class _SessionIssuanceHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ZKSessionIssuer"
    sys_version = ""

    def _respond(self, status: int, payload: dict[str, str | int]) -> None:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'")
        self.send_header("Connection", "close")
        if status == 405:
            self.send_header("Allow", "POST")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.close_connection = True

    def _request_body_status(self) -> int | None:
        # No request body is part of challenge issuance. Reject ambiguous
        # framing rather than parsing a body on this minimal server. A small,
        # explicitly framed body is drained before returning so clients receive
        # the HTTP error response instead of a TCP reset on connection close.
        transfer_encodings = self.headers.get_all("Transfer-Encoding", [])
        content_lengths = self.headers.get_all("Content-Length", [])
        if transfer_encodings or len(content_lengths) > 1:
            return 400
        if not content_lengths:
            return None
        value = content_lengths[0].strip()
        if not value.isascii() or not value.isdecimal():
            return 400
        normalized_length = value.lstrip("0") or "0"
        if len(normalized_length) > len(str(_MAX_REJECTED_BODY_BYTES)):
            return 413
        body_length = int(normalized_length)
        if body_length == 0:
            return None
        if body_length > _MAX_REJECTED_BODY_BYTES:
            return 413
        self.rfile.read(body_length)
        return 400

    def _handle(self) -> None:
        body_status = self._request_body_status()
        if body_status is not None:
            error = "request_body_too_large" if body_status == 413 else "request_body_not_allowed"
            self._respond(body_status, {"error": error})
            return
        if self.path != _SESSION_PATH:
            self._respond(404, {"error": "not_found"})
            return
        if self.command != "POST":
            self._respond(405, {"error": "method_not_allowed"})
            return
        server = cast(SessionIssuanceServer, self.server)
        grant = server.store.issue(context_binding=server.context_binding)
        self._respond(201, grant.to_dict())

    do_GET = _handle
    do_HEAD = _handle
    do_POST = _handle
    do_PUT = _handle
    do_PATCH = _handle
    do_DELETE = _handle
    do_OPTIONS = _handle

    def log_message(self, _format: str, *args: Any) -> None:
        # Keep challenge endpoint access logs from exposing request metadata in
        # default stdout. Deployments should install their own redacted logger.
        return


class SessionIssuanceServer(ThreadingHTTPServer):
    """A small HTTP server bound exclusively to a loopback address."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        store: SessionChallengeStore,
        context_binding: bytes,
    ) -> None:
        self.store = store
        self.context_binding = context_binding
        self.address_family = (
            socket.AF_INET6 if ":" in address[0] else socket.AF_INET
        )
        super().__init__(address, _SessionIssuanceHandler)


def create_session_server(
    store: SessionChallengeStore,
    *,
    context_binding: bytes,
    host: str = "127.0.0.1",
    port: int = 0,
) -> SessionIssuanceServer:
    """Create a loopback-only HTTP issuer for verifier-pinned session state.

    This development server intentionally rejects non-loopback binds. It does
    not provide authentication, TLS, rate limiting, or proof verification and
    must not be exposed as a production verifier.
    """
    if not isinstance(store, SessionChallengeStore):
        raise TypeError("store must be a SessionChallengeStore")
    if not isinstance(context_binding, bytes) or len(context_binding) != 32:
        raise ValueError("context_binding must be exactly 32 bytes")
    try:
        address = ip_address(host)
    except ValueError as exc:
        raise ValueError("host must be a loopback IP address") from exc
    if not address.is_loopback:
        raise ValueError("host must be a loopback IP address")
    return SessionIssuanceServer((str(address), port), store, context_binding)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the development-only loopback challenge issuer from the CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="durable SQLite file path")
    parser.add_argument(
        "--context-binding-hex",
        required=True,
        help="verifier-pinned 32-byte policy digest as 64 hexadecimal characters",
    )
    parser.add_argument("--ttl-seconds", type=int, default=300)
    parser.add_argument("--host", default="127.0.0.1", help="loopback IP only")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    if re.fullmatch(r"[0-9a-fA-F]{64}", args.context_binding_hex) is None:
        parser.error(
            "--context-binding-hex must contain exactly 64 hexadecimal characters"
        )
    try:
        context_binding = bytes.fromhex(args.context_binding_hex)
    except ValueError:
        parser.error("--context-binding-hex must contain hexadecimal bytes")
    if len(context_binding) != 32:
        parser.error("--context-binding-hex must encode exactly 32 bytes")

    store = SessionChallengeStore(args.database, ttl_seconds=args.ttl_seconds)
    server = create_session_server(
        store,
        context_binding=context_binding,
        host=args.host,
        port=args.port,
    )
    host, port = server.server_address[:2]
    display_host = f"[{host}]" if ":" in host else host
    print(
        f"Development session issuer listening on http://{display_host}:{port}; "
        "loopback only; proof verification is not configured.",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
