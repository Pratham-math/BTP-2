# Local and cloud video generation

This guide contains runtime installation and **historical single-owner MVP**
instructions. For the current authenticated app, use
[SERVICE_SETUP.md](SERVICE_SETUP.md) and [PLATFORM_SETUP.md](PLATFORM_SETUP.md).
The three-scene limits and Settings/preset UI below do not define platform scope.
Gemini is optional for Ollama/Piper text-based platform lessons.

The app supports two complete presets. **Local** uses Ollama text and Piper
speech; **Cloud API** uses Gemini for both. Manim and FFmpeg always run on the
computer hosting FastAPI. A WiFi visitor uses that host's hardware.

## Install once on Windows

Keep the existing `.venv`, FFmpeg/ffprobe and Manim setup. Add local narration:

```powershell
.venv\Scripts\python -m pip install -r requirements-local.txt
```

Install [Ollama](https://ollama.com/download/windows) from its official
distribution. Set `OLLAMA_NO_CLOUD=1` in the environment of the **Ollama app or
service**, restart it, and keep its loopback binding. Setting this variable only
in FastAPI does not change a separately running Ollama service.

Download the selected model explicitly during setup:

```powershell
ollama pull qwen3:4b-q4_K_M
```

This model download is several GB. It is a starting configuration to evaluate;
its presence does not establish content quality or a hardware minimum. Check
available disk and RAM before installing. Other installed completion models can
be selected, but they also need the schema probe and content review.

Download the example voice and retain its model card/license information:

```powershell
New-Item -ItemType Directory -Force .local\voices
Push-Location .local\voices
..\..\.venv\Scripts\python -m piper.download_voices en_US-lessac-medium
Pop-Location
```

The first release supports English voices using packaged eSpeak/text phonemizers;
voices that require additional downloaded phonemizers are excluded. The
directory must contain both `en_US-lessac-medium.onnx` and
`en_US-lessac-medium.onnx.json`. A model/configuration pair is validated and
hashed before use. Voices are never downloaded when Make video is clicked.
Piper's engine and individual voices have separate distribution obligations;
retain their notices before bundling an installer. See the
[Piper voice documentation](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/VOICES.md).

Optional non-secret `.env` settings are listed in `.env.example`. The supported
profiles preserve the existing 24 fps export: 1280×720 and an 854×480 preview.
Diagram limits remain the tested existing limits: process/cycle up to 6 nodes,
tree up to 7 nodes and 4 levels, plot up to 12 points, narration 35–110 words.

## Start and check

The October MVP demonstrations used a portable Ollama runtime and Qwen3 model,
plus real Piper speech. Those historical results are preserved in
[LEGACY_MVP_PROGRESS.md](LEGACY_MVP_PROGRESS.md). They do not describe the current
installation: on 25 October the configured Ollama endpoint was unreachable and
the current environment had no Piper package or valid voice files. Verify the
runtime/model/voice before following the launch instructions. Installation is
separate from the release acceptance gates.

To start this dedicated runtime again after stopping it, use another terminal:

```powershell
.\scripts\start-local-runtime.ps1
```

The launcher uses an installed `ollama` command or the prepared portable binary,
keeps one model/job at a time, and removes cloud keys from its environment. It
refuses to start over an existing service. `-OllamaPath` and `-ModelDirectory`
can explicitly select another installed runtime/model directory. No model is
downloaded by this launcher or by Generate.

```powershell
Push-Location client
npm run build
Pop-Location
.\scripts\start.ps1
```

Open `http://127.0.0.1:8000`, select **Run on this laptop**, and click **Check
setup**. The checks discover the installed model, verify its digest and
completion capability, request a tiny JSON-schema answer, check voice files,
and check media tools/storage. A passed schema probe is not a reviewed lesson
or an offline end-to-end test.

For Cloud API, select that preset and add the Gemini key in Settings. Its
presence is checked without a billable test; live model access/quota can still
fail during generation. Keys stay in the backend's `.env` and are never saved
in frontend storage, job configuration or child-process environments.

```powershell
.venv\Scripts\python scripts\diagnostics.py
.venv\Scripts\python -m pytest -q
Push-Location client
npm run build
Pop-Location
```

The diagnostics report omits prompts, narration, keys and private job contents.
The automated media fixtures use synthetic tones; they do not establish speech
quality or live Gemini/Piper narration.

## Saved work and recovery

Jobs save their request and non-secret provider configuration in `data/<id>/`.
`manifest.json` records input hashes, output checksums, provider identities,
stage timings and ordered scene clips. `timing.json` records measured WAV
durations, a 150 ms lead-in and 350 ms final hold; it does not claim word
alignment. New speech is completed before rendering begins.

One job owns the generation slot. Duplicate client request IDs return the
original job; different requests get a busy response. Closing the browser
preserves the prompt/job selection and restores status polling on return.
Changing the default preset affects new jobs. Resume uses the saved settings;
a changed installed model/voice digest requires an explicit new job.

Cancellation stops owned Piper/Manim/FFmpeg processes and their descendants.
On Windows, those children start suspended, enter a kernel Job Object, then
run. Closing the backend also terminates that owned tree; normal cancellation
waits for its exit before releasing the generation slot. Python workers launch
the current interpreter image directly while retaining the virtual environment,
so Windows Store execution aliases do not bypass the guard. Existing Ollama
services are outside this ownership.
An in-flight inference request can delay cancellation until its response or
deadline. If an Ollama request times out, disconnects after admission, or the
backend stops during it, further local inference is blocked because the
service may still be working. Restart the dedicated Ollama runtime yourself,
then click **I restarted Ollama** in Local Settings and check setup again.
The app never kills a shared Ollama service.

By default the app lets Ollama manage its normal five-minute residency. Set
`OLLAMA_EXCLUSIVE=1` only for an exclusively owned runtime to request unloading
after each call. This can increase cold-load latency. Keep large inference and
rendering stages sequential and measure RAM on the intended laptop.

The backend holds an OS file lock for one app instance per data directory.
Incomplete jobs become **interrupted** on startup. Valid artifacts are reused
only when dependency hashes and checksums match; damaged manifests are retained
and reported. An updated prompt template regenerates text on resume. Downstream
artifacts are reused only if the newly accepted content and their dependencies
still match. Older saved slide scripts still use Pillow, with unverifiable
downstream artifacts regenerated. Existing ready MP4s remain playable.

Default limits: one-hour job deadline, three-minute speech-process deadline per
scene, ten-minute render deadline per scene, 512 MB minimum free disk, and
2 GB maximum job directory. These are bounded failure controls rather than an
enforced RAM sandbox. Successful outputs contain H.264/AAC, fast-start metadata,
all scenes, positive duration, and a bounded decode check before publication.

## Personal app versus shared demo

Launch on loopback for personal use. State-changing API calls require a token
issued by `/api/session`; the UI holds it only in memory. Unexpected browser
origins/hosts are rejected, and settings/key management additionally require
the actual connection peer to be loopback. Forwarded headers do not grant owner
access when using the provided launch script (`--no-proxy-headers`). Preserve
that flag when invoking Uvicorn directly. A server restart invalidates the
browser token; refresh the page.

For a supervised WiFi demo, explicitly configure `APP_HOSTS` and `APP_ORIGINS`
with the host/IP and Vite or FastAPI port being used. Keep localhost entries for
owner settings. This file-based, single-owner prototype does not provide
per-student private storage or authentication.

## Remaining release evidence

After model/voice setup, disconnect external networking while retaining
loopback, and create a fresh three-scene video with no Gemini key. Listen to the
complete narration, inspect all scene transitions/final sentences, and verify
play, seek and download. Live Gemini and local generation have succeeded, and
the user confirmed playback, seek and complete narration for the 43-second local
demonstration. HTTP ranges/downloads and real restart/resume have also passed.
The OS-network-disabled gate remains pending. See `IMPLEMENTATION_PROGRESS.md`
for evidence and `CONTENT_REVIEW.md` for script review findings. Valid JSON and
readable diagrams do not guarantee factual correctness.

The fixed review set is in `scripts/review_prompts.json`. With the backend
stopped to avoid competing inference, run the local script-only benchmark:

```powershell
.venv\Scripts\python scripts\review_local_scripts.py --ids photosynthesis water-cycle binary-search-tree linear-trend
```

Omit `--ids` for all twelve prompts. Candidates and timings are saved in ignored
`.run/local-script-review/`; manual factual/visual review stays explicitly
pending until the report is reviewed. Successful schema validation is not a
content-quality score.

Bounded local candidate answers and validation errors are retained in each job
directory for diagnosis/review. They can contain private study material and are
not exposed through status responses or application logs.

Interactive lessons, assessments, source uploads, accounts and databases are
later milestones and are outside this release.
