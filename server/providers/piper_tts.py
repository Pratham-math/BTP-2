"""Offline Piper narration with one supervised voice process per job."""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from server.artifacts import file_hash
from server.config import PROJECT_DIR, voices_dir
from server.providers.base import GenerationError, inspect_audio
from server.runtime import checkpoint, stop_process
from server.owned_process import close_owned_job, spawn_owned
from server.providers.piper_runtime import piper_device, require_cuda


def installed_voices() -> list[dict]:
    result = []
    folder = voices_dir()
    if not folder.exists():
        return result
    for model in sorted(folder.glob("*.onnx")):
        config = model.with_suffix(".onnx.json")
        if (model.is_symlink() or config.is_symlink() or not config.is_file()
                or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", model.stem)):
            continue
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
            rate = data.get("audio", {}).get("sample_rate")
            language = data.get("language", {}).get("code", "")
            if (not isinstance(rate, int) or not 8000 <= rate <= 96000 or model.stat().st_size == 0
                    or not language.startswith("en") or data.get("phoneme_type", "espeak") not in {"espeak", "text"}):
                continue
            result.append({"id": model.stem, "sample_rate": rate, "size": model.stat().st_size})
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return result


def voice_identity(voice_id: str) -> dict:
    if voice_id not in {item["id"] for item in installed_voices()}:
        raise GenerationError("VOICE_NOT_INSTALLED", "The selected Piper voice is not installed with its configuration.",
                              "Download the voice's ONNX and ONNX JSON files into the configured voices directory.")
    from importlib.metadata import PackageNotFoundError, version
    model = voices_dir() / f"{voice_id}.onnx"
    try:
        engine_version = version("piper-tts")
    except PackageNotFoundError as error:
        raise GenerationError("DEPENDENCY_MISSING", "The Piper speech distribution is not installed.",
                              "Install requirements-local.txt in the project Python environment.") from error
    device = piper_device()
    if device == "cuda":
        import onnxruntime
        require_cuda(onnxruntime)
    return {"provider": "piper", "voice": voice_id, "device": device, "model_digest": file_hash(model),
            "config_digest": file_hash(model.with_suffix(".onnx.json")), "engine_version": engine_version}


class PiperSpeechProvider:
    def __init__(self, voice_id: str, identity: dict, rate: float = 1):
        self.voice_id, self.identity, self.rate = voice_id, identity, rate
        self.process = None
        self.responses = queue.Queue(maxsize=8)
        self.reader = None

    def _start(self, folder: Path):
        model = voices_dir() / f"{self.voice_id}.onnx"
        env = {key: value for key, value in os.environ.items()
               if key.upper() not in {"GEMINI_API_KEY", "GOOGLE_API_KEY"}}
        env.update(PYTHONIOENCODING="utf-8", OMP_NUM_THREADS="2")
        options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        self.process = spawn_owned(
            [sys.executable, "-u", "-m", "server.providers.piper_worker", str(model),
             str(model.with_suffix(".onnx.json")), str(folder), str(self.rate), self.identity.get("device", "cpu")],
            cwd=PROJECT_DIR, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", shell=False, **options)

        def read():
            while True:
                line = self.process.stdout.readline(10000)
                if not line:
                    self.responses.put(None)
                    break
                self.responses.put(line)
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        ready = self._response()
        if ready.get("code") == "TTS_GPU_UNAVAILABLE":
            raise GenerationError(ready["code"], ready["message"], ready.get("action"))
        if ready.get("ready") is not True:
            raise GenerationError("TTS_FAILED", "Piper could not load the selected voice.",
                                  "Check that the voice and Piper package are compatible.")

    def _response(self):
        deadline = time.monotonic() + 180
        while True:
            checkpoint()
            if time.monotonic() > deadline:
                raise GenerationError("TTS_FAILED", "Piper exceeded the narration time limit.")
            try:
                line = self.responses.get(timeout=.1)
            except queue.Empty:
                continue
            if line is None:
                raise GenerationError("TTS_FAILED", "The Piper speech process stopped unexpectedly.")
            try:
                result = json.loads(line)
                if not isinstance(result, dict):
                    raise ValueError("Invalid response")
                return result
            except ValueError as error:
                raise GenerationError("TTS_FAILED", "The Piper process returned an invalid response.") from error

    def synthesize(self, text: str, output_path: Path):
        checkpoint()
        try:
            if self.process is None:
                self._start(output_path.parent.resolve())
            temporary = output_path.with_suffix(".tmp.wav")
            request = {"text": text, "filename": temporary.name}
            self.process.stdin.write(json.dumps(request) + "\n")
            self.process.stdin.flush()
            reply = self._response()
            if reply.get("ok") is not True or reply.get("filename") != temporary.name:
                raise GenerationError("TTS_FAILED", "Piper could not synthesize this narration.")
            artifact = inspect_audio(temporary, self.identity)
            checkpoint()
            os.replace(temporary, output_path)
            return artifact
        except (OSError, BrokenPipeError) as error:
            raise GenerationError("TTS_FAILED", "The Piper speech process could not complete narration.") from error

    def close(self):
        if self.process:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                stop_process(self.process)
            finally:
                close_owned_job(self.process)
            self.process.stdout.close()
            if self.reader:
                self.reader.join(timeout=2)
