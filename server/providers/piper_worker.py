"""Owned speech subprocess: load one voice, serve only bounded WAV requests."""

import json
import re
import sys
import wave
from contextlib import redirect_stdout
from pathlib import Path


def main():
    # This speech process has all required assets before it starts. Python
    # phonemizers must never fetch extra resources during a local job.
    def no_network(event, _args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            raise RuntimeError("Network access is disabled in the local speech process")
    sys.addaudithook(no_network)
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    from piper import SynthesisConfig
    from server.providers.piper_runtime import load_voice

    model, config, output_dir = (Path(value).resolve() for value in sys.argv[1:4])
    rate = float(sys.argv[4])
    if not model.is_file() or not config.is_file() or model.is_symlink() or config.is_symlink():
        raise ValueError("Voice assets must be installed before synthesis")
    device = sys.argv[5] if len(sys.argv) > 5 else "cpu"
    if device not in {"cpu", "cuda"}:
        raise ValueError("Invalid speech device")
    # DLL loaders sometimes print diagnostics; stdout is our JSON protocol.
    with redirect_stdout(sys.stderr):
        voice = load_voice(model, config, device)
    settings = SynthesisConfig(length_scale=1.0 / rate, normalize_audio=True)
    print(json.dumps({"ready": True, "device": device}), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            name, text = request["filename"], request["text"]
            if not re.fullmatch(r"scene-\d{1,2}(-utterance-\d{1,2})?\.tmp\.wav", name) or not isinstance(text, str) or not 1 <= len(text) <= 1200:
                raise ValueError("Invalid speech request")
            output = output_dir / name
            if output.is_symlink() or output.resolve().parent != output_dir:
                raise ValueError("Invalid output path")
            with wave.open(str(output), "wb") as wav_file:
                voice.synthesize_wav(text, wav_file, syn_config=settings)
            print(json.dumps({"filename": name, "ok": True}), flush=True)
        except Exception:
            print(json.dumps({"ok": False}), flush=True)
            return


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Private narration and local paths must not become provider diagnostics.
        from server.providers.base import GenerationError
        failure = {"ok": False}
        if isinstance(error, GenerationError):
            failure.update(code=error.code, message=str(error), action=error.action)
        print(json.dumps(failure), flush=True)
        raise SystemExit(1)
