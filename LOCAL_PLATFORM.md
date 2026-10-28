# Running the full platform locally

The local profile runs the app and its database on one Windows laptop. Text
generation can use either Ollama or Gemini, according to the existing host
configuration. For the user's laptop-only demonstration, Python grading can use
the explicit local demo runner described below. A separately isolated runner is
still required for shared or untrusted submissions.
Runtime files, caches and uploads are stored inside the project folder.

| Piece | Local version | Where |
|---|---|---|
| Database | Portable PostgreSQL 17, loopback port 5433 | `.local/pgsql`, data in `.local/pgdata` |
| Accounts | Email/username + password (first account is administrator) | `local_credentials` table |
| Files and media | Disk storage with signed links | `data/objects` |
| Lesson writer | Ollama + `qwen3:4b-q4_K_M` | `.local/ollama`, `.local/models` |
| Narration | Piper `en_US-lessac-medium` | `.local/voices` |
| Visuals | Remotion, drawn live in the browser | `client/src/remotion` |
| Code checks | Opt-in local demo subprocess, or separately isolated Judge0 | See the demo exception below |
| PDF/PPTX reading | Separate no-network parser process | `server/ingestion/local_parse.py` |
| Topic reference | Wikipedia article for the topic | `server/ingestion/curated.py` |

`PLATFORM_PROFILE=local` in `.env` selects local accounts, storage and source
handling. The text and speech providers remain separately configured. Without
the local profile, the production Supabase and R2 adapters are used.

## First-time setup

1. `uv venv --python 3.12 .venv` and
   `uv pip install --python .venv\Scripts\python.exe -r requirements-platform.txt -r requirements-local.txt`
   with `UV_CACHE_DIR` pointing into `.local\cache`.
2. `npm ci` and `npm run build` in `client` (npm cache in `.local\cache\npm`).
3. Portable Ollama in `.local\ollama`; `ollama pull qwen3:4b-q4_K_M` with
   `OLLAMA_MODELS=.local\models`.
4. Piper voice into `.local\voices` (`python -m piper.download_voices en_US-lessac-medium`).
5. PostgreSQL binaries zip unpacked into `.local\pgsql`.

## Daily use

### Python on this laptop for the demo

The user explicitly authorized this exception on 28 October 2026. In the existing
ignored `.env` use:

```dotenv
PLATFORM_PROFILE=local
PLATFORM_LOCAL_DEMO_PYTHON=true
```

Restart the API, generation worker and grading worker after changing the setting.
No Judge0 URL, token, server or language ID is needed for this mode. The existing
Python 3.12 environment executes standard-library programs with a five-second
per-test wall-time limit and bounded captured output (64 KB stdout, 8 KB stderr).
Each run uses its own temporary directory and a filtered inherited environment;
owned child processes are cleaned up after execution. Grading outcomes are saved
under the private job cache so interrupted workers can resume.

**This is not a security sandbox.** Python still has the logged-in user's OS
permissions, including file and network access. It has no proven memory or CPU
isolation. Use only trusted demo programs; keep the app at
`http://127.0.0.1:8000`, without public tunnels, reverse proxies or LAN exposure.
The API rejects non-loopback clients while this mode is enabled and explicitly
reports `runner_mode=local_demo`, `runner_isolated=false`. The UI labels the mode.

The flag defaults to false and has no effect in the production profile. To go
back to the separate runner, set `PLATFORM_LOCAL_DEMO_PYTHON=false`, configure
[PYTHON_RUNNER_SETUP.md](PYTHON_RUNNER_SETUP.md), then restart all three processes.

### Start the app

```powershell
.\scripts\start-local.ps1
```

Open http://127.0.0.1:8000, create an account, and choose **New lesson**:
type a topic and what you want to be able to do, optionally paste notes and
attach PDF/PPTX files. One background job reads the material, plans the
objectives and assessments, and prepares the first video block.

```powershell
.\scripts\stop-local.ps1
```

Logs are in `.run\logs`. The first start creates the database and applies
`migrations/local/000_shim.sql`, `migrations/0*.sql` and
`migrations/local/100_local_accounts.sql`.

## Lesson and classroom controls

- Use a lesson card's **⋯ → Delete lesson**, or the same menu on its learning-path
  page. Confirmation removes it from your workspace and cancels preparation.
  Records are archived; saved sources stay in the source library and classroom
  assessment history remains available to the teacher.
- Use a classroom card's **⋯ → Leave classroom**, or **Settings → Leave classroom**.
  A voluntary departure can be reversed by joining with the code while enrollment
  is open. A teacher revocation still requires teacher restoration.
- Teachers find the **permanent class code** in **Classroom → Settings**. The
  roster's **Invite learners** shortcut opens that panel. Students cannot retrieve
  the code through the API or classroom UI. **Pause enrollment** and **Open
  enrollment** use the same code. Existing legacy invitations remain valid.
- Migration `005_classroom_management.sql` adds stable-code/enrollment state and
  voluntary-departure fields. It is already applied locally and is run by the
  local launcher for existing databases. Existing records are preserved.

## How lessons adapt

- Block 1 and its recap are prepared before you start. Normal blocks 2 and 3
  are queued in the background; you do not wait for the whole lesson to render.
- The first answer to assessment *k* schedules block *k+3*: assessment 1 shapes
  block 4, assessment 2 shapes block 5, and so on. It can generate while you
  watch the two intervening blocks. This is a lead-time strategy, not a guarantee
  of zero waiting when the model or renderer is slow.
- A provisional 0–100 learning signal uses first/latest correctness (including
  partial scores), retries, hints and shown solutions. Recent concepts have more
  weight, with extra weight for relevant prerequisites. It selects supportive,
  balanced or challenge teaching: scaffolding, conceptual pacing and example
  complexity change; required coverage and assessment difficulty do not.
- Each future teaching plan freezes when its triggering first assessment is
  graded, avoiding regeneration on every retry. Retakes still update the live
  signal and inform plans triggered by later assessments. Queue-full plans remain
  saved and retry admission during session polling or playback progress saves.
- Independent bulk preparation stops at the first three blocks, avoiding unused
  normal videos for later objectives. Lessons with at most three blocks have no
  later adaptive video, but still offer assessment-driven recaps and practice.
- A wrong answer plays the recap and asks an equivalent question.
- Classrooms use only their finite reviewed normal/recap routes, never freshly
  generated unreviewed adaptive videos.

## Assessment types

The planner picks per objective: multiple choice, multi-select, predict the
output, Python coding (using the configured local-demo or separate runner), or a
short written answer graded by the selected verifier model against a rubric.

## Limits to know

- The local model is small (4B). Expect a few minutes per block and some
  weaker explanations; local mode records verifier findings instead of
  blocking, and skips unreadable (scanned) pages.
- The former local subprocess runner is not an isolation boundary. The app and
  workers use the isolated-runner adapter instead; Python grading reports a
  configuration error until a separate runner passes its isolation checks.
- Scanned PDFs need OCR, which is not included; use text-based PDFs or notes.
