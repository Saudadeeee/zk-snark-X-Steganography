"""Small, fail-closed HTTP job service core (auth, limits, job store, retention).

``create_app`` owns everything generic about the service; the media work is
injected as handlers. ``src.api.native_handlers.create_native_app`` supplies the
native C++ CAVLC handlers and is the production entry point.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import math
import os
import re
import secrets
import shutil
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from starlette.routing import get_route_path
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool


_LOGGER = logging.getLogger(__name__)

JOB_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{24}")
# "rejected" is terminal like "succeeded": the job ran, but the proof did not verify.
TERMINAL_JOB_STATUSES = frozenset({"succeeded", "rejected", "failed"})
MIN_API_TOKEN_LENGTH = 32
EMBED_OUTPUT_NAME = "stego.h264"
# Sidecars an older (pure-Python) embedder left next to its output. Job directories from older
# builds may still hold them; nothing serves them, so they are deleted.


def is_valid_job_id(job_id: object) -> bool:
    """Job IDs are ``secrets.token_urlsafe(18)``; anything else never touches the filesystem."""
    return isinstance(job_id, str) and JOB_ID_PATTERN.fullmatch(job_id) is not None


def bearer_token_matches(authorization: str | bytes | None, api_token: str) -> bool:
    """Constant-time Bearer check that fails closed, never raising on non-ASCII input."""
    if not authorization:
        return False
    if isinstance(authorization, str):
        # Starlette decodes header bytes as latin-1; undo that to compare the raw header bytes.
        try:
            authorization = authorization.encode("latin-1")
        except UnicodeEncodeError:
            authorization = authorization.encode("utf-8", errors="surrogatepass")
    expected = f"Bearer {api_token}".encode("utf-8", errors="surrogatepass")
    return secrets.compare_digest(authorization, expected)


def client_host(scope: dict[str, Any]) -> str:
    """The direct peer address; forwarded-for headers are client-controlled and ignored."""
    client = scope.get("client")
    return str(client[0]) if client else "unknown"


class AuthFailureLimiter:
    """Per-client fixed-window counter of failed Bearer checks with bounded memory.

    Once a client reaches ``max_failures`` within ``window_seconds`` of its first
    failure, every protected request from it is refused (429) until that window
    ends, whatever token it sends. Other clients are unaffected; at most
    ``max_tracked_clients`` windows are kept, evicting the oldest first.
    """

    def __init__(
        self,
        *,
        max_failures: int = 10,
        window_seconds: float = 60.0,
        max_tracked_clients: int = 4096,
        clock: Callable[[], float] = time.monotonic,
    ):
        if max_failures < 1 or max_tracked_clients < 1:
            raise ValueError("max_failures and max_tracked_clients must be positive")
        if not math.isfinite(window_seconds) or window_seconds <= 0:
            raise ValueError("window_seconds must be finite and positive")
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.max_tracked_clients = max_tracked_clients
        self._clock = clock
        self._windows: OrderedDict[str, tuple[float, int]] = OrderedDict()
        self._lock = threading.Lock()

    def retry_after(self, client: str) -> int:
        """Whole seconds until ``client`` may authenticate again, or 0 when it is not throttled."""
        with self._lock:
            window = self._windows.get(client)
            if window is None:
                return 0
            started, failures = window
            remaining = started + self.window_seconds - self._clock()
            if remaining <= 0:
                del self._windows[client]
                return 0
            return max(1, math.ceil(remaining)) if failures >= self.max_failures else 0

    def record_failure(self, client: str) -> int:
        """Count one failed attempt and return the client's failures in its current window."""
        with self._lock:
            now = self._clock()
            window = self._windows.get(client)
            if window is not None and now - window[0] < self.window_seconds:
                failures = window[1] + 1
                self._windows[client] = (window[0], failures)  # Keeps its (start-ordered) position.
                return failures
            self._windows.pop(client, None)
            # Windows are appended in start order, so expired ones sit at the front.
            while self._windows:
                oldest_started = next(iter(self._windows.values()))[0]
                if now - oldest_started < self.window_seconds and len(self._windows) < self.max_tracked_clients:
                    break
                self._windows.popitem(last=False)
            self._windows[client] = (now, 1)
            return 1


class _RequestBodyLimitError(Exception):
    pass


