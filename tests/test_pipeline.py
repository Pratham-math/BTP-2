"""Fault-injection checks for artifact dependencies; speech is synthetic."""

import wave
from types import SimpleNamespace

from server import generator
from server.config import GenerationSettings, snapshot_settings
from server.providers.base import inspect_audio
from server.storage import Storage


def test_retry_and_changed_voice_or_quality_reuse_only_matching_stages(tmp_path, monkeypatch):
    storage, job_id = Storage(tmp_path), "c" * 32
    config = snapshot_settings(GenerationSettings())
    storage.create_job(job_id, "Explain a process", config.model_dump())
    calls = {"script": 0, "speech": 0, "render": 0, "mux": 0, "assemble": 0}
    fail = {"render": True}
    scene = generator.Scene(title="A simple process", bullets=["One stage follows another"],
        narration="This is an offline synthetic fixture used to verify which saved artifacts a retry may reuse. "
                  "The test does not contact a language model and does not create real spoken narration. "
                  "It checks that settings changes rebuild affected stages without discarding unrelated completed work.",
        visual={"kind": "process", "caption": "Follow the process", "nodes": [{"id": "a", "label": "First"}, {"id": "b", "label": "Second"}],
                "edges": [{"source": "a", "target": "b"}]})
    script = generator.VideoScript(title="A fixture lesson", scenes=[scene] * 3)

    def providers(settings, _key):
        def text(*_):
            calls["script"] += 1
            return script
        identity = {"voice": settings.voice, "engine": "synthetic-fixture"}
        def speech(_text, path):
            calls["speech"] += 1
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1); output.setsampwidth(2); output.setframerate(24000)
                output.writeframes(bytes([len(settings.voice), 0]) * 2400)
            return inspect_audio(path, identity)
        return (SimpleNamespace(identity={"model": settings.text_model}, generate_script=text, close=lambda: None),
                SimpleNamespace(identity=identity, synthesize=speech, close=lambda: None))

    def render(_scene, duration, output, index, _total, profile):
        calls["render"] += 1
        if fail["render"] and index == 2:
            fail["render"] = False
            raise RuntimeError("Injected render failure containing private source material")
        output.write_text(f"fixture video {duration} {profile} {index}", encoding="utf-8")
    def mux(silent, audio, output, *_):
        calls["mux"] += 1
        output.write_bytes(silent.read_bytes() + audio.read_bytes())
    def assemble(clips, output):
        calls["assemble"] += 1
        output.write_bytes(b"".join(path.read_bytes() for path in clips))

    monkeypatch.setattr(generator, "create_providers", providers)
    monkeypatch.setattr(generator, "check_settings", lambda settings, *_args, **_kwargs: {"ready": True, "checks": [], "settings": settings.model_dump()})
    monkeypatch.setattr(generator, "render_animation", render)
    monkeypatch.setattr(generator, "mux_animation", mux)
    monkeypatch.setattr(generator, "combine_videos", assemble)
    monkeypatch.setattr(generator, "verify_video", lambda _path, **kwargs: {"format": {"duration": kwargs.get("expected_duration", .6)}})
    run = lambda settings: generator.run_generation(storage, job_id, "Explain a process", "fixture-key", settings=settings)
    run(config)
    status = storage.read_status(job_id)
    assert status["state"] == "failed" and status["stage_code"] == "rendering"
    assert "private source material" not in status["error"]
    assert calls["speech"] == 3
    run(config)
    assert storage.read_status(job_id)["state"] == "ready"
    assert calls == {"script": 1, "speech": 3, "render": 4, "mux": 3, "assemble": 1}

    preview = config.model_copy(update={"render_profile": "480p24"})
    run(preview)
    assert calls["script"] == 1 and calls["speech"] == 3 and calls["render"] == 7
    changed_voice = preview.model_copy(update={"voice": "different-voice"})
    run(changed_voice)
    assert calls["script"] == 1 and calls["speech"] == 6 and calls["render"] == 10
    audio = storage.job_dir(job_id) / "scene-1.wav"
    audio.write_bytes(b"corrupted WAV")
    run(changed_voice)
    assert storage.read_status(job_id)["state"] == "ready"
    assert calls["speech"] == 7

    def updated_template(settings, key):
        text, speech = providers(settings, key)
        text.prompt_template_version = "updated-template-fixture"
        return text, speech
    before = calls.copy()
    monkeypatch.setattr(generator, "create_providers", updated_template)
    run(changed_voice)
    assert calls["script"] == before["script"] + 1
    assert calls["speech"] == before["speech"]  # Identical accepted text still matches the WAV inputs.
    assert calls["render"] == before["render"]
    assert storage.read_status(job_id)["settings"]["prompt_template_version"] == "updated-template-fixture"
