"""Loopback-only HTTP job API for the experimental video transport probe.

This is a local control API, not a public or production service. Clients upload
raw H.264 files and submit jobs against an operator-provisioned relation,
witness, relation pin, and sync key. The cryptographic limitations of the
underlying LNP22 probe still apply.
"""

from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import math
import os
import re
import sys
import tempfile
import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:
    from .video_e2e import (
        PROBE_PROTOCOL,
        _sync_key_from_environment,
        _verify_from_video,
        embed_and_verify,
    )
except ImportError:  # pragma: no cover - direct script execution
    from video_e2e import (  # type: ignore[no-redef]
        PROBE_PROTOCOL,
        _sync_key_from_environment,
        _verify_from_video,
        embed_and_verify,
    )

API_TOKEN_ENV = "ZKSTEGOLNP22_API_TOKEN"
RELATION_PATH_ENV = "ZKSTEGOLNP22_RELATION_PATH"
WITNESS_PATH_ENV = "ZKSTEGOLNP22_WITNESS_PATH"
RELATION_PIN_ENV = "ZKSTEGOLNP22_TRUSTED_RELATION_SHA256"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UPLOAD_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.h264$")
_REPORT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.json$")
_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_MAX_JSON_BYTES = 16 * 1024
_UPLOAD_CHUNK_BYTES = 1024 * 1024


