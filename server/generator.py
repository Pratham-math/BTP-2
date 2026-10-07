"""One provider-neutral coordinator with verified artifact checkpoints."""

import errno
import json
import re
import time
from pydantic import ValidationError

from server.artifacts import ArtifactStore, file_hash
from server.config import JobSettings, saved_settings
from server.media import (combine_videos, draw_slide, make_animated_scene, make_scene_video,
                          mux_animation, render_animation, verify_video, wav_duration)
from server.preflight import check_settings, require_ready
from server.providers.base import GenerationError, inspect_audio
from server.providers.gemini_text import create_client, gemini_response_schema, generate_script
from server.providers.gemini_tts import call_tts_with_retry, decode_audio_bytes, generate_audio
from server.providers.registry import create_providers
from server.runtime import CURRENT_CONTROL, JobControl, checkpoint, run_command
from server.script import AnimatedScene, AnimatedVideoScript, Scene, VideoScript
from server.storage import Storage, atomic_json, now_iso


TIMING_POLICY = {"version": "narration-v1", "lead_in": .15, "tail": .35}
PRONUNCIATION_VERSION = "en-v1"
PRONUNCIATIONS = {"CPU": "C P U", "GPU": "G P U", "API": "A P I"}


def spoken_text(narration: str) -> str:
    return re.sub(r"\b(?:CPU|GPU|API)\b", lambda match: PRONUNCIATIONS[match.group()], narration)


