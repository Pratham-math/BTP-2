"""Construct exactly the providers belonging to a validated preset."""

from server.config import JobSettings
from server.providers.base import GenerationError


def create_providers(settings: JobSettings, api_key: str | None = None):
    if settings.mode == "local":
        from server.providers.ollama_text import OllamaTextProvider
        from server.providers.piper_tts import PiperSpeechProvider
        return (OllamaTextProvider(settings.text_model, settings.text_identity),
                PiperSpeechProvider(settings.voice, settings.speech_identity, settings.speech_rate))
    if not api_key:
        raise GenerationError("KEY_MISSING", "Gemini is not configured. Add an API key in Settings.")
    from server.providers.gemini_text import GeminiTextProvider, create_client
    from server.providers.gemini_tts import GeminiSpeechProvider
    client = create_client(api_key)
    return GeminiTextProvider(client, settings.text_model), GeminiSpeechProvider(client, settings.speech_model, settings.voice)
