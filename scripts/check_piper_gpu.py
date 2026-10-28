"""Offline GPU voice/inference check; never installs or downloads anything."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from server.config import PROJECT_DIR
from server.providers.base import GenerationError
from server.providers.piper_tts import PiperSpeechProvider, voice_identity


def main():
    import os
    load_dotenv(PROJECT_DIR / ".env")
    # This checker always checks CUDA, independent of the configured default.
    os.environ["PIPER_DEVICE"] = "cuda"
    try:
        voice = os.getenv("PIPER_VOICE", "en_US-lessac-medium")
        identity = voice_identity(voice)
        temp_root = PROJECT_DIR / ".local" / "tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="gpu-voice-check-", dir=temp_root) as folder:
            speech = PiperSpeechProvider(voice, identity)
            try:
                audio = speech.synthesize("Tinker GPU narration is ready.", Path(folder) / "scene-1.wav")
                print(f"PASS: Piper CUDA narration produced {audio.duration:.2f} seconds of audio.")
            finally:
                speech.close()
        return 0
    except GenerationError as error:
        print(f"NOT READY [{error.code}]: {error}")
        if error.action:
            print(error.action)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
