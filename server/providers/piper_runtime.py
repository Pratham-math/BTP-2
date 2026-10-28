"""Explicit Piper device selection; never downloads runtimes or voice assets."""
import os

from server.providers.base import GenerationError


GPU_ACTION = (
    'Follow LOCAL_GPU_SETUP.md to install onnxruntime-gpu with CUDA/cuDNN in the '
    'project environment, then restart the API and workers. '
    'Set PIPER_DEVICE=cpu only if you want CPU narration.'
)


def piper_device():
    device = os.getenv("PIPER_DEVICE", "cpu").strip().lower()
    if device not in {"cpu", "cuda"}:
        raise GenerationError("TTS_DEVICE_INVALID", "PIPER_DEVICE must be cpu or cuda.")
    return device


def require_cuda(runtime):
    if "CUDAExecutionProvider" not in runtime.get_available_providers():
        raise GenerationError("TTS_GPU_UNAVAILABLE", "Piper GPU narration requires the CUDA ONNX Runtime provider.", GPU_ACTION)


def load_voice(model, config, device):
    import onnxruntime
    from piper import PiperVoice

    if device == "cuda":
        require_cuda(onnxruntime)
        try:
            onnxruntime.preload_dlls()
        except Exception as error:
            raise GenerationError("TTS_GPU_UNAVAILABLE", "Piper could not load the CUDA/cuDNN runtime libraries.", GPU_ACTION) from error
    try:
        voice = PiperVoice.load(str(model), config_path=str(config), use_cuda=device == "cuda")
    except Exception as error:
        if device == "cuda":
            raise GenerationError("TTS_GPU_UNAVAILABLE", "Piper could not initialize GPU narration.", GPU_ACTION) from error
        raise
    if device == "cuda":
        # ONNX Runtime can silently retry with CPU when CUDA DLL loading fails.
        if "CUDAExecutionProvider" not in voice.session.get_providers():
            raise GenerationError("TTS_GPU_UNAVAILABLE", "Piper fell back to CPU; GPU narration was not started.", GPU_ACTION)
        voice.session.disable_fallback()
    return voice