class ApiFault(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class _WindowRateLimiter:
    def __init__(self, limit: int, *, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, identity: str) -> bool:
        now = time.monotonic()
        with self._lock:
            events = self._events[identity]
            while events and now - events[0] >= self.window_seconds:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True


@dataclass(frozen=True)
class ApiConfig:
    workspace: Path
    relation_path: Path = field(repr=False)
    witness_path: Path = field(repr=False)
    trusted_relation_sha256: str
    api_token: str = field(repr=False)
    max_upload_bytes: int = 512 * 1024 * 1024
    max_inbox_bytes: int = 2 * 1024 * 1024 * 1024
    max_active_jobs: int = 1
    max_requests_per_minute: int = 120
    max_jobs_per_minute: int = 2
    request_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        workspace = self.workspace.resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError("workspace must be a directory")
        object.__setattr__(self, "workspace", workspace)
        for directory_name in ("inbox", "output", "reports"):
            directory = workspace / directory_name
            if (
                directory.is_symlink()
                or not directory.is_dir()
                or directory.resolve(strict=True).parent != workspace
            ):
                raise ValueError(f"workspace/{directory_name} must be an existing direct child directory")
        for field_name in ("relation_path", "witness_path"):
            path = getattr(self, field_name).resolve(strict=True)
            if not path.is_file():
                raise ValueError(f"{field_name} must be a regular file")
            object.__setattr__(self, field_name, path)
        if _SHA256_RE.fullmatch(self.trusted_relation_sha256) is None:
            raise ValueError("trusted relation digest must be a lowercase SHA-256 hex string")
        if len(self.api_token) < 32:
            raise ValueError("API bearer token must contain at least 32 characters")
        if min(
            self.max_upload_bytes,
            self.max_inbox_bytes,
            self.max_active_jobs,
            self.max_requests_per_minute,
            self.max_jobs_per_minute,
        ) < 1:
            raise ValueError("API limits must be positive")
        if not math.isfinite(self.request_timeout_seconds) or self.request_timeout_seconds <= 0:
            raise ValueError("request timeout must be a finite positive number")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _resolve_workspace_path(workspace: Path, value: Any, *, must_exist: bool) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ApiFault(422, "invalid_request", "A non-empty relative path is required")
    supplied = Path(value)
    if supplied.is_absolute():
        raise ApiFault(422, "invalid_request", "Paths must be relative to the API workspace")
    unresolved = workspace / supplied
    try:
        resolved = unresolved.resolve(strict=must_exist)
        resolved.relative_to(workspace)
    except (OSError, ValueError) as error:
        raise ApiFault(422, "invalid_request", "Path is missing or outside the API workspace") from error
    if must_exist and not resolved.is_file():
        raise ApiFault(422, "invalid_request", "Input path must identify a regular file")
    if not must_exist:
        if unresolved.is_symlink() or resolved.exists():
            raise ApiFault(409, "output_exists", "Output paths must not already exist")
        if not resolved.parent.is_dir():
            raise ApiFault(422, "invalid_request", "Output parent directory must already exist")
    return resolved


def _validate_job_request(workspace: Path, body: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(body, dict):
        raise ApiFault(422, "invalid_request", "JSON request must be an object")
    operation = body.get("operation")
    if operation not in ("embed", "verify"):
        raise ApiFault(422, "invalid_request", "operation must be 'embed' or 'verify'")
    allowed = {"operation", "video"}
    if operation == "embed":
        allowed |= {"output", "report", "proof_mode"}
    if set(body) - allowed:
        raise ApiFault(422, "invalid_request", "Request contains unsupported fields")

    video = _resolve_workspace_path(workspace, body.get("video"), must_exist=True)
    arguments = {"video": video}
    if operation == "embed":
        proof_mode = body.get("proof_mode", "augmented")
        if proof_mode not in ("augmented", "compact"):
            raise ApiFault(
                422,
                "invalid_request",
                "proof_mode must be 'augmented' or 'compact'",
            )
        output = _resolve_workspace_path(workspace, body.get("output"), must_exist=False)
        report = _resolve_workspace_path(workspace, body.get("report"), must_exist=False)
        output_directory = (workspace / "output").resolve(strict=True)
        report_directory = (workspace / "reports").resolve(strict=True)
        if output.parent != output_directory or output.suffix.lower() != ".h264":
            raise ApiFault(422, "invalid_request", "Output must be a .h264 file directly under workspace/output")
        if report.parent != report_directory or report.suffix.lower() != ".json":
            raise ApiFault(422, "invalid_request", "Report must be a .json file directly under workspace/reports")
        if _UPLOAD_NAME_RE.fullmatch(output.name) is None or _REPORT_NAME_RE.fullmatch(report.name) is None:
            raise ApiFault(422, "invalid_request", "Output and report names must use safe ASCII filenames")
        if video == output or video == report or output == report:
            raise ApiFault(422, "invalid_request", "Input, output, and report paths must be distinct")
        arguments.update(output=output, report=report, proof_mode=proof_mode)
    return operation, arguments


def _run_probe_operation(
    operation: str, arguments: dict[str, Any], config: ApiConfig
) -> dict[str, Any]:
    if operation == "verify":
        return _verify_from_video(
            arguments["video"],
            relation_path=config.relation_path,
            trusted_relation_sha256=config.trusted_relation_sha256,
            sync_key=_sync_key_from_environment(),
        )
    return embed_and_verify(
        arguments["video"],
        arguments["output"],
        arguments["report"],
        relation_path=config.relation_path,
        witness_path=config.witness_path,
        trusted_relation_sha256=config.trusted_relation_sha256,
        proof_mode=arguments["proof_mode"],
    )


def _public_result(
    operation: str, result: dict[str, Any], arguments: dict[str, Any], workspace: Path
) -> dict[str, Any]:
    if operation == "verify":
        fields = (
            "valid",
            "proof_format",
            "proof_bytes",
            "payload_bytes",
            "carriers_used",
            "statement_id",
            "canonical_video_sha256",
            "positions_hash",
            "verify_ms",
            "security_status",
        )
        return {key: result[key] for key in fields if key in result}
    fields = (
        "proof_mode",
        "proof_format",
        "output_video_sha256",
        "proof_bytes",
        "embedded_payload_bytes",
        "carriers_used",
        "strict_h264_decode",
        "blind_video_only_extraction",
        "proof_verification",
        "phase_ms",
        "peak_rss_mb",
        "security_status",
    )
    safe = {key: result[key] for key in fields if key in result}
    safe["output"] = arguments["output"].relative_to(workspace).as_posix()
    safe["report"] = arguments["report"].relative_to(workspace).as_posix()
    return safe


class JobManager:
    def __init__(
        self,
        config: ApiConfig,
        *,
        operation_runner: Callable[[str, dict[str, Any], ApiConfig], dict[str, Any]] = _run_probe_operation,
        executor: Any | None = None,
    ) -> None:
        self.config = config
        self.operation_runner = operation_runner
        self.executor = executor or ThreadPoolExecutor(max_workers=config.max_active_jobs)
        self._owns_executor = executor is None
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def submit(self, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            active_count = sum(job["status"] in {"queued", "running"} for job in self._jobs.values())
            if active_count >= self.config.max_active_jobs:
                raise ApiFault(429, "job_capacity_reached", "Verifier is busy; retry later")
            if len(self._jobs) >= 1024:
                for job_id in list(self._jobs):
                    if self._jobs[job_id]["status"] in {"succeeded", "failed"}:
                        del self._jobs[job_id]
                        if len(self._jobs) < 768:
                            break
            if len(self._jobs) >= 1024:
                raise ApiFault(503, "job_store_full", "Job store is full; restart the local service")
            job_id = uuid.uuid4().hex
            record = {
                "id": job_id,
                "operation": operation,
                "status": "queued",
                "created_at": _utc_now(),
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
            }
            self._jobs[job_id] = record
        try:
            future = self.executor.submit(self._execute, job_id, operation, arguments)
        except RuntimeError as error:
            with self._lock:
                self._jobs.pop(job_id, None)
            raise ApiFault(503, "service_unavailable", "The local job worker is unavailable") from error
        future.add_done_callback(lambda completed, current=job_id: self._finish(current, completed))
        return self.get(job_id) or record

    def _execute(self, job_id: str, operation: str, arguments: dict[str, Any]) -> None:
        with self._lock:
            record = self._jobs[job_id]
            record["status"] = "running"
            record["started_at"] = _utc_now()
        raw_result = self.operation_runner(operation, arguments, self.config)
        safe_result = _public_result(operation, raw_result, arguments, self.config.workspace)
        with self._lock:
            self._jobs[job_id]["result"] = safe_result

    def _finish(self, job_id: str, future: Future[Any]) -> None:
        with self._lock:
            record = self._jobs[job_id]
            error = None if future.cancelled() else future.exception()
            if future.cancelled() or error is not None:
                record["status"] = "failed"
                record["error"] = {
                    "code": "job_failed",
                    "message": "The requested video job failed",
                    "type": type(error).__name__ if error is not None else "CancelledError",
                }
            else:
                record["status"] = "succeeded"
            record["finished_at"] = _utc_now()

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._jobs.get(job_id)
            return dict(record) if record is not None else None

    def shutdown(self) -> None:
        if self._owns_executor:
            self.executor.shutdown(wait=False, cancel_futures=True)


class _LoopbackHttpServer(ThreadingHTTPServer):
    def handle_error(self, _request: Any, client_address: Any) -> None:
        error = sys.exc_info()[1]
        print(
            json.dumps(
                {
                    "event": "http_handler_error",
                    "client_ip": str(client_address[0]),
                    "error_type": type(error).__name__ if error is not None else "UnknownError",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )


def create_handler(config: ApiConfig, manager: JobManager | None = None):
    jobs = manager or JobManager(config)
    request_limiter = _WindowRateLimiter(config.max_requests_per_minute)
    job_limiter = _WindowRateLimiter(config.max_jobs_per_minute)
    upload_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "ZKStegoLocalAPI/1"

        def setup(self) -> None:
            self.request.settimeout(config.request_timeout_seconds)
            super().setup()

        def _write_json(self, status: int, body: dict[str, Any], *, headers: dict[str, str] | None = None) -> None:
            encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(encoded)

        def _error(self, fault: ApiFault) -> None:
            self._write_json(
                fault.status,
                {"error": {"code": fault.code, "message": fault.message}},
                headers={"Retry-After": "5"} if fault.status == 429 else None,
            )

        def _authorize(self) -> bool:
            supplied = self.headers.get("Authorization", "")
            expected = f"Bearer {config.api_token}"
            if not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
                self._error(ApiFault(401, "unauthorized", "A valid bearer token is required"))
                return False
            if not request_limiter.allow(self.client_address[0]):
                self._error(ApiFault(429, "rate_limit_exceeded", "Request rate limit exceeded"))
                return False
            return True

        def _read_json(self) -> Any:
            if self.headers.get("Transfer-Encoding"):
                raise ApiFault(400, "invalid_request", "Transfer-Encoding is not supported")
            if self.headers.get_content_type() != "application/json":
                raise ApiFault(415, "unsupported_media_type", "Content-Type must be application/json")
            raw_length = self.headers.get("Content-Length")
            try:
                length = int(raw_length or "")
            except ValueError as error:
                raise ApiFault(411, "length_required", "A valid Content-Length is required") from error
            if length < 1 or length > _MAX_JSON_BYTES:
                raise ApiFault(413, "request_too_large", "JSON request body is empty or too large")
            try:
                return json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise ApiFault(400, "invalid_json", "Request body must be valid UTF-8 JSON") from error

        def do_GET(self) -> None:
            if not self._authorize():
                return
            route = urlsplit(self.path).path
            if route == "/api/v1/health":
                self._write_json(
                    200,
                    {"data": {"status": "ok", "protocol": PROBE_PROTOCOL, "security_status": "experimental only; not an audited application ZKP"}},
                )
                return
            artifact_match = re.fullmatch(r"/api/v1/videos/([A-Za-z0-9][A-Za-z0-9._-]{0,119}\.h264)", route)
            if artifact_match is not None:
                self._stream_artifact(config.workspace / "output", artifact_match.group(1), "video/h264")
                return
            report_match = re.fullmatch(r"/api/v1/reports/([A-Za-z0-9][A-Za-z0-9._-]{0,119}\.json)", route)
            if report_match is not None:
                self._stream_artifact(config.workspace / "reports", report_match.group(1), "application/json")
                return
            match = re.fullmatch(r"/api/v1/jobs/([0-9a-f]{32})", route)
            if match is None:
                self._error(ApiFault(404, "not_found", "Resource not found"))
                return
            job = jobs.get(match.group(1))
            if job is None:
                self._error(ApiFault(404, "not_found", "Job not found"))
                return
            self._write_json(200, {"data": job})

        def _stream_artifact(self, directory: Path, name: str, content_type: str) -> None:
            path = directory / name
            try:
                resolved_directory = directory.resolve(strict=True)
                resolved_path = path.resolve(strict=True)
                resolved_path.relative_to(config.workspace)
                if path.is_symlink() or resolved_path.parent != resolved_directory or not resolved_path.is_file():
                    raise OSError("artifact path is not a regular file in the configured directory")
                size = resolved_path.stat().st_size
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                with resolved_path.open("rb") as source:
                    for chunk in iter(lambda: source.read(_UPLOAD_CHUNK_BYTES), b""):
                        self.wfile.write(chunk)
            except (OSError, ValueError):
                self._error(ApiFault(404, "not_found", "Artifact not found"))

        def do_POST(self) -> None:
            if not self._authorize():
                return
            if urlsplit(self.path).path != "/api/v1/jobs":
                self._error(ApiFault(404, "not_found", "Resource not found"))
                return
            try:
                body = self._read_json()
                operation, arguments = _validate_job_request(config.workspace, body)
                if not job_limiter.allow(self.client_address[0]):
                    raise ApiFault(429, "job_rate_limit", "Job submission limit reached; retry later")
                job = jobs.submit(operation, arguments)
            except ApiFault as fault:
                self._error(fault)
                return
            self._write_json(
                202,
                {"data": job},
                headers={"Location": f"/api/v1/jobs/{job['id']}"},
            )

        def do_PUT(self) -> None:
            if not self._authorize():
                return
            route = urlsplit(self.path).path
            prefix = "/api/v1/videos/"
            if not route.startswith(prefix):
                self._error(ApiFault(404, "not_found", "Resource not found"))
                return
            name = route[len(prefix):]
            if _UPLOAD_NAME_RE.fullmatch(name) is None:
                self._error(ApiFault(422, "invalid_request", "Video name must be a simple .h264 filename"))
                return
            if self.headers.get_content_type() not in {"video/h264", "application/octet-stream"}:
                self._error(ApiFault(415, "unsupported_media_type", "Upload must be raw H.264 bytes"))
                return
            if self.headers.get("Transfer-Encoding"):
                self._error(ApiFault(400, "invalid_request", "Transfer-Encoding is not supported"))
                return
            try:
                length = int(self.headers.get("Content-Length") or "")
            except ValueError:
                self._error(ApiFault(411, "length_required", "A valid Content-Length is required"))
                return
            if length < 1 or length > config.max_upload_bytes:
                self._error(ApiFault(413, "request_too_large", "H.264 upload is empty or exceeds the configured limit"))
                return
            inbox = config.workspace / "inbox"
            if inbox.is_symlink() or not inbox.is_dir() or inbox.resolve().parent != config.workspace:
                self._error(ApiFault(503, "storage_unavailable", "Configured inbox directory is unavailable"))
                return
            destination = inbox / name
            temporary_path: Path | None = None
            try:
                with upload_lock:
                    if destination.exists() or destination.is_symlink():
                        raise ApiFault(409, "video_exists", "Video name already exists; choose a new name")
                    existing_bytes = 0
                    for existing in inbox.glob("*.h264"):
                        if existing.is_symlink():
                            raise ApiFault(503, "storage_unavailable", "Inbox contains an unexpected symbolic link")
                        if existing.is_file():
                            existing_bytes += existing.stat().st_size
                    if existing_bytes + length > config.max_inbox_bytes:
                        raise ApiFault(413, "storage_quota_exceeded", "Configured inbox storage quota would be exceeded")
                    with tempfile.NamedTemporaryFile(prefix=".upload-", dir=inbox, delete=False) as output:
                        temporary_path = Path(output.name)
                        remaining = length
                        while remaining:
                            chunk = self.rfile.read(min(_UPLOAD_CHUNK_BYTES, remaining))
                            if not chunk:
                                raise ApiFault(400, "incomplete_upload", "Upload ended before Content-Length bytes arrived")
                            output.write(chunk)
                            remaining -= len(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    os.link(temporary_path, destination)
            except FileExistsError:
                self._error(ApiFault(409, "video_exists", "Video name already exists; choose a new name"))
                return
            except ApiFault as fault:
                self._error(fault)
                return
            except OSError:
                self._error(ApiFault(500, "upload_failed", "Could not safely store the upload"))
                return
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
            self._write_json(201, {"data": {"path": f"inbox/{name}", "bytes": length}})

        def do_DELETE(self) -> None:
            if not self._authorize():
                return
            self._error(ApiFault(405, "method_not_allowed", "DELETE is not supported"))

        def log_message(self, _format: str, *args: Any) -> None:
            # Avoid emitting request headers, paths, or job input details to stderr.
            return

    return Handler


def serve(*, host: str, port: int, config: ApiConfig) -> None:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        raise ValueError("API host must be an IP address") from error
    if address.version != 4 or not address.is_loopback:
        raise ValueError("experimental API only binds to an IPv4 loopback address")
    manager = JobManager(config)
    server = _LoopbackHttpServer((host, port), create_handler(config, manager))
    server.daemon_threads = True
    try:
        print(json.dumps({"listening": f"http://{host}:{server.server_port}", "security_status": "experimental local API"}), flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        manager.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        required = {
            "relation": os.environ.get(RELATION_PATH_ENV, ""),
            "witness": os.environ.get(WITNESS_PATH_ENV, ""),
            "trusted relation pin": os.environ.get(RELATION_PIN_ENV, ""),
            "API bearer token": os.environ.get(API_TOKEN_ENV, ""),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError("missing server configuration: " + ", ".join(missing))
        _sync_key_from_environment()
        config = ApiConfig(
            workspace=args.workspace,
            relation_path=Path(required["relation"]),
            witness_path=Path(required["witness"]),
            trusted_relation_sha256=required["trusted relation pin"],
            api_token=required["API bearer token"],
        )
        serve(host=args.host, port=args.port, config=config)
    except (OSError, RuntimeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "configuration_error",
                        "type": type(error).__name__,
                        "message": "Check local API configuration; sensitive details are not returned",
                    }
                }
            )
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
