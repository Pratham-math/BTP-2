import os
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from server.generator import run_generation
from server.storage import Storage, public_status


PROJECT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_DIR / ".env")

configured_data_dir = Path(os.getenv("DATA_DIR", "./data"))
if not configured_data_dir.is_absolute():
    configured_data_dir = PROJECT_DIR / configured_data_dir

storage = Storage(configured_data_dir)
generation_lock = Lock()


@asynccontextmanager
async def lifespan(_: FastAPI):
    storage.mark_interrupted_jobs()
    yield


app = FastAPI(title="Prompt to Video", version="1.0.0", lifespan=lifespan)


class VideoRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)

    @field_validator("prompt")
    @classmethod
    def clean_prompt(cls, prompt: str) -> str:
        prompt = prompt.strip()
        if len(prompt) < 3:
            raise ValueError("Enter at least 3 characters")
        return prompt


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "gemini_configured": bool(valid_api_key()),
        "ffmpeg": executable_available("ffmpeg"),
        "ffprobe": executable_available("ffprobe"),
    }


@app.post("/api/videos", status_code=202)
def create_video(request: VideoRequest, background_tasks: BackgroundTasks) -> dict:
    api_key = valid_api_key()
    if not api_key:
        raise HTTPException(
            503,
            "Gemini is not configured. Copy .env.example to .env and set GEMINI_API_KEY.",
        )
    if not executable_available("ffmpeg") or not executable_available("ffprobe"):
        raise HTTPException(503, "FFmpeg and ffprobe must be installed and available on PATH.")
    if not generation_lock.acquire(blocking=False):
        raise HTTPException(409, "Another video is being generated. Wait for it to finish.")

    job_id = uuid4().hex
    text_model = os.getenv("GEMINI_TEXT_MODEL", "gemini-3.5-flash-lite")
    tts_model = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
    voice = os.getenv("GEMINI_VOICE", "Kore")
    try:
        storage.create_job(
            job_id,
            request.prompt,
            {"text_model": text_model, "tts_model": tts_model, "voice": voice},
        )
        background_tasks.add_task(
            run_and_unlock,
            job_id,
            request.prompt,
            api_key,
            text_model,
            tts_model,
            voice,
        )
    except Exception:
        generation_lock.release()
        raise
    return {"id": job_id, "state": "queued"}


@app.get("/api/videos")
def list_videos() -> list[dict]:
    return storage.list_jobs()


@app.get("/api/videos/{job_id}")
def get_video_status(job_id: str) -> dict:
    try:
        return public_status(storage.read_status(job_id))
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "Video not found")


@app.post("/api/videos/{job_id}/retry", status_code=202)
def retry_video(job_id: str, background_tasks: BackgroundTasks) -> dict:
    api_key = valid_api_key()
    if not api_key:
        raise HTTPException(503, "Gemini is not configured. Set GEMINI_API_KEY in .env.")
    try:
        status = storage.read_status(job_id)
        prompt = (storage.job_dir(job_id) / "prompt.txt").read_text(encoding="utf-8")
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "Video not found")
    if status["state"] != "failed":
        raise HTTPException(409, "Only a failed video can be retried.")
    if not generation_lock.acquire(blocking=False):
        raise HTTPException(409, "Another video is being generated. Wait for it to finish.")

    settings = {
        "text_model": os.getenv("GEMINI_TEXT_MODEL", "gemini-3.5-flash-lite"),
        "tts_model": os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts"),
        "voice": os.getenv("GEMINI_VOICE", "Kore"),
    }
    storage.update_status(
        job_id, state="queued", stage="Waiting to retry", error=None, settings=settings
    )
    background_tasks.add_task(
        run_and_unlock,
        job_id,
        prompt,
        api_key,
        settings["text_model"],
        settings["tts_model"],
        settings["voice"],
    )
    return {"id": job_id, "state": "queued"}


@app.get("/api/videos/{job_id}/file")
def stream_video(job_id: str) -> FileResponse:
    path = ready_video_path(job_id)
    return FileResponse(path, media_type="video/mp4", filename=None)


@app.get("/api/videos/{job_id}/download")
def download_video(job_id: str) -> FileResponse:
    path = ready_video_path(job_id)
    return FileResponse(path, media_type="video/mp4", filename=f"learning-video-{job_id[:8]}.mp4")


def ready_video_path(job_id: str) -> Path:
    try:
        status = storage.read_status(job_id)
        path = storage.job_dir(job_id) / "video.mp4"
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "Video not found")
    if status["state"] != "ready" or not path.exists() or path.stat().st_size == 0:
        raise HTTPException(409, "Video is not ready yet")
    return path


def run_and_unlock(*args) -> None:
    try:
        run_generation(storage, *args)
    finally:
        generation_lock.release()


def valid_api_key() -> str | None:
    value = os.getenv("GEMINI_API_KEY", "").strip()
    if not value or value == "put_your_key_here":
        return None
    return value


def executable_available(name: str) -> bool:
    import shutil
    return shutil.which(name) is not None


frontend = PROJECT_DIR / "client" / "dist"
if frontend.exists():
    app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
