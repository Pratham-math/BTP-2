"""Admission, recovery and local control-surface checks without inference."""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from server import main
from server.artifacts import ArtifactStore
from server.runtime import RuntimeLease
from server.storage import Storage


@pytest.fixture
def backend(tmp_path, monkeypatch):
    storage = Storage(tmp_path / "data")
    monkeypatch.setattr(main, "storage", storage)
    monkeypatch.setattr(main, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(main, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture-key")
    monkeypatch.setattr(main, "check_settings", lambda config, *_args, **_kwargs: {"ready": True, "checks": [], "settings": config.model_dump()})
    with TestClient(main.app, client=("127.0.0.1", 50001), headers={"X-App-Token": main.CONTROL_TOKEN}) as client:
        yield client, storage
    assert not main.generation_lock.locked()


def test_duplicate_request_busy_status_and_cancellation_keep_one_slot(backend, monkeypatch):
    client, storage = backend
    started, finish = threading.Event(), threading.Event()
    calls = []
    def wait(_storage, job_id, *_args, control, **_kwargs):
        calls.append(job_id)
        storage.update_status(job_id, state="running", stage="Fixture is waiting")
        started.set()
        finish.wait(timeout=5)
        storage.update_status(job_id, state="cancelled" if control.cancel_requested.is_set() else "failed")
    monkeypatch.setattr(main, "run_generation", wait)
    payload = {"prompt": "Explain photosynthesis", "request_id": "fixture-request-01"}
    try:
        first = client.post("/api/videos", json=payload)
        assert first.status_code == 202
        assert started.wait(timeout=2)
        job_id = first.json()["id"]
        assert client.post("/api/videos", json=payload).json()["id"] == job_id
        assert client.post("/api/videos", json={**payload, "prompt": "Different input"}).status_code == 409
        assert client.post("/api/videos", json={"prompt": "Another independent request"}).status_code == 409
        assert client.get("/api/health").status_code == 200
        assert client.post(f"/api/videos/{job_id}/cancel").json()["state"] == "cancelling"
        assert client.get(f"/api/videos/{job_id}").json()["state"] == "cancelling"
        assert client.post("/api/videos", json={"prompt": "Another independent request"}).status_code == 409
        assert calls == [job_id]
    finally:
        finish.set()


def test_remote_settings_and_unexpected_origins_are_denied(backend):
    client, _ = backend
    assert client.put("/api/settings/api-key", json={"api_key": "private-secret-fixture"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/videos", json={"prompt": "Explain this"}, headers={"X-App-Token": ""}).status_code == 403
    remote = TestClient(main.app, client=("192.0.2.10", 50002), headers={"X-App-Token": main.CONTROL_TOKEN, "X-Forwarded-For": "127.0.0.1"})
    response = remote.put("/api/settings/api-key", json={"api_key": "private-secret-fixture"})
    assert response.status_code == 403
    assert "private-secret-fixture" not in response.text
    assert remote.get("/api/runtime").json()["owner_settings"] is False
    assert client.post("/api/videos", json={"prompt": "Explain this", "settings": {"mode": "local", "text_provider": "gemini"}}).status_code == 422


def test_damaged_ready_output_becomes_resumable_before_delivery(backend):
    client, storage = backend
    job_id = "d" * 32
    storage.create_job(job_id, "Public fixture request", {})
    folder = storage.job_dir(job_id)
    video = folder / "video.mp4"
    video.write_bytes(b"checksum-only delivery fixture; not a media acceptance test")
    ArtifactStore(folder).record("video", {"assembly": "fixture"}, video)
    storage.update_status(job_id, state="ready")
    video.write_bytes(b"damaged saved output")
    response = client.get(f"/api/videos/{job_id}/file")
    assert response.status_code == 409
    status = client.get(f"/api/videos/{job_id}").json()
    assert status["state"] == "failed" and status["error_code"] == "INVALID_ARTIFACT"
    assert "Resume" in status["action"]


def test_restart_marks_incomplete_jobs_and_data_directory_has_one_owner(tmp_path):
    storage = Storage(tmp_path)
    job_id = "a" * 32
    storage.create_job(job_id, "Example prompt", {})
    storage.update_status(job_id, state="cancelling")
    storage.mark_interrupted_jobs()
    assert storage.read_status(job_id)["state"] == "interrupted"
    owner, other = RuntimeLease(tmp_path), RuntimeLease(tmp_path)
    owner.acquire()
    try:
        with pytest.raises(RuntimeError, match="Another backend"):
            other.acquire()
    finally:
        owner.release()
    other.acquire()
    other.release()


def test_reuse_needs_matching_input_and_checksum_and_preserves_corruption(tmp_path):
    output = tmp_path / "scene-1.wav"
    output.write_bytes(b"fixture bytes")
    cache = ArtifactStore(tmp_path)
    inputs = {"voice": "one", "narration": "text"}
    cache.record("audio-1", inputs, output)
    assert cache.reusable("audio-1", inputs, output)
    assert not cache.reusable("audio-1", {**inputs, "voice": "two"}, output)
    output.write_bytes(b"interrupted output")
    assert not cache.reusable("audio-1", inputs, output)
    cache.manifest.write_text("damaged", encoding="utf-8")
    with pytest.raises(RuntimeError, match="damaged"):
        cache.reusable("audio-1", inputs, output)
    assert cache.manifest.read_text(encoding="utf-8") == "damaged"


@pytest.mark.parametrize("damaged", [[], {"schema_version": 2, "artifacts": {"audio-1": []}},
                                    {"schema_version": 2, "artifacts": {"audio-1": {"path": "scene-1.wav", "checksum": "invalid"}}}])
def test_malformed_manifest_shape_is_reported_without_replacing_saved_data(tmp_path, damaged):
    import json
    from server.providers.base import GenerationError
    cache = ArtifactStore(tmp_path)
    original = json.dumps(damaged)
    cache.manifest.write_text(original, encoding="utf-8")
    with pytest.raises(GenerationError) as error:
        cache.reusable("audio-1", {}, tmp_path / "scene-1.wav")
    assert error.value.code == "STORAGE_CORRUPT"
    assert cache.manifest.read_text(encoding="utf-8") == original