def run_generation(storage: Storage, job_id: str, prompt: str, api_key: str | None = None,
                   text_model=None, tts_model=None, voice=None, *, settings: JobSettings | None = None,
                   control: JobControl | None = None) -> None:
    folder = storage.job_dir(job_id)
    config = settings or saved_settings({"text_model": text_model or "", "tts_model": tts_model or "", "voice": voice or ""})
    control = control or JobControl(folder)
    token = CURRENT_CONTROL.set(control)
    cache = ArtifactStore(folder)
    text_provider = speech_provider = None
    failed = None
    stage_timings, active_stage, stage_started = {}, "preflight", time.monotonic()
    legacy = "schema_version" not in storage.read_status(job_id).get("settings", {})

    def progress(message, current=0, stage="scripting"):
        nonlocal stage_started, active_stage
        checkpoint()
        if stage != active_stage:
            stage_timings[active_stage] = stage_timings.get(active_stage, 0) + time.monotonic() - stage_started
            stage_started, active_stage = time.monotonic(), stage
        storage.update_status(job_id, stage=message, stage_code=stage, current=current)

    try:
        checkpoint()
        storage.update_status(job_id, state="running", stage="Checking generation setup", stage_code="preflight",
                              current=0, error=None, error_code=None, action=None, started_at=now_iso(), finished_at=None)
        checkpoint()
        previous_text, previous_speech = config.text_identity.copy(), config.speech_identity.copy()
        result = check_settings(config, storage.data_dir, probe=True)
        require_ready(result)
        if config.mode == "local" and ((previous_text and previous_text != config.text_identity)
                                        or (previous_speech and previous_speech != config.speech_identity)):
            raise GenerationError("DEPENDENCY_CHANGED", "The saved model or voice has changed since this job was accepted.",
                                  "Start a new video to use the changed model or voice.")
        storage.update_status(job_id, settings=config.model_dump())
        atomic_json(folder / "preflight.json", result)
        text_provider, speech_provider = create_providers(config, api_key)
        # A resumed job uses the installed prompt template. Its real version
        # must drive script reuse and saved provenance as well as unit caches.
        config.prompt_template_version = getattr(text_provider, "prompt_template_version", config.prompt_template_version)
        storage.update_status(job_id, settings=config.model_dump())
        script_inputs = {"prompt": prompt, "provider": text_provider.identity,
                         "schema": 2, "template": config.prompt_template_version}
        script_path = folder / "script.json"
        progress("Planning the lesson and visuals")
        if cache.reusable("script", script_inputs, script_path):
            script = VideoScript.model_validate_json(script_path.read_text(encoding="utf-8"))
        elif legacy and script_path.exists() and not cache.manifest.exists():
            script = VideoScript.model_validate_json(script_path.read_text(encoding="utf-8"))
            cache.record("script", script_inputs, script_path, {"legacy_import": True})
        else:
            script = text_provider.generate_script(prompt, folder, lambda message, index: progress(message, index))
            checkpoint()
            atomic_json(script_path, script.model_dump())
            cache.record("script", script_inputs, script_path)
        storage.update_status(job_id, title=script.title)
        cache.publish(ready=False, settings=config.model_dump(), script_checksum=file_hash(script_path), language="en",
                      provenance={"mode": config.mode, "text_provider": text_provider.identity,
                                  "speech_provider": speech_provider.identity})

        audio_paths, timing = [], []
        for index, scene in enumerate(script.scenes, 1):
            progress(f"Creating narration {index} of 3", index, "narrating")
            path, text = folder / f"scene-{index}.wav", spoken_text(scene.narration)
            audio_inputs = {"spoken_text": text, "provider": speech_provider.identity,
                            "rate": config.speech_rate, "pronunciation": PRONUNCIATION_VERSION}
            reusable = cache.reusable(f"audio-{index}", audio_inputs, path)
            if reusable:
                try:
                    artifact = inspect_audio(path, speech_provider.identity)
                except GenerationError:
                    reusable = None
            if not reusable:
                artifact = speech_provider.synthesize(text, path)
                checkpoint()
                cache.record(f"audio-{index}", audio_inputs, path, artifact.metadata())
            audio_paths.append(path)
            timing.append({"scene_id": f"scene-{index}", "audio_checksum": file_hash(path),
                           "voice_identity": speech_provider.identity,
                           "audio_duration": artifact.duration,
                           "duration": artifact.duration + TIMING_POLICY["lead_in"] + TIMING_POLICY["tail"],
                           "spoken_text": text, **TIMING_POLICY})
        speech_provider.close()
        speech_provider = None
        text_provider.close()
        text_provider = None
        progress("Measuring narration and planning animation time", 3, "timing")
        atomic_json(folder / "timing.json", {"schema_version": 2, "scenes": timing})

        scene_videos = []
        for index, (scene, audio_path, timeline) in enumerate(zip(script.scenes, audio_paths, timing), 1):
            progress(f"Rendering scene {index} of 3", index, "rendering")
            video_path = folder / f"scene-{index}.mp4"
            render_inputs = {"title": scene.title, "visual": scene.visual.model_dump() if scene.visual else None,
                             "bullets": scene.bullets if not scene.visual else [], "duration": timeline["duration"],
                             "timing_policy": TIMING_POLICY, "profile": config.render_profile,
                             "audio": timeline["audio_checksum"], "voice": timeline["voice_identity"],
                             "template": "manim-v2", "scene_number": index, "font": "Arial"}
            if scene.visual:
                silent_path = folder / f"scene-{index}.silent.mp4"
                if not cache.reusable(f"animation-{index}", render_inputs, silent_path):
                    render_animation(scene, timeline["duration"], silent_path, index, 3, config.render_profile)
                    checkpoint()
                    cache.record(f"animation-{index}", render_inputs, silent_path,
                                 verify_video(silent_path, require_audio=False, expected_duration=timeline["duration"]))
                clip_inputs = {"animation": file_hash(silent_path), "audio": file_hash(audio_path),
                               "mux": "h264-aac-v2", "profile": config.render_profile, "timing": TIMING_POLICY}
            else:
                image_path = folder / f"scene-{index}.png"
                if not cache.reusable(f"slide-{index}", render_inputs, image_path):
                    draw_slide(scene, image_path, index, 3)
                    cache.record(f"slide-{index}", render_inputs, image_path)
                clip_inputs = {"image": file_hash(image_path), "audio": file_hash(audio_path),
                               "profile": config.render_profile, "timing": TIMING_POLICY, "mux": "h264-aac-v2"}
            if not cache.reusable(f"clip-{index}", clip_inputs, video_path):
                progress(f"Adding narration to scene {index} of 3", index, "muxing")
                if scene.visual:
                    mux_animation(silent_path, audio_path, video_path, config.render_profile,
                                  TIMING_POLICY["lead_in"], TIMING_POLICY["tail"])
                else:
                    make_scene_video(image_path, audio_path, video_path, config.render_profile,
                                     TIMING_POLICY["lead_in"], TIMING_POLICY["tail"])
                checkpoint()
                cache.record(f"clip-{index}", clip_inputs, video_path,
                             verify_video(video_path, expected_duration=timeline["duration"]))
            scene_videos.append(video_path)

        progress("Assembling the final video", 3, "assembling")
        final_path = folder / "video.mp4"
        final_inputs = {"clips": [file_hash(path) for path in scene_videos], "assembly": "concat-v2"}
        if not cache.reusable("video", final_inputs, final_path):
            combine_videos(scene_videos, final_path)
        progress("Verifying picture, narration and duration", 3, "verifying")
        details = verify_video(final_path, expected_duration=sum(t["duration"] for t in timing), decode=True)
        with control.state_lock:
            checkpoint()
            cache.record("video", final_inputs, final_path, details)
            stage_timings[active_stage] = time.monotonic() - stage_started
            cache.publish(ready=True, ordered_clips=[path.name for path in scene_videos],
                          stage_seconds={key: round(value, 2) for key, value in stage_timings.items()}, completed_at=now_iso())
            storage.update_status(job_id, state="ready", stage="Ready", stage_code="ready", current=3,
                                  error=None, error_code=None, action=None, finished_at=now_iso())
    except Exception as error:
        failed = safe_error(error, active_stage)
    finally:
        for provider in (speech_provider, text_provider):
            if provider:
                try:
                    provider.close()
                except Exception:
                    pass
        CURRENT_CONTROL.reset(token)
        if failed:
            storage.update_status(job_id, state="cancelled" if failed.code == "CANCELLED" else "failed",
                                  error=str(failed), error_code=failed.code, action=failed.action, finished_at=now_iso())


