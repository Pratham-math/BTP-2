"""Provider contracts and safe errors shared with the coordinator."""

import math
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Protocol

from server.script import VideoScript


class GenerationError(RuntimeError):
    def __init__(self, code: str, message: str, action: str | None = None):
        super().__init__(message)
        self.code = code
        self.action = action


@dataclass(frozen=True)
class AudioArtifact:
    duration: float
    sample_rate: int
    channels: int
    sample_width: int
    identity: dict

    def metadata(self) -> dict:
        return asdict(self)


def inspect_audio(path: Path, identity: dict | None = None) -> AudioArtifact:
    try:
        with wave.open(str(path), "rb") as audio:
            rate, channels, width, count = (audio.getframerate(), audio.getnchannels(),
                                            audio.getsampwidth(), audio.getnframes())
            duration = count / rate
            if (not math.isfinite(duration) or not 0 < duration <= 300 or not 8000 <= rate <= 96000
                    or channels not in {1, 2} or width not in {1, 2, 3, 4}):
                raise ValueError("Invalid audio format or duration")
            # Validate the entire body with bounded memory, including truncation.
            remaining = count
            audible_samples = False
            while remaining:
                frames = min(remaining, 65536)
                samples = audio.readframes(frames)
                if len(samples) != frames * channels * width:
                    raise ValueError("Truncated WAV data")
                silence_byte = 128 if width == 1 else 0
                audible_samples = audible_samples or any(sample != silence_byte for sample in samples)
                remaining -= frames
            if not audible_samples:
                raise ValueError("Speech output is entirely silent")
    except (OSError, EOFError, wave.Error, ValueError, ZeroDivisionError) as error:
        raise GenerationError("TTS_FAILED", "Narration did not produce a complete, valid WAV file.",
                              "Check the selected voice and retry narration.") from error
    return AudioArtifact(duration, rate, channels, width, identity or {})


class TextProvider(Protocol):
    identity: dict

    def generate_script(self, prompt: str, workspace: Path,
                        progress: Callable[[str, int], None]) -> VideoScript: ...

    def close(self) -> None: ...


class SpeechProvider(Protocol):
    identity: dict

    def synthesize(self, text: str, output_path: Path) -> AudioArtifact: ...

    def close(self) -> None: ...
