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
        return self.data_dir / job_id

    def create_job(self, job_id: str, prompt: str, settings: dict[str, str]) -> None:
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
            },
        )
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8")

    def read_status(self, job_id: str) -> dict[str, Any]:
        path = self.job_dir(job_id) / "status.json"
        if not path.exists():
            raise FileNotFoundError(job_id)
        return json.loads(path.read_text(encoding="utf-8"))

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
                status = json.loads(path.read_text(encoding="utf-8"))
                jobs.append(public_status(status))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(jobs, key=lambda item: item["created_at"], reverse=True)[:10]

    def mark_interrupted_jobs(self) -> None:
        for path in self.data_dir.glob("*/status.json"):
            try:
                status = json.loads(path.read_text(encoding="utf-8"))
                if status.get("state") in {"queued", "running"}:
                    self.update_status(
                        status["id"],
                        state="failed",
                        stage="Interrupted",
                        error="The server stopped while this video was being made. Retry it.",
                    )
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue

    def write_json(self, path: Path, value: Any) -> None:
        with self._write_lock:
            self._write_json_unlocked(path, value)

    @staticmethod
    def _write_json_unlocked(path: Path, value: Any) -> None:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, path)


def public_status(status: dict[str, Any]) -> dict[str, Any]:
    return {key: status.get(key) for key in (
        "id", "state", "stage", "current", "total", "error", "created_at", "updated_at", "title"
    )}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

