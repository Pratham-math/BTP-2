# Local NVIDIA narration

The user requested GPU support without automatic downloads on 28 October 2026.
The laptop has an RTX 3050 6 GB with a working NVIDIA driver. Ollama previously
offloaded all Qwen3 layers to CUDA, but platform text generation currently uses
Gemini. Changing Piper does not switch the text provider.

Piper now supports `PIPER_DEVICE=cpu` or `PIPER_DEVICE=cuda`. CUDA mode requires
a real CUDA-backed voice session; missing libraries or CPU fallback produce an
actionable error. The ignored local `.env` selects CUDA. The installed runtime
is currently CPU-only, so GPU narration is pending the manual installation below.
No package, driver or model was downloaded during this change.

## Install manually

Stop the app first, then run these commands in PowerShell from the project root:

```powershell
.\scripts\stop-local.ps1
.\.venv\Scripts\python.exe -m pip uninstall -y onnxruntime onnxruntime-gpu
.\.venv\Scripts\python.exe -m pip install "onnxruntime-gpu[cuda,cudnn]==1.23.2"
.\scripts\start-local.ps1
```

The install command downloads ONNX Runtime GPU and NVIDIA CUDA/cuDNN runtime
packages. They can be large; no full CUDA development toolkit or PyTorch install
is needed for this route. Keep only one ONNX Runtime distribution in this
environment because CPU/GPU packages share the same Python module. Reinstalling
`requirements-local.txt` selects the CPU package again; repeat the GPU replacement
afterwards if needed. The existing Piper voice needs no new download.

[ONNX Runtime CUDA installation and DLL-loading documentation](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html#preload-dlls)
describes the runtime extras and `preload_dlls()` used by the voice subprocess.

## Verify without downloading

```powershell
.\.venv\Scripts\python.exe scripts\check_piper_gpu.py
```

This loads the installed voice on CUDA and synthesizes a short sample into a
temporary directory, then removes it. It checks provider selection, inference
and WAV output. It does not contact a model service or download assets. A pass
establishes local GPU narration, not full lesson quality or a speed guarantee.
Some phonemization and orchestration still use the CPU.

To explicitly return to CPU narration, set `PIPER_DEVICE=cpu` in `.env` and restart
the API and workers. Ollama GPU support is separate and already available; keep
the current text-provider setting unless you intend to switch to local text.
