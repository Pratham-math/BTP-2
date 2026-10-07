import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class Storage:
    """Store each video job in one local folder using atomic JSON writes."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._write_lock = Lock()

    def job_dir(self, job_id: str) -> Path:
        if not ID_PATTERN.fullmatch(job_id):
            raise ValueError("Invalid video ID")
        path = self.data_dir / job_id
        if path.resolve().parent != self.data_dir or path.is_symlink():
            raise ValueError("Job directory must stay inside data storage")
        return path

    def create_job(self, job_id: str, prompt: str, settings: dict, request_id: str | None = None) -> None:
        folder = self.job_dir(job_id)
        folder.mkdir(parents=True, exist_ok=False)
        self.write_json(
            folder / "status.json",
            {
                "id": job_id,
                "state": "queued",
                "stage": "Waiting to start",
                "current": 0,
                "total": 3,
                "error": None,
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "settings": settings,
                "request_id": request_id,
                "error_code": None,
            },
        )
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
        self.write_json(folder / "request.json", {"schema_version": 2, "prompt": prompt,
                                                  "settings": settings, "request_id": request_id})

    def read_status(self, job_id: str) -> dict[str, Any]:
        path = self.job_dir(job_id) / "status.json"
        if not path.exists():
            raise FileNotFoundError(job_id)
        if path.is_symlink() or path.resolve().parent != self.job_dir(job_id).resolve():
            raise ValueError("Invalid status path")
        status = json.loads(path.read_text(encoding="utf-8"))
        if status.get("id") != job_id or status.get("state") not in {
            "queued", "running", "ready", "failed", "interrupted", "cancelling", "cancelled"
        }:
            raise ValueError("Invalid saved job status")
        return status

    def find_request(self, request_id: str) -> dict | None:
        for path in self.data_dir.glob("*/status.json"):
            try:
                status = self.read_status(path.parent.name)
                if status.get("request_id") == request_id:
                    return status
            except (OSError, ValueError):
                continue
        return None

    def update_status(self, job_id: str, **changes: Any) -> dict[str, Any]:
        with self._write_lock:
            status = self.read_status(job_id)
            status.update(changes)
            status["updated_at"] = now_iso()
            self._write_json_unlocked(self.job_dir(job_id) / "status.json", status)
        return status

    def list_jobs(self) -> list[dict[str, Any]]:
        jobs = []
        for path in self.data_dir.glob("*/status.json"):
            try:
                status = self.read_status(path.parent.name)
                jobs.append(public_status(status))
            except (OSError, ValueError):
                continue
        return sorted(jobs, key=lambda item: item["created_at"], reverse=True)[:10]

    def mark_interrupted_jobs(self) -> None:
        for path in self.data_dir.glob("*/status.json"):
            try:
                status = self.read_status(path.parent.name)
                if status.get("state") in {"queued", "running", "cancelling"}:
                    self.update_status(
                        status["id"],
                        state="interrupted",
                        stage="Interrupted",
                        error="The server stopped while this video was being made. Retry it.",
                        error_code="INTERRUPTED",
                    )
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue

    def write_json(self, path: Path, value: Any) -> None:
        with self._write_lock:
            self._write_json_unlocked(path, value)

    @staticmethod
    def _write_json_unlocked(path: Path, value: Any) -> None:
        atomic_json(path, value)


def public_status(status: dict[str, Any]) -> dict[str, Any]:
    result = {key: status.get(key) for key in (
        "id", "state", "stage", "stage_code", "current", "total", "error", "error_code", "action",
        "created_at", "updated_at", "started_at", "finished_at", "heartbeat_at", "title"
    )}
    settings = status.get("settings", {})
    result["mode"] = settings.get("mode", "cloud")
    result["providers"] = {"text": settings.get("text_provider", "gemini"),
                           "speech": settings.get("speech_provider", "gemini")}
    if status.get("started_at"):
        end = datetime.fromisoformat(status.get("finished_at") or now_iso())
        result["elapsed_seconds"] = max(0, round((end - datetime.fromisoformat(status["started_at"])).total_seconds()))
    return result


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: Any):
    if path.is_symlink():
        raise ValueError("Cannot write through a symbolic link")
    temp = path.with_suffix(path.suffix + ".tmp")
    if temp.is_symlink():
        raise ValueError("Cannot write through a symbolic link")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
