"""Non-secret, versioned settings. Provider endpoints stay on the backend."""

import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


PROJECT_DIR = Path(__file__).resolve().parents[1]
PROFILES = {"720p24": (1280, 720, 24), "480p24": (854, 480, 24)}


class GenerationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    mode: Literal["cloud", "local"] = "cloud"
    text_model: str = Field(default="", max_length=120, pattern=r"^[a-zA-Z0-9_.:/-]*$")
    voice: str = Field(default="", max_length=80, pattern=r"^[a-zA-Z0-9_-]*$")
    render_profile: Literal["720p24", "480p24"] = "720p24"
    speech_rate: float = Field(default=1.0, ge=0.75, le=1.5)


class JobSettings(GenerationSettings):
    schema_version: Literal[2] = 2
    text_provider: Literal["gemini", "ollama"]
    speech_provider: Literal["gemini", "piper"]
    speech_model: str
    text_identity: dict = Field(default_factory=dict)
    speech_identity: dict = Field(default_factory=dict)
    prompt_template_version: str = "visual-v2"
    allow_cloud_fallback: Literal[False] = False

    @model_validator(mode="after")
    def check_preset(self):
        expected = ("ollama", "piper") if self.mode == "local" else ("gemini", "gemini")
        if (self.text_provider, self.speech_provider) != expected:
            raise ValueError("The selected mode requires its matching text and speech providers")
        if not self.text_model or not self.voice:
            raise ValueError("A model and voice are required")
        return self


def snapshot_settings(selection: GenerationSettings) -> JobSettings:
    values = selection.model_dump()
    local = selection.mode == "local"
    if not local and selection.speech_rate != 1:
        raise ValueError("Cloud narration currently uses its default speaking rate")
    values.update(
        text_provider="ollama" if local else "gemini",
        speech_provider="piper" if local else "gemini",
        text_model=selection.text_model or os.getenv("OLLAMA_MODEL" if local else "GEMINI_TEXT_MODEL",
                                                   "qwen3:4b-q4_K_M" if local else "gemini-3.5-flash-lite"),
        speech_model="piper" if local else os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts"),
        voice=selection.voice or os.getenv("PIPER_VOICE" if local else "GEMINI_VOICE",
                                         "en_US-lessac-medium" if local else "Kore"),
        prompt_template_version="local-v7" if local else "visual-v2",
    )
    return JobSettings.model_validate(values)


def saved_settings(values: dict) -> JobSettings:
    if "schema_version" in values:
        return JobSettings.model_validate(values)
    # Existing saved jobs used these three Gemini settings.
    result = snapshot_settings(GenerationSettings(text_model=values.get("text_model", ""),
                                                 voice=values.get("voice", "")))
    if values.get("tts_model"):
        result.speech_model = values["tts_model"]
    return result


def valid_api_key() -> str | None:
    value = os.getenv("GEMINI_API_KEY", "").strip()
    return value if value and value != "put_your_key_here" else None


def voices_dir() -> Path:
    folder = Path(os.getenv("PIPER_VOICES_DIR", str(PROJECT_DIR / ".local" / "voices")))
    return (folder if folder.is_absolute() else PROJECT_DIR / folder).resolve()


def ollama_url() -> str:
    value = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("OLLAMA_URL must be an HTTP loopback address without a path or credentials")
    port = parsed.port or 11434
    host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
    return f"http://{host}:{port}"
