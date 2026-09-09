# Prompt-to-video MVP

A deliberately small learning-video prototype. Enter a topic or explanation
request; Gemini plans a three-scene lesson and narrates it, Manim animates the
diagrams, and FFmpeg combines everything into one playable MP4.

This version does **not** include uploads, quizzes, checkpoints, accounts, or
progress tracking.

## Requirements

- Python 3.10+
- Node.js 20+
- `ffmpeg` and `ffprobe` on `PATH`, with H.264 and AAC support
- A Gemini API key with access to the configured text and TTS models

Manim is included in `requirements.txt`. The app uses its CPU renderer and plain
text, so these templates do not require a GPU or LaTeX. For an existing checkout,
rerun `.venv\Scripts\python -m pip install -r requirements.txt` and restart FastAPI.
Other operating systems may need Cairo/Pango build dependencies; see the
[Manim installation guide](https://docs.manim.community/en/stable/installation/uv.html).

## Windows PowerShell setup

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
Set-Location client
npm install
Set-Location ..
```

You can add or replace the Gemini API key from Settings in the web interface.
FastAPI saves it to `.env`, and the saved value is never returned to the browser.
Model names and voice can still be changed directly in `.env`.

## Run

For a single-server demo:

```powershell
Set-Location client
npm run build
Set-Location ..
.venv\Scripts\python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Open <http://127.0.0.1:8000>.

For development, run the backend command above and `npm run dev` from `client`
in another terminal, then open the Vite URL. Vite proxies `/api` to port 8000.

## Checks

```powershell
.venv\Scripts\python -m pytest -q
Set-Location client
npm run build
Set-Location ..
.venv\Scripts\python scripts/check_media.py data\<video-id>\video.mp4
```

The automated media tests render all four Manim templates, check changing
frames, timing, and the combined 720p H.264/AAC MP4. They use explicitly synthetic
tones and do not call Gemini. A real end-to-end acceptance check requires a configured key, generation
from the web UI, and listening to the resulting narration.

## How it works

- `generate_script` asks Gemini for a validated three-scene JSON script with
  a visual plan for every scene.
- `generate_audio` asks Gemini TTS for each narration and writes valid WAV files.
- `make_animated_scene` runs our fixed Manim templates in a separate local
  process, fitting each animation to the narration's duration. FFmpeg adds the
  audio; `combine_videos` joins normalized clips into `video.mp4`.
- FastAPI runs one generation job in the background and exposes status, retry,
  playback, and download endpoints.

The visual templates support processes, cycles, trees, and scatter plots with
an optional least-squares fitted line. Nodes can include simple sun, plant,
water, cloud, or computer illustrations. Gemini supplies labels, connections,
and numbers, never executable code. Graphs are validated before rendering.
Animations follow the scene duration; they are not aligned to individual spoken
words. This is a diagram renderer, not a general cinematic image/video model.
Manim adds no API fee; the existing Gemini calls still have their model/project
quotas. New videos use Manim automatically. Existing MP4s remain unchanged, and
retries of older scripts without visual plans retain the Pillow slide renderer.

Each result is saved under `data/<video-id>/`. Failed jobs retain valid completed
files so Retry can reuse them. The app is a local presentation prototype: its
background job is not a durable production queue, and Gemini TTS is a preview
model whose access and quota depend on the API project.
