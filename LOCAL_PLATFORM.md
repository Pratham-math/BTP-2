# Running the full platform locally

The full platform runs on one Windows laptop with no cloud accounts.
Everything (database, AI model, voice, caches, temp files, uploads) lives
inside this folder. Nothing is written to C:.

| Piece | Local version | Where |
|---|---|---|
| Database | Portable PostgreSQL 17, loopback port 5433 | `.local/pgsql`, data in `.local/pgdata` |
| Accounts | Email/username + password (first account is administrator) | `local_credentials` table |
| Files and media | Disk storage with signed links | `data/objects` |
| Lesson writer | Ollama + `qwen3:4b-q4_K_M` | `.local/ollama`, `.local/models` |
| Narration | Piper `en_US-lessac-medium` | `.local/voices` |
| Visuals | Remotion, drawn live in the browser | `client/src/remotion` |
| Code checks | Local Python runner (time-limited subprocess) | `server/local_services.py` |
| PDF/PPTX reading | Separate no-network parser process | `server/ingestion/local_parse.py` |
| Topic reference | Wikipedia article for the topic | `server/ingestion/curated.py` |

`PLATFORM_PROFILE=local` in `.env` selects all of the above. Without it the
production adapters (Supabase, R2, Judge0, Docker parser) are used, unchanged.

## First-time setup (already done on this machine)

1. `uv venv --python 3.12 .venv` and
   `uv pip install --python .venv\Scripts\python.exe -r requirements-platform.txt -r requirements-local.txt`
   with `UV_CACHE_DIR` pointing into `.local\cache`.
2. `npm ci` and `npm run build` in `client` (npm cache in `.local\cache\npm`).
3. Portable Ollama in `.local\ollama`; `ollama pull qwen3:4b-q4_K_M` with
   `OLLAMA_MODELS=.local\models`.
4. Piper voice into `.local\voices` (`python -m piper.download_voices en_US-lessac-medium`).
5. PostgreSQL binaries zip unpacked into `.local\pgsql`.

## Daily use

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

## How lessons adapt

- Block 1 and its recap are prepared before you start.
- Block 2 (normal) is prepared while you watch block 1.
- When you answer the first check of objective *k*, objective *k+2* is
  prepared from your results so far (weak points get more time; strengths
  move faster). Block *k+1* is already prepared, so you do not wait.
- A wrong answer plays the recap and asks an equivalent question.

## Assessment types

The planner picks per objective: multiple choice, multi-select, predict the
output, Python coding (run by the local runner), or a short written answer
graded by the local model against a rubric.

## Limits to know

- The local model is small (4B). Expect a few minutes per block and some
  weaker explanations; local mode records verifier findings instead of
  blocking, and skips unreadable (scanned) pages.
- The local Python runner is **not** an isolation boundary. On a shared VPS
  use Judge0 (`PLATFORM_PROFILE` unset) or keep the platform private.
- Scanned PDFs need OCR, which is not included; use text-based PDFs or notes.
