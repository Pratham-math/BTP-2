from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from server.providers.base import GenerationError
from server.providers.piper_runtime import load_voice, piper_device


def runtime(monkeypatch, *, available=True, actual=True, load_error=False):
    import sys
    ort = SimpleNamespace(
        get_available_providers=lambda: ["CUDAExecutionProvider"] if available else ["CPUExecutionProvider"],
        preload_dlls=Mock(),
    )
    session = SimpleNamespace(get_providers=lambda: ["CUDAExecutionProvider"] if actual else ["CPUExecutionProvider"], disable_fallback=Mock())
    loader = Mock(return_value=SimpleNamespace(session=session))
    if load_error:
        loader.side_effect = RuntimeError("Private local path must not escape")
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    monkeypatch.setitem(sys.modules, "piper", SimpleNamespace(PiperVoice=SimpleNamespace(load=loader)))
    return ort, loader, session


def test_device_selection_is_explicit(monkeypatch):
    monkeypatch.delenv("PIPER_DEVICE", raising=False)
    assert piper_device() == "cpu"
    monkeypatch.setenv("PIPER_DEVICE", "CUDA")
    assert piper_device() == "cuda"
    monkeypatch.setenv("PIPER_DEVICE", "auto")
    with pytest.raises(GenerationError, match="cpu or cuda"):
        piper_device()


def test_missing_cuda_fails_before_voice_load(monkeypatch):
    ort, loader, _ = runtime(monkeypatch, available=False)
    with pytest.raises(GenerationError) as caught:
        load_voice("voice.onnx", "voice.json", "cuda")
    assert caught.value.code == "TTS_GPU_UNAVAILABLE"
    assert "LOCAL_GPU_SETUP.md" in caught.value.action
    ort.preload_dlls.assert_not_called()
    loader.assert_not_called()


def test_cuda_is_preloaded_and_actual_session_verified(monkeypatch):
    ort, loader, session = runtime(monkeypatch)
    load_voice("voice.onnx", "voice.json", "cuda")
    ort.preload_dlls.assert_called_once_with()
    loader.assert_called_once_with("voice.onnx", config_path="voice.json", use_cuda=True)
    session.disable_fallback.assert_called_once_with()


def test_silent_cpu_fallback_is_rejected(monkeypatch):
    runtime(monkeypatch, actual=False)
    with pytest.raises(GenerationError, match="fell back to CPU"):
        load_voice("voice.onnx", "voice.json", "cuda")


def test_cuda_failure_has_safe_actionable_error(monkeypatch):
    runtime(monkeypatch, load_error=True)
    with pytest.raises(GenerationError) as caught:
        load_voice("voice.onnx", "voice.json", "cuda")
    assert caught.value.code == "TTS_GPU_UNAVAILABLE"
    assert "Private local path" not in str(caught.value)


def test_cpu_does_not_require_or_preload_cuda(monkeypatch):
    ort, loader, session = runtime(monkeypatch, available=False, actual=False)
    load_voice("voice.onnx", "voice.json", "cpu")
    loader.assert_called_once_with("voice.onnx", config_path="voice.json", use_cuda=False)
    ort.preload_dlls.assert_not_called()
    session.disable_fallback.assert_not_called()
