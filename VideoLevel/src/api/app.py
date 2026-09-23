"""Small, fail-closed HTTP API around the existing embed/verify runtime."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import re
import secrets
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

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

from src.embedder import embed
from src.verifier import verify


class _RequestBodyLimitError(Exception):
    pass


class RequestBodyGuard:
    """Bound multipart request bytes and wall-clock upload duration before routing."""

    _UPLOAD_PATHS: ClassVar[frozenset[str]] = frozenset({
        "/api/v1/jobs/embed",
        "/api/v1/jobs/verify",
        "/api/v1/jobs/extract",
    })

    def __init__(self, app, *, maximum_bytes: dict[str, int], timeout_seconds: float):
        self.app = app
        self.maximum_bytes = maximum_bytes
        self.timeout_seconds = timeout_seconds

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST" or scope.get("path") not in self._UPLOAD_PATHS:
            await self.app(scope, receive, send)
            return
        maximum_bytes = self.maximum_bytes[scope["path"]]

        headers = {key.lower(): value for key, value in scope.get("headers", ())}
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
    async def _reject(send, status_code: int, body: bytes) -> None:
        await send({
            "type": "http.response.start",
            "status": status_code,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("ascii"))],
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
    max_upload_bytes: int = 100 * 1024 * 1024
    max_workers: int = 1
    max_queued_jobs: int = 2
    artifact_ttl_seconds: float = 600.0
    upload_timeout_seconds: float = 120.0

    @classmethod
    def from_environment(cls) -> ApiSettings:
        token = os.environ.get("ZK_STEGO_API_TOKEN")
        if not token:
            raise RuntimeError("ZK_STEGO_API_TOKEN must be set; refusing to start an unauthenticated API")
        return cls(
            api_token=token,
            work_dir=Path(os.environ.get("ZK_STEGO_API_WORK_DIR", ".cache/api")),
            circuits_dir=Path(os.environ.get("ZK_STEGO_CIRCUITS_DIR", "circuits")),
        )


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
    try:
        with destination.open("wb") as stream:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > maximum:
                    raise HTTPException(status_code=413, detail="upload exceeds configured limit")
                stream.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def _safe_embed_result(result: Any, output_name: str) -> dict[str, Any]:
    if isinstance(result, dict):
        return {key: result[key] for key in ("valid", "bits_embedded", "capacity_bits", "output_file") if key in result}
    return {
        "valid": True,
        "bits_embedded": int(result.bits_embedded),
        "capacity_bits": int(result.capacity_bits),
        "output_file": output_name,
    }


def _safe_verify_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return {key: result[key] for key in ("valid", "bits_extracted") if key in result}
    return {"valid": bool(result.valid), "bits_extracted": int(result.bits_extracted)}


def _safe_extract_result(result: Any, output_name: str) -> dict[str, Any]:
    if isinstance(result, dict):
        safe = {key: result[key] for key in ("valid", "payload_bytes") if key in result}
        safe["output_file"] = output_name
        return safe
    return {"valid": True, "payload_bytes": int(result.payload_bytes), "output_file": output_name}


def create_app(
    settings: ApiSettings | None = None,
    *,
    embed_handler: Callable[..., Any] = embed,
    verify_handler: Callable[..., Any] | None = verify,
    extract_handler: Callable[..., Any] | None = None,
) -> FastAPI:
    settings = settings or ApiSettings.from_environment()
    if settings.max_workers < 1 or settings.max_queued_jobs < 0:
        raise ValueError("max_workers must be positive and max_queued_jobs must be non-negative")
    if not math.isfinite(settings.artifact_ttl_seconds) or settings.artifact_ttl_seconds < 1.0:
        raise ValueError("artifact_ttl_seconds must be finite and at least one second")
    if not math.isfinite(settings.upload_timeout_seconds) or settings.upload_timeout_seconds < 1.0:
        raise ValueError("upload_timeout_seconds must be finite and at least one second")
    app = FastAPI(title="ZK-Stego Video API", version="1.0.0", docs_url="/docs", redoc_url=None)
    app.add_middleware(
        RequestBodyGuard,
        maximum_bytes={
            "/api/v1/jobs/embed": settings.max_upload_bytes + (1024 * 1024),
            "/api/v1/jobs/extract": settings.max_upload_bytes + (1024 * 1024),
            "/api/v1/jobs/verify": (2 * settings.max_upload_bytes) + (1024 * 1024),
        },
        timeout_seconds=settings.upload_timeout_seconds,
    )
    store = JobStore(settings.work_dir / "jobs")
    work_dir_lease = WorkDirLease(settings.work_dir / ".api-instance.lock")
    executor = ThreadPoolExecutor(max_workers=settings.max_workers, thread_name_prefix="zk-stego")
    capacity = threading.BoundedSemaphore(settings.max_workers + settings.max_queued_jobs)
    artifact_cleanup_stop = threading.Event()
    artifact_cleanup_thread: threading.Thread | None = None
    artifact_lock = threading.Lock()
    app.state.settings, app.state.store, app.state.executor = settings, store, executor
    app.state.work_dir_lease = work_dir_lease

    def require_token(authorization: str | None = Header(default=None)) -> None:
        expected = f"Bearer {settings.api_token}"
        if not authorization or not secrets.compare_digest(authorization, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")

    def reserve_capacity() -> None:
        if not capacity.acquire(blocking=False):
            raise HTTPException(status_code=503, detail="job capacity reached; retry later", headers={"Retry-After": "1"})

    def cleanup_inputs(job_id: str, operation: str) -> None:
        directory = settings.work_dir / "files" / job_id
        filenames = {
            "embed": ("cover.h264",),
            "verify": ("stego.h264", "original.h264"),
            "extract": ("stego.h264",),
        }.get(operation, ())
        for filename in filenames:
            try:
                (directory / filename).unlink(missing_ok=True)
            except OSError:
                continue

    def submit(job_id: str, operation: str, handler: Callable[[], dict[str, Any]]) -> None:
        def run() -> None:
            try:
                store.update(job_id, status="running")
                try:
                    result = handler()
                    store.update(job_id, status="succeeded", result=result)
                except Exception as exc:  # Do not expose paths, secrets, or internal tracebacks.  # noqa: BLE001
                    store.update(job_id, status="failed", error=f"{operation} failed: {type(exc).__name__}")
            finally:
                try:
                    cleanup_inputs(job_id, operation)
                finally:
                    capacity.release()
        try:
            executor.submit(run)
        except Exception:
            try:
                store.update(job_id, status="failed", error=f"{operation} could not be scheduled")
            finally:
                try:
                    cleanup_inputs(job_id, operation)
                finally:
                    capacity.release()
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
                    main_artifact = job_dir / "stego.h264"
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

    def run_artifact_cleanup() -> None:
        interval = min(60.0, max(1.0, settings.artifact_ttl_seconds / 2.0))
        while not artifact_cleanup_stop.wait(interval):
            sweep_expired_extract_artifacts()

    def recover_interrupted_jobs() -> None:
        files_root = settings.work_dir / "files"
        for record in store.all_records():
            job_id = record.get("job_id")
            if not isinstance(job_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{24}", job_id) is None:
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
            artifact_cleanup_stop.clear()
            artifact_cleanup_thread = threading.Thread(
                target=run_artifact_cleanup, name="zk-stego-artifact-cleanup", daemon=True,
            )
            artifact_cleanup_thread.start()
            app.state.artifact_cleanup_thread = artifact_cleanup_thread
            app.state.sweep_expired_extract_artifacts = sweep_expired_extract_artifacts
            app.state.recover_interrupted_jobs = recover_interrupted_jobs
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
        chaos_key_b64: str | None = Form(default=None),
        ffmpeg_validate: bool = Form(default=False),
    ) -> dict[str, str]:
        message, secret_key = _decode_message(message_b64), _decode_key(secret_key_b64, "secret_key_b64")
        chaos_key = _decode_key(chaos_key_b64, "chaos_key_b64") if chaos_key_b64 else None
        reserve_capacity()
        job_dir_created = False
        try:
            record = store.create("embed")
            job_dir = settings.work_dir / "files" / record["job_id"]
            job_dir.mkdir(parents=True, exist_ok=False)
            job_dir_created = True
            input_path, output_path = job_dir / "cover.h264", job_dir / "stego.h264"
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
                circuits_dir=str(settings.circuits_dir), secret_key=secret_key, chaos_key=chaos_key,
                ffmpeg_validate=ffmpeg_validate,
            )
            return _safe_embed_result(result, output_path.name)

        submit(record["job_id"], "embed", perform)
        return {"job_id": record["job_id"], "status": "queued"}

    @app.post("/api/v1/jobs/verify", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_token)])
    async def start_verify(
        stego_video: UploadFile = File(...),  # noqa: B008
        original_video: UploadFile = File(...),  # noqa: B008
        secret_key_b64: str = Form(...),
        message_length: int = Form(..., ge=1, le=4096),
        chaos_key_b64: str | None = Form(default=None),
    ) -> dict[str, str]:
        if verify_handler is None:
            raise HTTPException(status_code=501, detail="proof verification is not configured for this service")
        secret_key = _decode_key(secret_key_b64, "secret_key_b64")
        chaos_key = _decode_key(chaos_key_b64, "chaos_key_b64") if chaos_key_b64 else None
        reserve_capacity()
        job_dir_created = False
        try:
            record = store.create("verify")
            job_dir = settings.work_dir / "files" / record["job_id"]
            job_dir.mkdir(parents=True, exist_ok=False)
            job_dir_created = True
            stego_path, original_path = job_dir / "stego.h264", job_dir / "original.h264"
            await _save_upload(stego_video, stego_path, settings.max_upload_bytes)
            await _save_upload(original_video, original_path, settings.max_upload_bytes)
        except BaseException:
            try:
                if "record" in locals():
                    abandon_upload(record["job_id"], job_dir, job_dir_created)
            finally:
                capacity.release()
            raise

        def perform() -> dict[str, Any]:
            result = verify_handler(
                stego_video_path=str(stego_path), original_video_path=str(original_path),
                circuits_dir=str(settings.circuits_dir), secret_key=secret_key,
                message_length=message_length, chaos_key=chaos_key,
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
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        return record

    @app.get("/api/v1/jobs/{job_id}/artifact", dependencies=[Depends(require_token)])
    def download_artifact(job_id: str) -> FileResponse:
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


app = create_app() if os.environ.get("ZK_STEGO_API_TOKEN") else None
