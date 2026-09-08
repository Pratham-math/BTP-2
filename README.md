# LearnFrame prompt-to-video MVP

A deliberately small learning-video prototype. Enter a topic or explanation
request; Gemini creates a three-scene lesson and narrates it, Pillow draws the
slides, and FFmpeg combines everything into one playable MP4.

This version does **not** include uploads, quizzes, checkpoints, accounts, or
progress tracking.

## Requirements

- Python 3.10+
- Node.js 20+
- `ffmpeg` and `ffprobe` on `PATH`, with H.264 and AAC support
- A Gemini API key with access to the configured text and TTS models

## Windows PowerShell setup

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
Set-Location client
npm install
Set-Location ..
```

Open `.env` and replace `put_your_key_here` with your Gemini API key. The key is
read only by FastAPI; it is never sent to the browser. Model names and voice can
also be changed there.

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

The automated media test uses an explicitly synthetic tone and does not call
Gemini. A real end-to-end acceptance check requires a configured key, generation
from the web UI, and listening to the resulting narration.

## How it works

- `generate_script` asks Gemini for a validated three-scene JSON script.
- `generate_audio` asks Gemini TTS for each narration and writes valid WAV files.
- `draw_slide` makes a readable 1280×720 image for each scene.
- `make_scene_video` combines each image/audio pair; `combine_videos` joins the
  normalized clips into `video.mp4`.
- FastAPI runs one generation job in the background and exposes status, retry,
  playback, and download endpoints.

Each result is saved under `data/<video-id>/`. Failed jobs retain valid completed
files so Retry can reuse them. The app is a local presentation prototype: its
background job is not a durable production queue, and Gemini TTS is a preview
model whose access and quota depend on the API project.