def safe_error(error: Exception, stage: str = "generation") -> GenerationError:
    if isinstance(error, GenerationError):
        return error
    message = str(error).lower()
    if isinstance(error, MemoryError) or "out of memory" in message:
        return GenerationError("OUT_OF_MEMORY", "This backend ran out of memory.", "Choose a smaller model or preview quality.")
    if isinstance(error, OSError) and error.errno == errno.ENOSPC:
        return GenerationError("DISK_FULL", "The storage drive is full.", "Free space and resume the job.")
    if isinstance(error, ValidationError):
        return GenerationError("INVALID_SCRIPT", "The generated lesson did not satisfy the scene and visual limits.", "Retry or simplify the prompt.")
    if "api key" in message or "api_key" in message or "unauth" in message:
        return GenerationError("KEY_REJECTED", "Gemini rejected the API key. Replace it in Settings.")
    if "quota" in message or "resource_exhausted" in message or "429" in message:
        return GenerationError("QUOTA_REACHED", "Gemini quota was reached. Wait or use a project with available quota, then retry.")
    if "not found" in message and "model" in message:
        return GenerationError("MODEL_UNAVAILABLE", "A configured Gemini model is unavailable. Check the model names in .env.")
    code = "RENDER_FAILED" if stage in {"rendering", "muxing", "assembling", "verifying"} else "GENERATION_FAILED"
    return GenerationError(code, f"The {stage} stage stopped unexpectedly. Completed artifacts are saved.", "Check setup and retry this job.")


def readable_error(error: Exception) -> str:
    return str(safe_error(error))
