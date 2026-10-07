"""Small local API: one executor, one active job, file-backed recovery."""

import ipaddress
import json
import os
import secrets
import shutil
import socket
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from importlib.metadata import version
from importlib.util import find_spec
from pathlib import Path
from threading import Lock, RLock
from uuid import uuid4

from dotenv import load_dotenv, set_key
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from server.artifacts import ArtifactStore, file_hash, input_hash
from server.config import GenerationSettings, JobSettings, PROJECT_DIR, saved_settings, snapshot_settings, valid_api_key
from server.generator import run_generation, safe_error
from server.preflight import check_settings, provider_inventory, require_ready
from server.providers.base import GenerationError
from server.runtime import JobControl, JobHeartbeat, RuntimeLease
from server.storage import Storage, atomic_json, now_iso, public_status


ENV_FILE = PROJECT_DIR / ".env"
load_dotenv(ENV_FILE)
configured_data_dir = Path(os.getenv("DATA_DIR", "./data"))
storage = Storage(configured_data_dir if configured_data_dir.is_absolute() else PROJECT_DIR / configured_data_dir)
SETTINGS_FILE = PROJECT_DIR / ".local" / "settings.json"
generation_lock, admission_lock = Lock(), RLock()
active_jobs: dict[str, JobControl] = {}
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video")
CONTROL_TOKEN = secrets.token_urlsafe(32)
ALLOWED_ORIGINS = set(os.getenv("APP_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5173,http://localhost:5173").split(","))


@asynccontextmanager
async def lifespan(_: FastAPI):
    global executor
    lease = RuntimeLease(storage.data_dir)
    lease.acquire()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video")
    storage.mark_interrupted_jobs()
    try:
        yield
    finally:
        for control in list(active_jobs.values()):
            control.cancel_requested.set()
        # Retain the data-directory lease until owned work really stops.
        executor.shutdown(wait=True, cancel_futures=False)
        lease.release()


app = FastAPI(title="Prompt to Video", version="2.0.0", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=os.getenv("APP_HOSTS", "127.0.0.1,localhost,::1,testserver").split(","))


