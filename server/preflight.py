"""Actionable checks with no installs, model downloads, or cloud fallback."""

import json
import os
import shutil
import threading
import time
from importlib.util import find_spec
from pathlib import Path

from server.config import GenerationSettings, JobSettings, snapshot_settings, valid_api_key
from server.providers.base import GenerationError
from server.providers.ollama_text import OllamaConnection, OllamaTextProvider
from server.providers.piper_tts import installed_voices, voice_identity
from server.providers import ollama_recovery
from server.runtime import run_command


_probes: dict[str, float] = {}
_probe_lock = threading.Lock()
_encoder_cache: tuple[str, bool] | None = None


def provider_inventory() -> dict:
    connection = None
    try:
        connection = OllamaConnection(timeout=3)
        models = connection.models()
        ollama = {"available": True, "models": models, "message": "Ollama is reachable on loopback."}
    except (GenerationError, ValueError):
        ollama = {"available": False, "models": [], "message": "Start Ollama on the backend computer."}
    finally:
        if connection:
            connection.close()
    defaults = {mode: {name: getattr(snapshot_settings(GenerationSettings(mode=mode)), name)
                       for name in GenerationSettings.model_fields} for mode in ("cloud", "local")}
    return {"defaults": defaults, "presets": [{"id": "local", "text": "ollama", "speech": "piper"},
                        {"id": "cloud", "text": "gemini", "speech": "gemini"}],
            "ollama": {**ollama, "recovery_required": ollama_recovery.recovery_required()},
            "piper": {"installed": find_spec("piper") is not None, "voices": installed_voices()},
            "gemini": {"api_key_configured": bool(valid_api_key())}}


def check_settings(settings: JobSettings, data_dir: Path, probe: bool = False) -> dict:
    checks = []
    def add(name, ready, message, code=None, action=None):
        checks.append({"name": name, "ready": bool(ready), "message": message,
                       "code": None if ready else code, "action": None if ready else action})

    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    add("ffmpeg", bool(ffmpeg and ffprobe), "FFmpeg and ffprobe are available." if ffmpeg and ffprobe else "FFmpeg / ffprobe are missing.",
        "DEPENDENCY_MISSING", "Install FFmpeg and ffprobe and add them to PATH.")
    if ffmpeg and ffprobe:
        global _encoder_cache
        if _encoder_cache is None or _encoder_cache[0] != ffmpeg:
            try:
                encoders = run_command([ffmpeg, "-hide_banner", "-encoders"], timeout=10).stdout
                _encoder_cache = (ffmpeg, "libx264" in encoders and " aac " in encoders)
            except GenerationError:
                _encoder_cache = (ffmpeg, False)
        add("encoders", _encoder_cache[1], "H.264 and AAC encoders are available." if _encoder_cache[1] else "Required H.264 / AAC encoders are unavailable.",
            "ENCODER_MISSING", "Install an FFmpeg build with libx264 and AAC encoding.")
    manim = find_spec("manim") is not None
    add("manim", manim, "Manim is installed." if manim else "Manim is missing.",
        "DEPENDENCY_MISSING", "Install the server requirements in the project Python environment.")
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        import tempfile
        with tempfile.TemporaryFile(dir=data_dir) as sample:
            sample.write(b"readiness")
        free = shutil.disk_usage(data_dir).free
        minimum = int(os.getenv("MIN_FREE_DISK_MB", "512")) * 1024 * 1024
        add("storage", free >= minimum, f"{free // (1024 ** 3)} GB free on the storage drive.",
            "DISK_FULL", "Free disk space before generating a video.")
    except OSError:
        add("storage", False, "Job storage is not writable.", "STORAGE_UNAVAILABLE", "Check permissions on the configured data directory.")

    if settings.mode == "cloud":
        key = bool(valid_api_key())
        add("gemini", key, "A Gemini key is configured; live model access has not been checked." if key else "Gemini is not configured. Add an API key in Settings.",
            "KEY_MISSING", "Add a Gemini key in Settings.")
        settings.text_identity = {"provider": "gemini", "model": settings.text_model}
        settings.speech_identity = {"provider": "gemini", "model": settings.speech_model, "voice": settings.voice}
    else:
        connection = None
        try:
            ollama_recovery.assert_available()
            connection = OllamaConnection(timeout=5)
            matches = [item for item in connection.models() if item["id"] == settings.text_model]
            if not matches:
                raise GenerationError("MODEL_NOT_INSTALLED", "The selected Ollama model is not installed.",
                                      f"Run ollama pull {settings.text_model} during setup, then check again.")
            info = connection.inspect_model(settings.text_model)
            identity = {"provider": "ollama", "model": settings.text_model,
                        "digest": matches[0]["digest"], **info}
            if not identity["digest"]:
                raise GenerationError("MODEL_UNSUPPORTED", "Ollama did not provide a model digest.")
            settings.text_identity = identity
            add("ollama", True, "The selected local model is installed.")
            from server.artifacts import input_hash
            probe_key = input_hash(identity)
            with _probe_lock:
                probed = _probes.get(probe_key, 0) > time.monotonic() - 600
            if probe and not probed:
                # Generation probes run in the bounded coordinator, outside the event loop.
                tester = OllamaTextProvider(settings.text_model, identity, OllamaConnection(timeout=120))
                try:
                    tester.probe()
                    with _probe_lock:
                        _probes[probe_key] = time.monotonic()
                    probed = True
                finally:
                    tester.close()
            add("schema_probe", probed or not probe,
                "JSON-schema setup probe passed." if probed else "Schema capability will be checked before script generation.",
                "MODEL_UNSUPPORTED", "Run Check setup to verify schema output.")
        except (GenerationError, ValueError) as error:
            name = "schema_probe" if any(c["name"] == "ollama" and c["ready"] for c in checks) else "ollama"
            add(name, False, str(error) if isinstance(error, GenerationError) else "Ollama's configured address is invalid.",
                getattr(error, "code", "LOCAL_POLICY"), getattr(error, "action", "Use a trusted loopback Ollama address."))
        finally:
            if connection:
                connection.close()
        piper = find_spec("piper") is not None
        add("piper", piper, "Piper is installed." if piper else "Piper speech is not installed.",
            "DEPENDENCY_MISSING", "Install requirements-local.txt in the project Python environment.")
        if piper:
            try:
                settings.speech_identity = voice_identity(settings.voice)
                add("voice", True, "The selected voice and its configuration are installed.")
            except GenerationError as error:
                add("voice", False, str(error), error.code, error.action)
        else:
            ready_voice = settings.voice in {item["id"] for item in installed_voices()}
            add("voice", ready_voice, "Voice files are installed." if ready_voice else "The selected Piper voice files are missing.",
                "VOICE_NOT_INSTALLED", "Download the voice's ONNX and JSON files during setup.")
    return {"ready": all(item["ready"] for item in checks), "mode": settings.mode,
            "checks": checks, "settings": settings.model_dump()}


def require_ready(result: dict):
    for item in result["checks"]:
        if not item["ready"]:
            raise GenerationError(item["code"] or "NOT_READY", item["message"], item["action"])
