"""Offline rendering checks. Fixture tones are not live Gemini narration."""

import json
import math
import shutil
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageChops
from pydantic import ValidationError

from scripts.check_media import inspect as inspect_media
from server import generator
from server.storage import Storage
from server.providers.base import inspect_audio
from server.visuals import VisualSpec


NARRATION = (
    "This is an offline rendering fixture for the animated lesson pipeline. "
    "The audio is a synthetic test tone, not a real voice or Gemini narration. "
    "We use it to check animation frames, timing, audio tracks, and the final downloadable video."
)


def example_visual(kind):
    if kind == "plot":
        return {"kind": kind, "caption": "Illustrative data: a fitted line summarizes the trend.",
                "x_label": "Study hours", "y_label": "Practice score", "fit_line": True,
                "points": [{"x": x, "y": y} for x, y in [(1, 2), (2, 4), (3, 3), (4, 6)]]}
    if kind == "tree":
        return {"kind": kind, "caption": "A root branches into child nodes.",
                "nodes": [{"id": str(i), "label": str(i), "color": "red" if i % 2 else "ink"} for i in range(7)],
                "edges": [{"source": str((i - 1) // 2), "target": str(i)} for i in range(1, 7)]}
    icons = ["sun", "cloud", "water"] if kind == "cycle" else ["sun", "plant", "none"]
    names = ["Evaporation", "Condensation", "Precipitation"] if kind == "cycle" else ["Sunlight", "Plant leaves", "Stored energy"]
    edges = [{"source": "0", "target": "1"}, {"source": "1", "target": "2"}]
    if kind == "cycle":
        edges.append({"source": "2", "target": "0"})
    return {"kind": kind, "caption": "Follow the arrows through the process.",
            "nodes": [{"id": str(i), "label": name, "icon": icons[i]} for i, name in enumerate(names)], "edges": edges}


def write_tone(path, seconds=4):
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"".join(
            int(1800 * math.sin(2 * math.pi * 330 * i / 24000)).to_bytes(2, "little", signed=True)
            for i in range(int(24000 * seconds))
        ))


@pytest.fixture(scope="module")
def rendered_examples(tmp_path_factory):
    folder = tmp_path_factory.mktemp("manim-media")
    audio = folder / "synthetic.wav"
    write_tone(audio)
    clips = {}
    for kind in ("process", "cycle", "tree", "plot"):
        scene = generator.Scene(title=f"Animated {kind} example", bullets=["Offline fixture"],
                                narration=NARRATION, visual=example_visual(kind))
        clip = folder / f"{kind}.mp4"
        generator.make_animated_scene(scene, audio, clip, 1, 3)
        clips[kind] = clip
    return clips


def frame(path, seconds):
    result = subprocess.run([
        "ffmpeg", "-v", "error", "-ss", str(seconds), "-i", str(path),
        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ], check=True, capture_output=True, timeout=30)
    return Image.frombytes("RGB", (1280, 720), result.stdout)


@pytest.mark.parametrize("kind", ["process", "cycle", "tree", "plot"])
def test_templates_render_moving_video_with_audio(kind, rendered_examples):
    clip = rendered_examples[kind]
    inspect_media(clip)
    details = generator.verify_video(clip)
    assert float(details["format"]["duration"]) == pytest.approx(4.25, abs=.12)
    # Compare only the diagram region, excluding the static title and caption.
    early = frame(clip, .2).crop((60, 140, 1220, 590))
    late = frame(clip, 3.6).crop((60, 140, 1220, 590))
    assert ImageChops.difference(early, late).getbbox() is not None


def test_animated_clips_join_into_one_playable_mp4(rendered_examples, tmp_path):
    clips = []
    for index, kind in enumerate(("process", "tree", "plot"), 1):
        copy = tmp_path / f"scene-{index}.mp4"
        shutil.copyfile(rendered_examples[kind], copy)
        clips.append(copy)
    final = tmp_path / "video.mp4"
    generator.combine_videos(clips, final)
    inspect_media(final)
    assert float(generator.verify_video(final)["format"]["duration"]) == pytest.approx(12.75, abs=.2)


@pytest.mark.parametrize("case", ["unknown-edge", "duplicate-id", "disconnected-tree", "code", "infinite-point", "vertical-fit"])
def test_bad_visual_plans_are_rejected(case):
    data = example_visual("process")
    if case == "unknown-edge":
        data["edges"][0]["target"] = "missing"
    elif case == "duplicate-id":
        data["nodes"][1]["id"] = "0"
    elif case == "disconnected-tree":
        data = example_visual("tree")
        data["edges"] = [{"source": "0", "target": "1"}, {"source": "2", "target": "3"},
                         {"source": "3", "target": "2"}, {"source": "0", "target": "4"},
                         {"source": "4", "target": "5"}, {"source": "4", "target": "6"}]
    elif case == "code":
        data["python"] = "print('This must never execute')"
    elif case == "infinite-point":
        data = example_visual("plot")
        data["points"][0]["x"] = float("inf")
    else:
        data = example_visual("plot")
        for point in data["points"]:
            point["x"] = 2
    with pytest.raises(ValidationError):
        VisualSpec.model_validate(data)


def test_new_scripts_require_visuals_but_legacy_scripts_still_load():
    data = {"title": "Old lesson", "scenes": [{"title": "Old scene", "bullets": ["Text"], "narration": NARRATION}] * 3}
    assert generator.VideoScript.model_validate(data).scenes[0].visual is None
    fake_client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **_: SimpleNamespace(text=json.dumps(data))))
    with pytest.raises(ValidationError):
        generator.generate_script(fake_client, "Explain trees", "fake-model")


def test_retry_reuses_narration_and_completed_animations(rendered_examples, tmp_path, monkeypatch):
    storage = Storage(tmp_path)
    job_id = "b" * 32
    storage.create_job(job_id, "Explain sunlight", {})
    scene = generator.Scene(title="Sunlight to energy", bullets=["A simple process"],
                            narration=NARRATION, visual=example_visual("process"))
    script = generator.VideoScript(title="A visual lesson", scenes=[scene] * 3)
    calls = {"script": 0, "audio": 0, "animation": 0}

    def script_result(*_):
        calls["script"] += 1
        return script

    def audio_result(_client, _narration, path, *_):
        calls["audio"] += 1
        write_tone(path)

    def animation_result(_scene, _duration, output, index, _total, _profile):
        calls["animation"] += 1
        if calls["animation"] == 2:
            raise RuntimeError("Temporary rendering failure")
        shutil.copyfile(rendered_examples["process"], output)

    text = SimpleNamespace(identity={"provider": "fixture-text"}, generate_script=script_result, close=lambda: None)
    def speech_result(narration, path):
        audio_result(None, narration, path)
        return inspect_audio(path)
    speech = SimpleNamespace(identity={"provider": "fixture-tone"}, synthesize=speech_result, close=lambda: None)
    monkeypatch.setattr(generator, "create_providers", lambda *_: (text, speech))
    monkeypatch.setattr(generator, "check_settings", lambda config, *_args, **_kwargs: {"ready": True, "checks": [], "settings": config.model_dump()})
    monkeypatch.setattr(generator, "render_animation", animation_result)
    args = (storage, job_id, "Explain sunlight", "offline-key", "fake", "fake", "fake")
    generator.run_generation(*args)
    assert storage.read_status(job_id)["state"] == "failed"
    generator.run_generation(*args)
    assert storage.read_status(job_id)["state"] == "ready"
    assert calls == {"script": 1, "audio": 3, "animation": 4}
    inspect_media(storage.job_dir(job_id) / "video.mp4")
