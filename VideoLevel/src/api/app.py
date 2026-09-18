"""Small, fail-closed HTTP API around the existing embed/verify runtime."""

from __future__ import annotations

import base64
import json
import os
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from src.embedder import embed
from src.verifier import verify


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ApiSettings:
    api_token: str
    work_dir: Path = Path(".cache/api")
    circuits_dir: Path = Path("circuits")
    max_upload_bytes: int = 100 * 1024 * 1024
    max_workers: int = 1

    @classmethod
    def from_environment(cls) -> "ApiSettings":
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

    def update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            record = self._records[job_id]
            record.update(changes, updated_at=_now())
            self._persist(record)

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


def create_app(
    settings: ApiSettings | None = None,
    *,
    embed_handler: Callable[..., Any] = embed,
    verify_handler: Callable[..., Any] = verify,
) -> FastAPI:
    settings = settings or ApiSettings.from_environment()
    app = FastAPI(title="ZK-Stego Video API", version="1.0.0", docs_url="/docs", redoc_url=None)
    store = JobStore(settings.work_dir / "jobs")
    executor = ThreadPoolExecutor(max_workers=settings.max_workers, thread_name_prefix="zk-stego")
    app.state.settings, app.state.store, app.state.executor = settings, store, executor

    def require_token(authorization: str | None = Header(default=None)) -> None:
        expected = f"Bearer {settings.api_token}"
        if not authorization or not secrets.compare_digest(authorization, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")

    def submit(job_id: str, operation: str, handler: Callable[[], dict[str, Any]]) -> None:
        def run() -> None:
            store.update(job_id, status="running")
            try:
                result = handler()
                store.update(job_id, status="succeeded", result=result)
            except Exception as exc:  # Do not expose paths, secrets, or internal tracebacks.
                store.update(job_id, status="failed", error=f"{operation} failed: {type(exc).__name__}")
        executor.submit(run)

    @app.on_event("shutdown")
    def shutdown() -> None:
        executor.shutdown(wait=True, cancel_futures=False)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "zk-stego-video"}

    @app.post("/api/v1/jobs/embed", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_token)])
    async def start_embed(
        video: UploadFile = File(...),
        message_b64: str = Form(...),
        secret_key_b64: str = Form(...),
        chaos_key_b64: str | None = Form(default=None),
        ffmpeg_validate: bool = Form(default=False),
    ) -> dict[str, str]:
        message, secret_key = _decode_message(message_b64), _decode_key(secret_key_b64, "secret_key_b64")
        chaos_key = _decode_key(chaos_key_b64, "chaos_key_b64") if chaos_key_b64 else None
        record = store.create("embed")
        job_dir = settings.work_dir / "files" / record["job_id"]
        job_dir.mkdir(parents=True, exist_ok=False)
        input_path, output_path = job_dir / "cover.h264", job_dir / "stego.h264"
        await _save_upload(video, input_path, settings.max_upload_bytes)

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
        stego_video: UploadFile = File(...),
        original_video: UploadFile = File(...),
        secret_key_b64: str = Form(...),
        message_length: int = Form(..., ge=1, le=4096),
        chaos_key_b64: str | None = Form(default=None),
    ) -> dict[str, str]:
        secret_key = _decode_key(secret_key_b64, "secret_key_b64")
        chaos_key = _decode_key(chaos_key_b64, "chaos_key_b64") if chaos_key_b64 else None
        record = store.create("verify")
        job_dir = settings.work_dir / "files" / record["job_id"]
        job_dir.mkdir(parents=True, exist_ok=False)
        stego_path, original_path = job_dir / "stego.h264", job_dir / "original.h264"
        await _save_upload(stego_video, stego_path, settings.max_upload_bytes)
        await _save_upload(original_video, original_path, settings.max_upload_bytes)

        def perform() -> dict[str, Any]:
            result = verify_handler(
                stego_video_path=str(stego_path), original_video_path=str(original_path),
                circuits_dir=str(settings.circuits_dir), secret_key=secret_key,
                message_length=message_length, chaos_key=chaos_key,
            )
            return _safe_verify_result(result)

        submit(record["job_id"], "verify", perform)
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
        artifact = settings.work_dir / "files" / job_id / "stego.h264"
        if not record or record.get("status") != "succeeded" or record.get("operation") != "embed" or not artifact.is_file():
            raise HTTPException(status_code=404, detail="artifact not available")
        return FileResponse(artifact, media_type="video/h264", filename="stego.h264")

    return app


app = create_app() if os.environ.get("ZK_STEGO_API_TOKEN") else None