@app.middleware("http")
async def protect_control_surface(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        if origin and origin not in ALLOWED_ORIGINS:
            return JSONResponse({"detail": "This application origin is not allowed."}, status_code=403)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not secrets.compare_digest(
                request.headers.get("x-app-token", ""), CONTROL_TOKEN):
            return JSONResponse({"detail": "Refresh the app to establish a control session."}, status_code=403)
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def safe_validation(_: Request, error: RequestValidationError):
    # FastAPI's default error includes the submitted API key / private prompt.
    details = [{"loc": item["loc"], "msg": item["msg"], "type": item["type"]} for item in error.errors()]
    return JSONResponse({"detail": details}, status_code=422)


def local_peer(request: Request) -> bool:
    try:
        return bool(request.client and ipaddress.ip_address(request.client.host).is_loopback)
    except ValueError:
        return False


def require_owner(request: Request):
    if not local_peer(request):
        raise HTTPException(403, "Settings can only be changed from the backend computer's loopback session.")


class VideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=3, max_length=2000)
    settings: GenerationSettings | None = None
    request_id: str | None = Field(default=None, min_length=8, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")

    @field_validator("prompt")
    @classmethod
    def clean_prompt(cls, value):
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Enter at least 3 characters")
        return value


class ApiKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr


class PreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    settings: GenerationSettings
    probe: bool = True


class RuntimeResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_restarted: bool


@app.post("/api/providers/ollama/confirm-restart", dependencies=[Depends(require_owner)])
def confirm_ollama_restart(request: RuntimeResetRequest):
    if not request.confirm_restarted:
        raise HTTPException(422, "Confirm only after restarting your dedicated Ollama runtime.")
    if not generation_lock.acquire(blocking=False):
        raise HTTPException(409, "Wait for the current job to stop before confirming a runtime restart.")
    from server.providers.ollama_text import OllamaConnection
    from server.providers import ollama_recovery
    try:
        connection = OllamaConnection(timeout=5)
        try:
            connection.models()
        finally:
            connection.close()
        ollama_recovery.finish_request()
        return {"recovery_required": False}
    except GenerationError as error:
        raise HTTPException(503, str(error)) from error
    finally:
        generation_lock.release()


def current_selection() -> GenerationSettings:
    if SETTINGS_FILE.exists():
        try:
            return GenerationSettings.model_validate_json(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise HTTPException(409, "Saved settings are damaged. Restore or replace them from the backend computer.")
    return GenerationSettings()


def selected_settings(selection: GenerationSettings) -> JobSettings:
    try:
        return snapshot_settings(selection)
    except ValueError as error:
        raise HTTPException(422, "The selected generation settings are invalid.") from error


def readiness(settings: JobSettings, probe=False) -> dict:
    result = check_settings(settings, storage.data_dir, probe=probe)
    try:
        require_ready(result)
    except GenerationError as error:
        raise HTTPException(503, {"code": error.code, "message": str(error), "action": error.action,
                                  "checks": result["checks"]}) from error
    return result


@app.get("/api/session")
def session():
    return {"control_token": CONTROL_TOKEN}


@app.get("/api/health")
def health():
    return {"ok": True, "gemini_configured": bool(valid_api_key()), "ffmpeg": executable_available("ffmpeg"),
            "ffprobe": executable_available("ffprobe"), "manim": find_spec("manim") is not None}


@app.get("/api/runtime")
def runtime(request: Request):
    return {"host": socket.gethostname(), "compute_location": "backend computer",
            "personal_session": local_peer(request), "owner_settings": local_peer(request),
            "active_job": next(iter(active_jobs), None), "single_job": True,
            "versions": {name: version(name) for name in ("fastapi", "google-genai", "manim", "pydantic")}}


@app.get("/api/providers")
def providers():
    return provider_inventory()


@app.get("/api/settings")
def get_settings():
    config = selected_settings(current_selection())
    return {"api_key_configured": bool(valid_api_key()),
            "selection": {name: getattr(config, name) for name in GenerationSettings.model_fields}}


@app.put("/api/settings", dependencies=[Depends(require_owner)])
def update_settings(selection: GenerationSettings):
    config = selected_settings(selection)
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(SETTINGS_FILE, {name: getattr(config, name) for name in GenerationSettings.model_fields})
    return get_settings()


@app.put("/api/settings/api-key", dependencies=[Depends(require_owner)])
def update_api_key(request: ApiKeyRequest):
    key = request.api_key.get_secret_value().strip()
    if len(key) < 10 or len(key) > 512 or key == "put_your_key_here" or any(c in key for c in "\r\n\x00"):
        raise HTTPException(422, "Enter a valid Gemini API key.")
    try:
        ENV_FILE.touch(exist_ok=True)
        saved, _, _ = set_key(str(ENV_FILE), "GEMINI_API_KEY", key, quote_mode="always")
        if not saved:
            raise OSError("Could not update environment file")
    except OSError as error:
        raise HTTPException(500, "The API key could not be saved on the server.") from error
    os.environ["GEMINI_API_KEY"] = key
    return {"api_key_configured": True}


@app.post("/api/preflight", dependencies=[Depends(require_owner)])
def preflight(request: PreflightRequest):
    if not generation_lock.acquire(blocking=False):
        raise HTTPException(409, "Wait for the active video before running setup probes.")
    try:
        return check_settings(selected_settings(request.settings), storage.data_dir, probe=request.probe)
    finally:
        generation_lock.release()


def schedule(job_id, prompt, settings):
    control = JobControl(storage.job_dir(job_id))
    active_jobs[job_id] = control
    try:
        executor.submit(run_and_unlock, job_id, prompt, valid_api_key() if settings.mode == "cloud" else None,
                        settings=settings, control=control)
    except Exception:
        active_jobs.pop(job_id, None)
        generation_lock.release()
        storage.update_status(job_id, state="failed", error="The coordinator could not start this job.", error_code="RUNNER_UNAVAILABLE")
        raise


@app.post("/api/videos", status_code=202)
def create_video(request: VideoRequest):
    settings = selected_settings(request.settings or current_selection())
    signature = input_hash({"prompt": request.prompt, "settings": settings.model_dump(exclude={"text_identity", "speech_identity"})})
    with admission_lock:
        if request.request_id:
            previous = storage.find_request(request.request_id)
            if previous:
                if previous.get("request_hash") != signature:
                    raise HTTPException(409, "This request ID was already used with different input.")
                return public_status(previous)
        if generation_lock.locked():
            raise HTTPException(409, {"code": "BUSY", "message": "Another video is being generated. Wait for it to finish."})
        readiness(settings)
        if not generation_lock.acquire(blocking=False):
            raise HTTPException(409, "Another video is being generated.")
        job_id = uuid4().hex
        try:
            storage.create_job(job_id, request.prompt, settings.model_dump(), request.request_id)
            storage.update_status(job_id, request_hash=signature)
        except Exception:
            generation_lock.release()
            raise
        schedule(job_id, request.prompt, settings)
    return {"id": job_id, "state": "queued", "mode": settings.mode}


@app.get("/api/videos")
def list_videos():
    return storage.list_jobs()


def read_job(job_id):
    try:
        return storage.read_status(job_id)
    except (ValueError, OSError):
        raise HTTPException(404, "Video not found or its saved status is invalid")


@app.get("/api/videos/{job_id}")
def get_video_status(job_id: str):
    return public_status(read_job(job_id))


@app.post("/api/videos/{job_id}/retry", status_code=202)
def retry_video(job_id: str):
    with admission_lock:
        status = read_job(job_id)
        if status["state"] not in {"failed", "interrupted", "cancelled"}:
            raise HTTPException(409, "Only a stopped video can be resumed.")
        if generation_lock.locked():
            raise HTTPException(409, "Another video is being generated. Wait for cleanup to finish.")
        try:
            settings = saved_settings(status["settings"])
            prompt = (storage.job_dir(job_id) / "prompt.txt").read_text(encoding="utf-8")
        except (ValueError, OSError):
            raise HTTPException(409, "The saved request or settings are invalid.")
        # Preserve saved dependency identities; the coordinator compares live ones.
        readiness(settings.model_copy(deep=True))
        if not generation_lock.acquire(blocking=False):
            raise HTTPException(409, "Another video is being generated.")
        try:
            storage.update_status(job_id, state="queued", stage="Waiting to resume", error=None, error_code=None, action=None)
        except Exception:
            generation_lock.release()
            raise
        schedule(job_id, prompt, settings)
    return {"id": job_id, "state": "queued"}


@app.post("/api/videos/{job_id}/cancel", status_code=202)
def cancel_video(job_id: str):
    with admission_lock:
        status = read_job(job_id)
        control = active_jobs.get(job_id)
        if status["state"] not in {"queued", "running", "cancelling"} or not control:
            raise HTTPException(409, "This video has no active generation to cancel.")
        with control.state_lock:
            if storage.read_status(job_id)["state"] == "ready":
                raise HTTPException(409, "This video has already completed.")
            control.cancel_requested.set()
            storage.update_status(job_id, state="cancelling", stage="Cancelling; waiting for owned work to stop")
    return {"id": job_id, "state": "cancelling"}


def ready_video_path(job_id: str) -> Path:
    status = read_job(job_id)
    path = storage.job_dir(job_id) / "video.mp4"
    def invalid_output(message, code="INVALID_ARTIFACT"):
        with admission_lock:
            if storage.read_status(job_id)["state"] == "ready":
                storage.update_status(job_id, state="failed", stage="Output verification failed", stage_code="verifying",
                                      error=message, error_code=code,
                                      action="Start a new video or restore the saved manifest." if code == "STORAGE_CORRUPT" else "Resume this video to rebuild the damaged output.")
        raise HTTPException(409, message)

    if status["state"] != "ready":
        raise HTTPException(409, "Video is not ready yet")
    if not path.is_file() or path.stat().st_size == 0:
        invalid_output("The saved video output is missing or empty.")
    if path.is_symlink() or path.resolve().parent != storage.job_dir(job_id).resolve():
        invalid_output("The saved video artifact path is invalid.")
    manifest = storage.job_dir(job_id) / "manifest.json"
    if manifest.exists():
        try:
            record = ArtifactStore(storage.job_dir(job_id))._read().get("artifacts", {}).get("video")
            if not record or record["path"] != "video.mp4" or record.get("checksum") != file_hash(path):
                raise ValueError("Missing verification")
        except (ValueError, GenerationError, KeyError) as error:
            invalid_output("The saved output failed its checksum or manifest verification.", getattr(error, "code", "INVALID_ARTIFACT"))
    return path


@app.get("/api/videos/{job_id}/file")
@app.get("/api/videos/{job_id}/stream")
def stream_video(job_id: str):
    return FileResponse(ready_video_path(job_id), media_type="video/mp4")


@app.get("/api/videos/{job_id}/download")
def download_video(job_id: str):
    return FileResponse(ready_video_path(job_id), media_type="video/mp4", filename=f"learning-video-{job_id[:8]}.mp4")


def run_and_unlock(*args, **kwargs):
    job_id = args[0] if args else None
    heartbeat = JobHeartbeat(storage, job_id) if job_id else None
    if heartbeat:
        heartbeat.start()
    try:
        run_generation(storage, *args, **kwargs)
    except Exception as error:
        if job_id:
            safe = safe_error(error)
            storage.update_status(job_id, state="failed", error=str(safe), error_code=safe.code, finished_at=now_iso())
        else:
            raise
    finally:
        if heartbeat:
            heartbeat.stop()
        with admission_lock:
            if job_id:
                active_jobs.pop(job_id, None)
            generation_lock.release()


def executable_available(name: str) -> bool:
    return shutil.which(name) is not None


frontend = PROJECT_DIR / "client" / "dist"
if frontend.exists():
    app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
