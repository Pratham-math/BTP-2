# Work report — 26 Oct 2026

## Goal
Make the full Tinker platform run locally (no cloud, nothing on C:), use Remotion
instead of Manim, have real assessments of varied types, longer lessons, and the
adaptive rule: assessment *k* shapes lesson block *k+2*.

## Setup done (all inside `BTP-2/`, on E:)
| Item | Location | Status |
|---|---|---|
| Python 3.12 venv + deps | `.venv` (caches in `.local/cache`) | ✅ |
| Client deps + build (+ remotion, @remotion/player, katex) | `client/` | ✅ |
| Ollama 0.40.11 (portable) + `qwen3:4b-q4_K_M` (RTX 3050) | `.local/ollama`, `.local/models` | ✅ |
| Piper voice `en_US-lessac-medium` | `.local/voices` | ✅ |
| PostgreSQL 17.6 (portable, port 5433) | `.local/pgsql`, data `.local/pgdata` | ✅ |
| `.env` set to local profile | `.env` | ✅ |
| Test account (generated) | `.local/test-account.txt` | ✅ |

## Code changes
**Local profile (`PLATFORM_PROFILE=local`)** — production adapters unchanged
- `server/local_services.py`: password accounts, on-disk storage with signed URLs, local Python runner, local PDF/PPTX parser call.
- `server/local_api.py`: `/api/local/register|login`, signed file serving (type allowlist + sandbox headers after a security review).
- `server/ingestion/local_parse.py`: no-network parser subprocess.
- `server/database.py`: `LocalCredential` model; loopback DB without TLS.
- `migrations/local/000_shim.sql`, `100_local_accounts.sql`.
- `server/platform_settings.py`, `platform.py`, `worker/__main__.py`, `worker/tasks.py`: wire local adapters.
- `server/ingestion/curated.py`: any topic → Wikipedia article as source.
- `scripts/start-local.ps1` / `stop-local.ps1`: one command starts DB, Ollama, API, workers.

**Remotion instead of Manim**
- `server/lessons/production.py`: per-scene narration audio (m4a) + captions; no Manim render (`PLATFORM_RENDERER=remotion`).
- `client/src/remotion/Scene.jsx`, `ScenePlayer.jsx`: browser-drawn scenes synced to narration.
- `server/visuals.py`: new visual kinds `bullets`, `compare`, `array`, `equation` (legacy MVP kept on old kinds).

**Longer lessons**
- Author prompt: normal block 4–6 scenes, recap 2–3, varied visuals; thin blocks re-requested.

**Assessments**
- New `short` (written answer) kind graded by the model with a rubric (`worker/tasks.py: grade_short`).
- Planner picks `check_kind` per objective (mcq / multiple / trace / python / short).
- MCQ keys given as option text/letter are mapped to option IDs.
- Local fallback: if a question keeps failing validation, use a short-answer check.

**Adaptive schedule**
- `server/learning/service.py`: after the first answer on objective *k*, an `adapted` block for *k+2* is queued using the learner's results; next-block lookahead on; already-prepared blocks are preferred so the learner doesn't wait.

**One-step lesson creation**
- `POST /api/lessons/quick`: topic + goal + optional notes/PDF/PPTX + reference article → one job reads, plans, confirms and prepares block 1.
- New simple "New lesson" page; friendly progress labels.

**Local robustness for the 4B model**
- Unmentioned source sections auto-excluded (recorded); verifier findings recorded instead of blocking; Ollama context set (`PLATFORM_OLLAMA_CONTEXT`).

**Docs**: `LOCAL_PLATFORM.md`, README link, design in `docs/superpowers/specs/2026-10-26-local-adaptive-platform-design.md`.

## Tests
- Backend: **148 passed** (last full run, before the final step-repair edit). One older lease test is timing-flaky on Windows (pre-existing).
- Frontend: 15 passed; production build OK.
- New `tests/test_local_profile.py` (runner, storage, contracts, k+2 schedule).

## Live end-to-end run (in progress)
Lesson "Binary search" via the one-step flow:
- ✅ Source reading, scope, 6 good objectives, 12 assessments written and verified.
- ❌ Block 1 authoring failed validation: the model numbers visual steps from 1 / past the end.
- Last edit (not yet verified, tests not re-run): `InstructionScene` now repairs step numbers instead of rejecting.

## Known issues / next steps
1. Verify the step-repair edit, restart workers, let block 1 finish, play it in the browser.
2. Test a full session: answer checks, confirm *k+2* adapted block and short-answer grading.
3. The in-progress lesson was planned before `check_kind` existed → its checks are all MCQ; new lessons will vary types.
4. Speed: ~1 min per scene of writing on the local 4B model; planning a 6-objective lesson took ~25 min.
5. Not committed to git yet.
