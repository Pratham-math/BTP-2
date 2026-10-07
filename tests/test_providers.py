"""Provider protocol checks use HTTP fixtures, never live text or fake speech claims."""

import json
import wave
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from server.config import GenerationSettings, JobSettings, ollama_url, snapshot_settings
from server.providers import ollama_recovery
from server.providers.base import GenerationError, inspect_audio
from server.providers.gemini_text import GeminiTextProvider
from server.providers.ollama_text import OllamaConnection, OllamaTextProvider


@pytest.fixture(autouse=True)
def isolated_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(ollama_recovery, "RECOVERY_FILE", tmp_path / "inflight.json")
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:11434")


def scene_data(kind):
    if kind == "plot":
        visual = {"kind": kind, "caption": "Illustrative data", "x_label": "Hours", "y_label": "Score",
                  "points": [{"x": 1, "y": 2}, {"x": 2, "y": 4}], "fit_line": True}
    else:
        edges = [{"source": "a", "target": "b"}]
        if kind == "cycle":
            edges.append({"source": "b", "target": "a"})
        visual = {"kind": kind, "caption": "One concept leads to another",
                  "nodes": [{"id": "a", "label": "First"}, {"id": "b", "label": "Second"}], "edges": edges}
    return {"title": "An example scene", "bullets": ["A clear relationship"],
            "narration": "This example teaches how a simple relationship can be represented visually. "
                         "Start with the first part and follow its connection to the next part. "
                         "Looking at the complete diagram helps you connect the explanation with a concrete example and remember the underlying idea.",
            "visual": visual}


def outline(kind):
    return {"title": "A local lesson", "teaching_goal": "Understand the relationship", "supported": True, "limitation": "",
            "scenes": [{"concept_id": f"concept-{i}", "title": f"Scene number {i}",
                        "learning_goal": "Understand this concept", "visual_kind": kind} for i in range(1, 4)]}


def answer(data, reason="stop"):
    return httpx.Response(200, json={"done": True, "done_reason": reason,
                                   "message": {"content": json.dumps(data), "thinking": "Never parse this field"}})


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_gemini_repairs_once_and_keeps_validation_inputs_private(tmp_path, repair_succeeds):
    from types import SimpleNamespace
    calls = []
    private_candidate = "private-invalid-candidate-text"
    valid = {"title": "A cloud lesson", "scenes": [scene_data("process") for _ in range(3)]}
    invalid = {**valid, "scenes": [{**scene_data("process"), "narration": private_candidate} for _ in range(3)]}

    def generate(**request):
        calls.append(request)
        return SimpleNamespace(text=json.dumps(valid if repair_succeeds and len(calls) == 2 else invalid))

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate), close=lambda: None)
    provider = GeminiTextProvider(client, "fixture-cloud-model")
    if repair_succeeds:
        result = provider.generate_script("Explain a process", tmp_path, lambda *_: None)
        assert len(result.scenes) == 3
    else:
        with pytest.raises(GenerationError) as error:
            provider.generate_script("Explain a process", tmp_path, lambda *_: None)
        assert error.value.code == "INVALID_SCRIPT"
        assert private_candidate not in str(error.value)
    assert len(calls) == 2
    assert "previous candidate failed" in calls[1]["contents"]
    assert private_candidate not in calls[1]["contents"]