class RequestBodyGuard:
    """Authenticate, then bound multipart request bytes and upload duration before routing.

    Authentication runs here, before any body byte is read, because FastAPI
    parses (and spools) multipart forms before route dependencies execute.
    With an ``auth_limiter``, a client that keeps failing authentication is
    answered 429 with ``Retry-After`` until its failure window ends.
    """

    _UPLOAD_PATHS: ClassVar[frozenset[str]] = frozenset({
        "/api/v1/jobs/embed",
        "/api/v1/jobs/verify",
        "/api/v1/jobs/extract",
    })
    _PROTECTED_PREFIX: ClassVar[str] = "/api/v1/"

    def __init__(
        self,
        app,
        *,
        maximum_bytes: dict[str, int],
        timeout_seconds: float,
        api_token: str | None = None,
        max_concurrent_uploads: int | None = None,
        auth_limiter: AuthFailureLimiter | None = None,
    ):
        self.app = app
        self.maximum_bytes = maximum_bytes
        self.timeout_seconds = timeout_seconds
        self.api_token = api_token
        self.max_concurrent_uploads = max_concurrent_uploads
        self.auth_limiter = auth_limiter
        self._active_uploads = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Keep the first occurrence of each header, matching FastAPI's Header() dependency.
        headers: dict[bytes, bytes] = {}
        for key, value in scope.get("headers", ()):
            headers.setdefault(key.lower(), value)
        # Compare against the routed path: with --root-path, uvicorn prefixes scope["path"],
        # and a raw prefix check would let protected routes skip auth and size limits.
        path = get_route_path(scope) if scope.get("path") else ""
        if self.api_token is not None and path.startswith(self._PROTECTED_PREFIX):
            client = client_host(scope)
            retry_after = self.auth_limiter.retry_after(client) if self.auth_limiter is not None else 0
            if retry_after:
                await self._reject(
                    send, 429, b'{"detail":"too many failed authentication attempts; retry later"}',
                    extra_headers=[(b"retry-after", str(retry_after).encode("ascii"))],
                )
                return
            if not bearer_token_matches(headers.get(b"authorization"), self.api_token):
                failures = self.auth_limiter.record_failure(client) if self.auth_limiter is not None else None
                _LOGGER.warning(
                    "API authentication failed: client=%s path=%r failures_in_window=%s", client, path, failures,
                )
                await self._reject(
                    send, 401, b'{"detail":"Bearer token required"}',
                    extra_headers=[(b"www-authenticate", b"Bearer")],
                )
                return
        if scope.get("method") != "POST" or path not in self._UPLOAD_PATHS:
            await self.app(scope, receive, send)
            return
        if self.max_concurrent_uploads is not None and self._active_uploads >= self.max_concurrent_uploads:
            await self._reject(
                send, 503, b'{"detail":"upload capacity reached; retry later"}',
                extra_headers=[(b"retry-after", b"1")],
            )
            return
        self._active_uploads += 1
        try:
            await self._guard_upload(scope, receive, send, headers)
        finally:
            self._active_uploads -= 1

    async def _guard_upload(self, scope, receive, send, headers: dict[bytes, bytes]) -> None:
        maximum_bytes = self.maximum_bytes[scope["path"]]
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > maximum_bytes:
                    await self._reject(send, 413, b'{"detail":"request body exceeds configured limit"}')
                    return
            except ValueError:
                await self._reject(send, 400, b'{"detail":"invalid Content-Length"}')
                return

        started = asyncio.get_running_loop().time()
        received = 0

        async def guarded_receive():
            nonlocal received
            remaining = self.timeout_seconds - (asyncio.get_running_loop().time() - started)
            if remaining <= 0:
                raise TimeoutError
            message = await asyncio.wait_for(receive(), timeout=remaining)
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > maximum_bytes:
                    raise _RequestBodyLimitError
            return message

        response_started = False

        async def guarded_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, guarded_receive, guarded_send)
        except _RequestBodyLimitError:
            if response_started:
                raise
            await self._reject(send, 413, b'{"detail":"request body exceeds configured limit"}')
        except (TimeoutError, asyncio.TimeoutError):
            if response_started:
                raise
            await self._reject(send, 408, b'{"detail":"request body upload timed out"}')

    @staticmethod
    async def _reject(
        send, status_code: int, body: bytes, *, extra_headers: list[tuple[bytes, bytes]] | None = None,
    ) -> None:
        await send({
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                *(extra_headers or ()),
            ],
        })
        await send({"type": "http.response.body", "body": body, "more_body": False})


