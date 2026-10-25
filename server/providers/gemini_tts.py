"""The existing Gemini Interactions speech request behind a speech provider."""

import base64
import os
import time
import wave
from pathlib import Path
from google import genai
from server.providers.base import inspect_audio


def generate_audio(
    client: genai.Client,
    narration: str,
    output_path: Path,
    model: str,
    voice: str,
    *, metadata_style=False, admit=None,
) -> None:
    speech_prompt = (
        "Speak in a warm, clear, patient teaching voice at a moderate pace. "
        "Read only the following narration:\n\n" + narration
    )
    interaction = call_tts_with_retry(client, model, narration if metadata_style else speech_prompt, voice, metadata_style=metadata_style, admit=admit)
    audio = interaction.output_audio
    if audio is None or not audio.data:
        raise RuntimeError("Gemini returned no speech audio")

    pcm = decode_audio_bytes(audio.data)
    temp_path = output_path.with_suffix(".tmp.wav")
    if pcm.startswith(b"RIFF"):
        temp_path.write_bytes(pcm)
    else:
        # Gemini TTS currently returns mono, 24 kHz, signed 16-bit PCM.
        with wave.open(str(temp_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(24_000)
            wav_file.writeframes(pcm)
    inspect_audio(temp_path)
    os.replace(temp_path, output_path)


def call_tts_with_retry(client: genai.Client, model: str, prompt: str, voice: str, *, metadata_style=False, admit=None):
    for attempt in range(2):
        try:
            if admit: admit()
            return client.interactions.create(
                model=model,
                input=[{"type": "user_input", "content": [{"type": "text", "text": prompt,
                    "annotations": [{"type": "speech_metadata", "style": "Warm, patient teaching; clear diction at a moderate pace."}]}]}] if metadata_style else prompt,
                response_format={"type": "audio"},
                generation_config={"speech_config": [{"voice": voice}]},
            )
        except Exception as error:
            message = str(error).lower()
            transient = "429" in message or "resource_exhausted" in message or "timeout" in message
            if attempt == 0 and transient:
                from server.runtime import CURRENT_CONTROL, checkpoint
                control = CURRENT_CONTROL.get()
                if control:
                    control.cancel_requested.wait(12)
                    checkpoint()
                else:
                    time.sleep(12)
                continue
            raise
    raise RuntimeError("Gemini speech generation failed")


def decode_audio_bytes(value: str | bytes) -> bytes:
    if isinstance(value, str):
        return base64.b64decode(value, validate=True)
    if value.startswith(b"RIFF"):
        return value
    # Interactions audio is base64. Some SDK versions expose it as bytes instead
    # of text, while older generate-content responses expose decoded PCM bytes.
    try:
        decoded = base64.b64decode(value, validate=True)
        if decoded:
            return decoded
    except (ValueError, base64.binascii.Error):
        pass
    return value



class GeminiSpeechProvider:
    def __init__(self, client, model, voice, *, metadata_style=False, admit=None):
        self.client, self.model, self.voice = client, model, voice
        self.metadata_style, self.admit = metadata_style, admit
        self.identity = {"provider": "gemini", "model": model, "voice": voice, "protocol": "metadata-v1" if metadata_style else "legacy-instructions-v1"}

    def synthesize(self, text, output_path):
        from server.runtime import checkpoint
        checkpoint()
        generate_audio(self.client, text, output_path, self.model, self.voice, metadata_style=self.metadata_style, admit=self.admit)
        checkpoint()
        return inspect_audio(output_path, self.identity)

    def close(self):
        pass
