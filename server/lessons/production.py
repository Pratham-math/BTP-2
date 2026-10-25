"""Measured semantic speech, captions and independently verified scene clips."""
import os
import html
import wave
from pathlib import Path

from server.artifacts import file_hash
from server.config import GenerationSettings, snapshot_settings
from server.generator import spoken_text
from server.lessons.contracts import BlockDraft, digest
from server.media import mux_animation, render_animation, verify_video
from server.providers.base import inspect_audio
from server.providers.base import GenerationError
from server.providers.registry import create_providers


def vtt_time(seconds):
    ms = round(seconds * 1000)
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def join_wavs(paths, destination):
    with wave.open(str(paths[0]), "rb") as first:
        params = first.getparams()
    with wave.open(str(destination), "wb") as output:
        output.setparams(params)
        for path in paths:
            with wave.open(str(path), "rb") as audio:
                if audio.getparams()[:3] != params[:3]:
                    raise ValueError("Utterance WAV formats differ")
                while data := audio.readframes(65536):
                    output.writeframesraw(data)
    return inspect_audio(destination)


def produce_block(draft: BlockDraft, folder: Path, context, objects, prefix):
    from server.providers.gemini_text import create_client
    from server.providers.gemini_tts import GeminiSpeechProvider
    from server.providers.piper_tts import PiperSpeechProvider, voice_identity
    folder.mkdir(parents=True, exist_ok=True)
    local = os.getenv("PLATFORM_SPEECH_PROVIDER", "gemini") == "piper"
    speech_model = os.getenv("PLATFORM_SPEECH_MODEL", "")
    if not local and not speech_model:
        raise GenerationError("MODEL_NOT_CONFIGURED", "Select and benchmark PLATFORM_SPEECH_MODEL before preparing narration.")
    from server.lessons.authoring import StructuredAuthor
    from server.platform_settings import PlatformSettings
    author = StructuredAuthor(PlatformSettings.from_env(), context)
    voice = os.getenv("PIPER_VOICE", "en_US-lessac-medium")
    speech = PiperSpeechProvider(voice, voice_identity(voice), 1) if local else GeminiSpeechProvider(
        create_client(os.getenv("GEMINI_API_KEY", "")), speech_model, os.getenv("GEMINI_VOICE", "Kore"), metadata_style=True, admit=author.quota)
    assets = []
    try:
        for index, scene in enumerate(draft.scenes, 1):
            context.check()
            paths, cues, clock = [], [], .15
            for number, utterance in enumerate(scene.utterances):
                text = spoken_text(utterance.text)
                inputs = {"text": text, "voice": speech.identity, "version": "semantic-v1"}
                path = folder / f"scene-{index}-utterance-{number}.wav"
                saved = context.saved(f"speech_{index}_{number}", inputs)
                if not saved or not path.exists() or file_hash(path) != saved["checksum"]:
                    speech.synthesize(text, path)
                    context.check()
                    context.save(f"speech_{index}_{number}", inputs, {"checksum": file_hash(path)})
                artifact = inspect_audio(path)
                paths.append(path)
                cues.append({"start": clock, "end": clock + artifact.duration, "text": utterance.text, "visual_step": utterance.visual_step})
                clock += artifact.duration
            audio = folder / f"scene-{index}.wav"
            artifact = join_wavs(paths, audio)
            duration = artifact.duration + .5
            inputs = {"scene": scene.model_dump(), "audio": file_hash(audio), "duration": duration,
                      "cues": cues, "template": "platform-manim-v2", "profile": "720p24"}
            silent, clip = folder / f"scene-{index}.silent.mp4", folder / f"scene-{index}.mp4"
            saved = context.saved(f"render_{index}", inputs)
            if not saved or not clip.exists() or file_hash(clip) != saved["checksum"]:
                render_animation(scene, duration, silent, index, len(draft.scenes), "720p24", cue_times=[x["start"] for x in cues], cue_steps=[x["visual_step"] for x in cues])
                context.check()
                mux_animation(silent, audio, clip, "720p24", .15, .35)
                verify_video(clip, expected_duration=duration, decode=True)
                context.check()
                context.save(f"render_{index}", inputs, {"checksum": file_hash(clip), "duration": duration})
            caption = folder / f"scene-{index}.vtt"
            caption.write_text("WEBVTT\n\n" + "\n\n".join(f"{i}\n{vtt_time(c['start'])} --> {vtt_time(c['end'])}\n{html.escape(' '.join(c['text'].split()))}" for i, c in enumerate(cues, 1)) + "\n", encoding="utf-8")
            for path, kind, mime in [(clip, "clip", "video/mp4"), (caption, "caption", "text/vtt")]:
                checksum = file_hash(path)
                key = f"{prefix}/{checksum}{path.suffix}"
                context.check()
                objects.put(key, path, mime)
                context.check()
                assets.append({"position": index - 1, "kind": kind, "object_key": key, "checksum": checksum,
                               "duration": duration, "mime": mime, "transcript": scene.narration if kind == "clip" else ""})
        return assets
    finally:
        speech.close()
        if not local:
            speech.client.close()