class WorkDirLease:
    """Hold an OS-released exclusive lock so one API process owns a work dir."""

    def __init__(self, path: Path):
        self.path = path
        self._stream = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise RuntimeError("another API process already owns this work directory") from exc
        self._stream = stream

    def release(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ApiSettings:
    api_token: str
    work_dir: Path = Path(".cache/api")
    circuits_dir: Path = Path("circuits")
    # Trusted camera registry (src/camera_registry.py JSON); the verify job checks proofs against its root.
    camera_registry_path: Path | None = None
    # Mode-1 (message-only) proofs are not bound to the video; reject them unless explicitly allowed.
    require_video_binding: bool = True
    max_upload_bytes: int = 100 * 1024 * 1024
    max_workers: int = 1
    max_queued_jobs: int = 2
    artifact_ttl_seconds: float = 600.0
    upload_timeout_seconds: float = 120.0
    max_concurrent_uploads: int = 4
    job_retention_seconds: float = 24 * 3600.0
    enable_docs: bool = False
    auth_failure_limit: int = 10
    auth_failure_window_seconds: float = 60.0

    @classmethod
    def from_environment(cls) -> ApiSettings:
        token = os.environ.get("ZK_STEGO_API_TOKEN")
        if not token:
            raise RuntimeError("ZK_STEGO_API_TOKEN must be set; refusing to start an unauthenticated API")
        if len(token) < MIN_API_TOKEN_LENGTH:
            raise RuntimeError(
                f"ZK_STEGO_API_TOKEN must be at least {MIN_API_TOKEN_LENGTH} characters; "
                "generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )
        return cls(
            api_token=token,
            work_dir=Path(os.environ.get("ZK_STEGO_API_WORK_DIR", ".cache/api")),
            circuits_dir=Path(os.environ.get("ZK_STEGO_CIRCUITS_DIR", "circuits")),
            camera_registry_path=(Path(os.environ["ZK_STEGO_CAMERA_REGISTRY"])
                                  if os.environ.get("ZK_STEGO_CAMERA_REGISTRY") else None),
            require_video_binding=os.environ.get("ZK_STEGO_ALLOW_MESSAGE_ONLY_PROOFS") != "1",
            upload_timeout_seconds=_seconds_from_environment("ZK_STEGO_API_UPLOAD_TIMEOUT_SECONDS", 120.0),
            job_retention_seconds=_seconds_from_environment("ZK_STEGO_API_JOB_RETENTION_SECONDS", 24 * 3600.0),
            enable_docs=os.environ.get("ZK_STEGO_API_DOCS") == "1",
        )


def _seconds_from_environment(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number of seconds") from exc
    if not math.isfinite(value) or value < 1.0:
        raise ValueError(f"{name} must be finite and at least one second")
    return value


class JobStore:
    """Thread-safe local metadata store.  Secrets and message contents are never stored."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self, operation: str) -> dict[str, Any]:
        job_id = secrets.token_urlsafe(18)
        record = {"job_id": job_id, "operation": operation, "status": "queued", "created_at": _now(), "updated_at": _now()}
        with self._lock:
            self._records[job_id] = record
            self._persist(record)
        return dict(record)

    def get(self, job_id: str) -> dict[str, Any] | None:
        if not is_valid_job_id(job_id):
            return None
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                persisted = self.directory / f"{job_id}.json"
                try:
                    loaded = json.loads(persisted.read_text(encoding="utf-8"))
                    if loaded.get("job_id") == job_id and isinstance(loaded.get("status"), str):
                        self._records[job_id] = loaded
                        record = loaded
                except (OSError, ValueError, TypeError):
                    return None
            return dict(record) if record else None

    def all_records(self) -> list[dict[str, Any]]:
        with self._lock:
            for persisted in self.directory.glob("*.json"):
                if persisted.stem in self._records:
                    continue
                try:
                    loaded = json.loads(persisted.read_text(encoding="utf-8"))
                    if loaded.get("job_id") == persisted.stem and isinstance(loaded.get("status"), str):
                        self._records[persisted.stem] = loaded
                except (OSError, ValueError, TypeError):
                    continue
            return [dict(record) for record in self._records.values()]

    def update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            record = self._records[job_id]
            record.update(changes, updated_at=_now())
            self._persist(record)

    def discard(self, job_id: str) -> None:
        with self._lock:
            self._records.pop(job_id, None)
            (self.directory / f"{job_id}.json").unlink(missing_ok=True)

    def _persist(self, record: dict[str, Any]) -> None:
        destination = self.directory / f"{record['job_id']}.json"
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
        os.replace(temporary, destination)


def _decode_key(value: str, field_name: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"{field_name} must be base64") from exc
    if len(decoded) != 32:
        raise HTTPException(status_code=422, detail=f"{field_name} must decode to exactly 32 bytes")
    return decoded


def _decode_message(value: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="message_b64 must be base64") from exc
    if not decoded or len(decoded) > 4096:
        raise HTTPException(status_code=422, detail="message must be between 1 and 4096 bytes")
    return decoded


async def _save_upload(upload: UploadFile, destination: Path, maximum: int) -> None:
    if Path(upload.filename or "").suffix.lower() not in {".h264", ".264"}:
        raise HTTPException(status_code=422, detail="only raw .h264 / .264 video uploads are accepted")
    written = 0
    stream = None
    try:
        # Disk I/O runs off the event loop so one slow disk cannot stall every connection.
        stream = await run_in_threadpool(destination.open, "wb")
        while chunk := await upload.read(1024 * 1024):
            written += len(chunk)
            if written > maximum:
                raise HTTPException(status_code=413, detail="upload exceeds configured limit")
            await run_in_threadpool(stream.write, chunk)
        await run_in_threadpool(stream.close)
    except BaseException:
        # Cleanup must not mask the original error (e.g. a flush failing again on ENOSPC).
        if stream is not None:
            with contextlib.suppress(OSError):
                stream.close()
        with contextlib.suppress(OSError):
            destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def _safe_embed_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: result[key]
        for key in ("valid", "bits_embedded", "bits_embedded_source", "capacity_bits", "output_file")
        if key in result
    }


def _safe_verify_result(result: dict[str, Any]) -> dict[str, Any]:
    """Only a verified proof may carry its (proven) message; a rejection carries a reason code."""
    if result.get("valid") is True:
        return {key: result[key] for key in ("valid", "message_b64", "payload_bytes", "video_bound") if key in result}
    return {"valid": False, **({"reason": str(result["reason"])} if "reason" in result else {})}


def _safe_extract_result(result: dict[str, Any], output_name: str) -> dict[str, Any]:
    safe = {key: result[key] for key in ("valid", "payload_bytes") if key in result}
    safe["output_file"] = output_name
    # Extraction never authenticates a payload; only the verify job checks its proof.
    safe["verified"] = False
    return safe


def create_app(
    settings: ApiSettings | None = None,
    *,
    embed_handler: Callable[..., dict[str, Any]] | None = None,
    verify_handler: Callable[..., dict[str, Any]] | None = None,
    extract_handler: Callable[..., dict[str, Any]] | None = None,
) -> FastAPI:
    """Build the job service; an endpoint whose handler is ``None`` answers 501.

    Handlers run on the worker pool and receive keyword arguments only:
    ``embed_handler(video_path, message, output_path, secret_key)``,
    ``verify_handler(stego_video_path, secret_key, maximum_payload_bytes)`` and
    ``extract_handler(stego_video_path, output_path, secret_key, maximum_payload_bytes)``.
    A verify job is "succeeded" only when its result has ``valid is True``; any other
    result is "rejected", and a handler exception is "failed".
    """
    settings = settings or ApiSettings.from_environment()
    if not isinstance(settings.api_token, str) or len(settings.api_token) < MIN_API_TOKEN_LENGTH:
        raise ValueError(f"api_token must be a string of at least {MIN_API_TOKEN_LENGTH} characters")
    if settings.auth_failure_limit < 1:
        raise ValueError("auth_failure_limit must be positive")
    if not math.isfinite(settings.auth_failure_window_seconds) or settings.auth_failure_window_seconds <= 0:
        raise ValueError("auth_failure_window_seconds must be finite and positive")
    if settings.max_workers < 1 or settings.max_queued_jobs < 0:
        raise ValueError("max_workers must be positive and max_queued_jobs must be non-negative")
    if not math.isfinite(settings.artifact_ttl_seconds) or settings.artifact_ttl_seconds < 1.0:
        raise ValueError("artifact_ttl_seconds must be finite and at least one second")
    if not math.isfinite(settings.upload_timeout_seconds) or settings.upload_timeout_seconds < 1.0:
        raise ValueError("upload_timeout_seconds must be finite and at least one second")
    if settings.max_concurrent_uploads < 1:
        raise ValueError("max_concurrent_uploads must be positive")
    if not math.isfinite(settings.job_retention_seconds) or settings.job_retention_seconds < 1.0:
        raise ValueError("job_retention_seconds must be finite and at least one second")
    # Interactive docs and the OpenAPI schema are unauthenticated, so they are opt-in (ZK_STEGO_API_DOCS=1).
    app = FastAPI(
        title="ZK-Stego Video API", version="1.0.0",
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
    )
    # Shared by RequestBodyGuard (HTTP) and any WebSocket route that authenticates before accept().
    auth_limiter = AuthFailureLimiter(
        max_failures=settings.auth_failure_limit, window_seconds=settings.auth_failure_window_seconds,
    )
    app.state.auth_failure_limiter = auth_limiter
    app.add_middleware(
        RequestBodyGuard,
        maximum_bytes={
            "/api/v1/jobs/embed": settings.max_upload_bytes + (1024 * 1024),
            "/api/v1/jobs/extract": settings.max_upload_bytes + (1024 * 1024),
            "/api/v1/jobs/verify": settings.max_upload_bytes + (1024 * 1024),
        },
        timeout_seconds=settings.upload_timeout_seconds,
        api_token=settings.api_token,
        max_concurrent_uploads=settings.max_concurrent_uploads,
        auth_limiter=auth_limiter,
    )
    store = JobStore(settings.work_dir / "jobs")
    work_dir_lease = WorkDirLease(settings.work_dir / ".api-instance.lock")
    executor = ThreadPoolExecutor(max_workers=settings.max_workers, thread_name_prefix="zk-stego")
    capacity = threading.BoundedSemaphore(settings.max_workers + settings.max_queued_jobs)
    artifact_cleanup_stop = threading.Event()
    artifact_cleanup_thread: threading.Thread | None = None
    artifact_lock = threading.Lock()
    app.state.settings, app.state.store, app.state.executor = settings, store, executor
    app.state.capacity = capacity
    app.state.work_dir_lease = work_dir_lease

    def require_token(authorization: str | None = Header(default=None)) -> None:
        # Defense in depth: RequestBodyGuard already rejected unauthenticated /api/v1/ requests.
        if not bearer_token_matches(authorization, settings.api_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")

    def reserve_capacity() -> None:
        if not capacity.acquire(blocking=False):
            raise HTTPException(status_code=503, detail="job capacity reached; retry later", headers={"Retry-After": "1"})

    def cleanup_inputs(job_id: str, operation: str) -> None:
        directory = settings.work_dir / "files" / job_id
        filenames = {
            "embed": ("cover.h264",),
            "verify": ("stego.h264",),
            "extract": ("stego.h264",),
        }.get(operation, ())
        for filename in filenames:
            try:
                (directory / filename).unlink(missing_ok=True)
            except OSError:
                continue

    def outcome(operation: str, handler: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            result = handler()
        except Exception as exc:  # Do not expose paths, secrets, or internal tracebacks.  # noqa: BLE001
            return {"status": "failed", "error": f"{operation} failed: {type(exc).__name__}"}
        # Fail closed: a verify job is "succeeded" only when the proof verified.
        # Anything else is the terminal "rejected" status, keeping the valid=false body.
        rejected = operation == "verify" and result.get("valid") is not True
        return {"status": "rejected" if rejected else "succeeded", "result": result}

    def release(job_id: str, operation: str) -> None:
        try:
            cleanup_inputs(job_id, operation)
        finally:
            capacity.release()

    # A terminal status is published only after the job's inputs are removed and its
    # capacity slot is free, so a client that sees a finished job can submit the next one.
    def submit(job_id: str, operation: str, handler: Callable[[], dict[str, Any]]) -> None:
        def run() -> None:
            try:
                store.update(job_id, status="running")
            except Exception:  # noqa: BLE001 - e.g. ENOSPC persisting the record.
                try:
                    release(job_id, operation)
                finally:
                    # The in-memory record is updated before persisting, so this still ends the
                    # job for clients; restart recovery fails whatever state reached the disk.
                    with contextlib.suppress(Exception):
                        store.update(job_id, status="failed", error=f"{operation} could not be started")
                return
            try:
                terminal = outcome(operation, handler)
            finally:
                release(job_id, operation)
            try:
                store.update(job_id, **terminal)
            except Exception:  # noqa: BLE001 - e.g. ENOSPC persisting the final record.
                # Never leave a client-visible success that the disk does not hold: end the job as
                # failed (in memory at least; restart recovery fails a record left "running").
                _LOGGER.warning("job %s: could not persist its %s status", job_id, terminal.get("status"))
                with contextlib.suppress(Exception):
                    store.update(job_id, status="failed", error=f"{operation} result could not be saved")
        try:
            executor.submit(run)
        except Exception:
            try:
                release(job_id, operation)
            finally:
                store.update(job_id, status="failed", error=f"{operation} could not be scheduled")
            raise

    def abandon_upload(job_id: str, job_dir: Path, created: bool) -> None:
        if created:
            for path in job_dir.iterdir():
                if path.is_file():
                    path.unlink(missing_ok=True)
            job_dir.rmdir()
        store.discard(job_id)

    def sweep_expired_extract_artifacts() -> None:
        cutoff = time.time() - settings.artifact_ttl_seconds
        files_root = settings.work_dir / "files"
        try:
            job_dirs = tuple(files_root.iterdir())
        except OSError:
            return
        with artifact_lock:
            for job_dir in job_dirs:
                if not job_dir.is_dir():
                    continue
                job_id = job_dir.name
                record = store.get(job_id)
                if not record:
                    continue
                if record.get("operation") == "embed":
                    main_artifact = job_dir / EMBED_OUTPUT_NAME
                elif record.get("operation") == "extract":
                    main_artifact = job_dir / "payload.bin"
                else:
                    continue
                artifacts = (main_artifact, *job_dir.glob(".artifact-claim-*.tmp"))
                removed = False
                for artifact_path in artifacts:
                    try:
                        if artifact_path.stat().st_mtime < cutoff:
                            artifact_path.unlink(missing_ok=True)
                            removed = True
                    except OSError:
                        continue
                if removed:
                    try:
                        record = store.get(job_id)
                        if record and record.get("operation") in {"embed", "extract"}:
                            store.update(job_id, artifact_expired=True)
                    except (OSError, KeyError):
                        continue

    def purge_expired_jobs(now: float | None = None) -> int:
        """Drop terminal job records and their directories older than the retention window.

        Queued/running records are never purged, so restart recovery still sees
        every interrupted job. The cutoff is never shorter than the artifact TTL,
        so an artifact that may still be downloaded is never removed here.
        """
        keep_seconds = max(settings.job_retention_seconds, settings.artifact_ttl_seconds)
        cutoff = (time.time() if now is None else now) - keep_seconds
        files_root = settings.work_dir / "files"
        purged = 0
        with artifact_lock:
            for record in store.all_records():
                job_id = record.get("job_id")
                if not is_valid_job_id(job_id) or record.get("status") not in TERMINAL_JOB_STATUSES:
                    continue
                try:
                    updated = datetime.fromisoformat(str(record.get("updated_at"))).timestamp()
                except (TypeError, ValueError):
                    continue
                if updated >= cutoff:
                    continue
                job_dir = files_root / job_id
                try:
                    if job_dir.is_dir():
                        shutil.rmtree(job_dir)
                    store.discard(job_id)
                    purged += 1
                except OSError:
                    continue
            try:
                remaining_dirs = tuple(files_root.iterdir())
            except OSError:
                remaining_dirs = ()
            for job_dir in remaining_dirs:
                # Orphans: an empty, stale directory whose record is already gone.
                if not job_dir.is_dir() or not is_valid_job_id(job_dir.name) or store.get(job_dir.name):
                    continue
                try:
                    if job_dir.stat().st_mtime < cutoff:
                        shutil.rmtree(job_dir)
                except OSError:
                    continue
        return purged

    def run_artifact_cleanup() -> None:
        interval = min(60.0, max(1.0, settings.artifact_ttl_seconds / 2.0))
        while not artifact_cleanup_stop.wait(interval):
            sweep_expired_extract_artifacts()
            purge_expired_jobs()

    def recover_interrupted_jobs() -> None:
        files_root = settings.work_dir / "files"
        for record in store.all_records():
            job_id = record.get("job_id")
            if not is_valid_job_id(job_id):
                continue
            try:
                if record.get("status") not in {"queued", "running"}:
                    continue
                operation = record.get("operation")
                if not isinstance(operation, str) or operation not in {"embed", "verify", "extract"}:
                    continue
                cleanup_inputs(job_id, operation)
                job_dir = files_root / job_id
                partial_outputs = {
                    "embed": ("stego.h264",),
                    "extract": ("payload.bin",),
                }.get(operation, ())
                if job_dir.is_dir():
                    for filename in partial_outputs:
                        (job_dir / filename).unlink(missing_ok=True)
                store.update(job_id, status="failed", error="job interrupted by service restart")
            except (OSError, KeyError):
                continue

    @app.on_event("startup")
    def startup() -> None:
        nonlocal artifact_cleanup_thread
        work_dir_lease.acquire()
        try:
            recover_interrupted_jobs()
            sweep_expired_extract_artifacts()
            purge_expired_jobs()
            artifact_cleanup_stop.clear()
            artifact_cleanup_thread = threading.Thread(
                target=run_artifact_cleanup, name="zk-stego-artifact-cleanup", daemon=True,
            )
            artifact_cleanup_thread.start()
            app.state.artifact_cleanup_thread = artifact_cleanup_thread
            app.state.sweep_expired_extract_artifacts = sweep_expired_extract_artifacts
            app.state.recover_interrupted_jobs = recover_interrupted_jobs
            app.state.purge_expired_jobs = purge_expired_jobs
        except BaseException:
            work_dir_lease.release()
            raise

    @app.on_event("shutdown")
    def shutdown() -> None:
        artifact_cleanup_stop.set()
        if artifact_cleanup_thread is not None:
            artifact_cleanup_thread.join(timeout=2.0)
        try:
            executor.shutdown(wait=True, cancel_futures=False)
        finally:
            work_dir_lease.release()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "zk-stego-video"}

    @app.post("/api/v1/jobs/embed", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_token)])
    async def start_embed(
        video: UploadFile = File(...),  # noqa: B008
        message_b64: str = Form(...),
        secret_key_b64: str = Form(...),
    ) -> dict[str, str]:
        if embed_handler is None:
            raise HTTPException(status_code=501, detail="embedding is not configured for this service")
        message, secret_key = _decode_message(message_b64), _decode_key(secret_key_b64, "secret_key_b64")
        reserve_capacity()
        job_dir_created = False
        try:
            record = store.create("embed")
            job_dir = settings.work_dir / "files" / record["job_id"]
            job_dir.mkdir(parents=True, exist_ok=False)
            job_dir_created = True
            input_path, output_path = job_dir / "cover.h264", job_dir / EMBED_OUTPUT_NAME
            await _save_upload(video, input_path, settings.max_upload_bytes)
        except BaseException:
            try:
                if "record" in locals():
                    abandon_upload(record["job_id"], job_dir, job_dir_created)
            finally:
                capacity.release()
            raise

        def perform() -> dict[str, Any]:
            result = embed_handler(
                video_path=str(input_path), message=message, output_path=str(output_path),
                secret_key=secret_key,
            )
            return _safe_embed_result(result)

        submit(record["job_id"], "embed", perform)
        return {"job_id": record["job_id"], "status": "queued"}

    @app.post("/api/v1/jobs/verify", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_token)])
    async def start_verify(
        stego_video: UploadFile = File(...),  # noqa: B008
        secret_key_b64: str = Form(...),
        maximum_payload_bytes: int = Form(..., ge=1, le=4096),
    ) -> dict[str, str]:
        if verify_handler is None:
            raise HTTPException(status_code=501, detail="proof verification is not configured for this service")
        secret_key = _decode_key(secret_key_b64, "secret_key_b64")
        reserve_capacity()
        job_dir_created = False
        try:
            record = store.create("verify")
            job_dir = settings.work_dir / "files" / record["job_id"]
            job_dir.mkdir(parents=True, exist_ok=False)
            job_dir_created = True
            stego_path = job_dir / "stego.h264"
            await _save_upload(stego_video, stego_path, settings.max_upload_bytes)
        except BaseException:
            try:
                if "record" in locals():
                    abandon_upload(record["job_id"], job_dir, job_dir_created)
            finally:
                capacity.release()
            raise

        def perform() -> dict[str, Any]:
            result = verify_handler(
                stego_video_path=str(stego_path), secret_key=secret_key,
                maximum_payload_bytes=maximum_payload_bytes,
            )
            return _safe_verify_result(result)

        submit(record["job_id"], "verify", perform)
        return {"job_id": record["job_id"], "status": "queued"}

    @app.post("/api/v1/jobs/extract", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_token)])
    async def start_extract(
        stego_video: UploadFile = File(...),  # noqa: B008
        secret_key_b64: str = Form(...),
        maximum_payload_bytes: int = Form(..., ge=1, le=4096),
    ) -> dict[str, str]:
        if extract_handler is None:
            raise HTTPException(status_code=501, detail="blind extraction is not configured for this service")
        secret_key = _decode_key(secret_key_b64, "secret_key_b64")
        reserve_capacity()
        job_dir_created = False
        try:
            record = store.create("extract")
            job_dir = settings.work_dir / "files" / record["job_id"]
            job_dir.mkdir(parents=True, exist_ok=False)
            job_dir_created = True
            stego_path, payload_path = job_dir / "stego.h264", job_dir / "payload.bin"
            await _save_upload(stego_video, stego_path, settings.max_upload_bytes)
        except BaseException:
            try:
                if "record" in locals():
                    abandon_upload(record["job_id"], job_dir, job_dir_created)
            finally:
                capacity.release()
            raise

        def perform() -> dict[str, Any]:
            result = extract_handler(
                stego_video_path=str(stego_path), output_path=str(payload_path),
                secret_key=secret_key, maximum_payload_bytes=maximum_payload_bytes,
            )
            return _safe_extract_result(result, payload_path.name)

        submit(record["job_id"], "extract", perform)
        return {"job_id": record["job_id"], "status": "queued"}

    @app.get("/api/v1/jobs/{job_id}", dependencies=[Depends(require_token)])
    def get_job(job_id: str) -> dict[str, Any]:
        if not is_valid_job_id(job_id):
            raise HTTPException(status_code=404, detail="job not found")
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        return record

    @app.get("/api/v1/jobs/{job_id}/artifact", dependencies=[Depends(require_token)])
    def download_artifact(job_id: str) -> FileResponse:
        if not is_valid_job_id(job_id):
            raise HTTPException(status_code=404, detail="artifact not available")
        record = store.get(job_id)
        if not record or record.get("status") != "succeeded":
            raise HTTPException(status_code=404, detail="artifact not available")
        if record.get("operation") == "embed":
            source = settings.work_dir / "files" / job_id / "stego.h264"
            media_type, filename = "video/h264", "stego.h264"
        elif record.get("operation") == "extract":
            source = settings.work_dir / "files" / job_id / "payload.bin"
            media_type, filename = "application/octet-stream", "payload.bin"
        else:
            raise HTTPException(status_code=404, detail="artifact not available")
        claimed = source.with_name(f".artifact-claim-{secrets.token_hex(12)}.tmp")
        with artifact_lock:
            try:
                if source.stat().st_mtime < time.time() - settings.artifact_ttl_seconds:
                    source.unlink(missing_ok=True)
                    store.update(job_id, artifact_expired=True)
                    raise HTTPException(status_code=404, detail="artifact not available")
                os.replace(source, claimed)
                os.utime(claimed, None)
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail="artifact not available") from exc

        def consume_artifact() -> None:
            try:
                with artifact_lock:
                    claimed.unlink(missing_ok=True)
                    store.update(job_id, artifact_expired=True)
            except (OSError, KeyError):
                pass

        if not claimed.is_file():
            raise HTTPException(status_code=404, detail="artifact not available")
        return FileResponse(
            claimed, media_type=media_type, filename=filename,
            background=BackgroundTask(consume_artifact),
        )

    return app
