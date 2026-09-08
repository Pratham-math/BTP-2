import math
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts.check_media import inspect as inspect_media
from server import main
from server.generator import Scene, combine_videos, draw_slide, make_scene_video, verify_video
from server.main import app


client = TestClient(app)


def test_blank_and_too_long_prompts_are_rejected():
    assert client.post("/api/videos", json={"prompt": "   "}).status_code == 422
    assert client.post("/api/videos", json={"prompt": "x" * 2001}).status_code == 422


def test_missing_key_has_a_clear_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    response = client.post("/api/videos", json={"prompt": "Explain photosynthesis"})
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]


def test_unknown_video_is_not_found():
    assert client.get("/api/videos/" + "a" * 32).status_code == 404


def test_generation_lock_is_released_after_an_unexpected_failure(monkeypatch):
    def fail(*_):
        raise RuntimeError("provider failed")

    monkeypatch.setattr(main, "run_generation", fail)
    assert main.generation_lock.acquire(blocking=False)
    with pytest.raises(RuntimeError, match="provider failed"):
        main.run_and_unlock()
    assert not main.generation_lock.locked()


def test_offline_render_and_concat_have_audio_and_video(tmp_path: Path):
    clips = []
    scene = Scene(
        title="A tiny rendering test",
        bullets=["The picture is rendered with Pillow", "FFmpeg adds fixture audio"],
        narration="This synthetic offline fixture checks how our local rendering pipeline combines a slide with an audio track. It deliberately uses a simple generated tone, so it is not a substitute for real Gemini narration or for listening to a live end to end result before a demonstration.",
    )
    for number in (1, 2):
        image_path = tmp_path / f"scene-{number}.png"
        audio_path = tmp_path / f"scene-{number}.wav"
        video_path = tmp_path / f"scene-{number}.mp4"
        draw_slide(scene, image_path, number, 2)
        write_test_tone(audio_path)
        make_scene_video(image_path, audio_path, video_path)
        clips.append(video_path)

    final_path = tmp_path / "video.mp4"
    combine_videos(clips, final_path)
    details = verify_video(final_path)
    inspect_media(final_path)
    assert float(details["format"]["duration"]) > 1.5


def write_test_tone(path: Path, seconds: float = 0.8) -> None:
    rate = 24_000
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        frames = bytearray()
        for index in range(int(rate * seconds)):
            sample = int(1800 * math.sin(2 * math.pi * 330 * index / rate))
            frames.extend(sample.to_bytes(2, "little", signed=True))
        output.writeframes(frames)
