"""Prevent more inference when a previous local call may still be running."""

import json
from uuid import uuid4
from server.config import PROJECT_DIR
from server.providers.base import GenerationError
from server.storage import atomic_json

RECOVERY_FILE = PROJECT_DIR / ".local" / "ollama-inflight.json"
INSTANCE = uuid4().hex


def recovery_required() -> bool:
    if not RECOVERY_FILE.exists():
        return False
    try:
        data = json.loads(RECOVERY_FILE.read_text(encoding="utf-8"))
        return data.get("uncertain", False) or data.get("instance") != INSTANCE
    except (OSError, ValueError):
        return True


def assert_available():
    if recovery_required():
        raise GenerationError("LOCAL_RUNTIME_UNCERTAIN", "A previous Ollama request may still be running.",
                              "Restart your dedicated Ollama runtime, then confirm the restart in Settings.")


def begin_request():
    assert_available()
    RECOVERY_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(RECOVERY_FILE, {"instance": INSTANCE, "uncertain": False})


def mark_uncertain():
    atomic_json(RECOVERY_FILE, {"instance": INSTANCE, "uncertain": True})


def finish_request():
    if RECOVERY_FILE.exists():
        RECOVERY_FILE.unlink()