@pytest.mark.parametrize("kind", ["process", "cycle", "tree", "plot"])
def test_local_script_uses_outline_and_strict_scene_contract(kind, tmp_path):
    calls = []
    def respond(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert request.url.host == "127.0.0.1"
        assert payload["stream"] is False
        assert payload["think"] is False
        if len(calls) > 1:
            visual = payload["format"]["$defs"]["VisualSpec"]["properties"]
            assert visual["kind"]["const"] == kind
            if kind == "plot":
                assert visual["nodes"]["maxItems"] == visual["edges"]["maxItems"] == 0
            else:
                assert visual["nodes"]["maxItems"] == (7 if kind == "tree" else 6)
        return answer(outline(kind) if len(calls) == 1 else scene_data(kind))
    connection = OllamaConnection(transport=httpx.MockTransport(respond))
    provider = OllamaTextProvider("qwen3:4b-q4_K_M", {"digest": "fixture", "capabilities": ["completion", "thinking"]}, connection)
    try:
        script = provider.generate_script("Explain an example", tmp_path, lambda *_: None)
        assert len(script.scenes) == 3
        assert all(scene.visual.kind == kind for scene in script.scenes)
        assert len(calls) == 4
        # A retry can reuse each validated unit without another inference request.
        provider.generate_script("Explain an example", tmp_path, lambda *_: None)
        assert len(calls) == 4
    finally:
        provider.close()


def test_one_repair_and_resume_keep_accepted_local_units(tmp_path):
    calls = []
    fail_last = True
    def respond(request):
        nonlocal fail_last
        payload = json.loads(request.content)
        calls.append(payload)
        if len(calls) == 1:
            return answer(outline("process"))
        if fail_last and len(calls) >= 4:
            invalid = scene_data("process")
            invalid["visual"]["edges"] = []
            return answer(invalid)
        return answer(scene_data("process"))
    provider = OllamaTextProvider("fixture", {"digest": "fixture"}, OllamaConnection(transport=httpx.MockTransport(respond)))
    try:
        with pytest.raises(GenerationError) as error:
            provider.generate_script("Explain this", tmp_path, lambda *_: None)
        assert error.value.code == "INVALID_SCRIPT"
        assert len(calls) == 5  # outline + 2 accepted scenes + 2 attempts for scene 3
        assert (tmp_path / "accepted-scene-2.json").exists()
        assert not (tmp_path / "accepted-scene-3.json").exists()
        failed_candidate = json.loads((tmp_path / "candidate-scene-3-attempt-2.json").read_text(encoding="utf-8"))
        assert failed_candidate["accepted"] is False and failed_candidate["errors"]
        assert all("input" not in error for error in failed_candidate["errors"])
        fail_last = False
        provider.generate_script("Explain this", tmp_path, lambda *_: None)
        assert len(calls) == 6
    finally:
        provider.close()


def test_truncation_and_timeout_never_switch_to_a_cloud_provider(tmp_path):
    def truncated(_):
        return answer(outline("process"), "length")
    provider = OllamaTextProvider("fixture", {}, OllamaConnection(transport=httpx.MockTransport(truncated)))
    with pytest.raises(GenerationError, match="stopped before"):
        provider.generate_script("Explain this", tmp_path, lambda *_: None)
    provider.close()
    assert not ollama_recovery.recovery_required()  # complete response; content was truncated

    def timed_out(request):
        raise httpx.ReadTimeout("fixture timeout", request=request)
    connection = OllamaConnection(transport=httpx.MockTransport(timed_out))
    with pytest.raises(GenerationError) as error:
        connection.request("POST", "/api/chat", {})
    assert error.value.code == "PROVIDER_TIMEOUT"
    assert ollama_recovery.recovery_required()
    with pytest.raises(GenerationError, match="may still be running"):
        ollama_recovery.assert_available()
    connection.close()


def test_unsupported_local_outline_stops_before_inventing_scenes(tmp_path):
    calls = []
    def respond(request):
        calls.append(request)
        return answer({"title": "Missing source material", "teaching_goal": "Explain the supplied source",
                       "supported": False, "limitation": "The previous presentation was not supplied", "scenes": []})
    provider = OllamaTextProvider("fixture", {}, OllamaConnection(transport=httpx.MockTransport(respond)))
    try:
        with pytest.raises(GenerationError) as error:
            provider.generate_script("Explain yesterday's presentation", tmp_path, lambda *_: None)
        assert error.value.code == "UNSUPPORTED_REQUEST"
        assert len(calls) == 1
        assert not (tmp_path / "accepted-scene-1.json").exists()
    finally:
        provider.close()


def test_backend_rejects_remote_ollama_urls_and_mixed_presets(monkeypatch):
    for url in ("https://example.com", "http://127.0.0.1:11434/path", "http://user@localhost:11434", "http://localhost:11434?key=secret"):
        monkeypatch.setenv("OLLAMA_URL", url)
        with pytest.raises(ValueError):
            ollama_url()
    config = snapshot_settings(GenerationSettings(mode="local"))
    data = config.model_dump()
    data["speech_provider"] = "gemini"
    with pytest.raises(ValidationError):
        JobSettings.model_validate(data)


def test_ollama_memory_failure_is_safe_and_actionable():
    connection = OllamaConnection(transport=httpx.MockTransport(lambda _: httpx.Response(
        500, json={"error": "out of memory while processing PRIVATE FIXTURE TEXT"})))
    with pytest.raises(GenerationError) as error:
        connection.request("POST", "/api/chat", {})
    assert error.value.code == "OUT_OF_MEMORY"
    assert "PRIVATE FIXTURE TEXT" not in str(error.value)
    assert not ollama_recovery.recovery_required()
    connection.close()


@pytest.mark.parametrize("case", ["empty", "truncated", "silent"])
def test_speech_artifact_needs_a_complete_positive_wav(tmp_path, case):
    path = tmp_path / "audio.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(24000)
        stream.writeframes(b"\x00\x00" * (100 if case != "empty" else 0))
    if case == "truncated":
        path.write_bytes(path.read_bytes()[:-20])
    with pytest.raises(GenerationError) as error:
        inspect_audio(path)
    assert error.value.code == "TTS_FAILED"
