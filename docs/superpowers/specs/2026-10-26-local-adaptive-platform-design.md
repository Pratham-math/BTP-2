# Local-first adaptive learning platform — design

Date: 26 October 2026. Status: draft for approval.

## Intent

College students (mainly our own college) learn a topic from a prompt, PDFs,
PPTX slides, typed notes, or any mix. They watch short narrated, animated
lesson blocks, answer the right kind of assessment after each block, and the
following lessons adapt to how they did. It must genuinely work end to end on
one laptop today (local Ollama + Piper, no cloud accounts) and move to a
college VPS later with configuration only.

## What exists (findings)

- `server.platform:app` already implements most of the product: source
  versions, curriculum planning with objectives, per-objective assessments
  (`mcq`, `multiple`, `trace`, `python`), normal/recap/reinforced blocks with
  unlimited scenes per block, durable jobs, sessions, progress, classrooms.
- The "3 scenes / ~50 s / no assessments" behaviour is the **legacy MVP**
  (`server/main.py`), which is what currently runs. It is not the platform.
- The platform cannot run here because it hard-requires Supabase Auth,
  PostgreSQL (worker refuses SQLite), S3/R2 storage, a Judge0 runner and a
  Docker parser sandbox. None are available locally.
- Measured locally: qwen3 4B writes ~50 s per scene; Manim render ~10 s per
  scene; Piper ~2 s per scene. The language model is the bottleneck.

## Goals

1. **Runs locally, fully offline-capable** (except topic web fetch): one
   command starts DB, Ollama, API, worker and UI. Everything on E:.
2. **Same code on a VPS**: local adapters are selected by configuration;
   Supabase/R2/Judge0 adapters remain for production.
3. **Remotion replaces Manim** for lesson visuals, played in the browser.
4. **Real lesson length**: whole topic split into objectives; each block
   3–6 scenes (~2–4 min); total length follows the material, no cap.
5. **Assessment type chosen per objective** by the planner: MCQ, multi-select,
   predict-the-output (trace), Python coding, and new **short answer**.
6. **Adaptive schedule (the user's rule)**:
   - Block 1 + its recap + both checks are ready before the student starts.
   - Block 2 (normal) is generated while block 1 plays.
   - Right after assessment 1 is graded, block 3 starts generating, shaped by
     assessment-1 results (weak points → more detail/examples on them;
     strong → brisker). In general, assessment *k* shapes block *k+2*.
   - A failed check still routes to the prepared recap + equivalent check.

## Non-goals (now)

YouTube input; OCR for scanned PDFs/images (warned, user corrects text);
legacy `.ppt`; MP4 download of Remotion lessons; production hosting itself.

## Anti-goals

- Fake success: a stage that did not run must not show as done.
- Student code running on a VPS outside an isolated runner.
- Waiting screens with no useful content when something ready exists.

## Design

### 1. Local service adapters (selected by `PLATFORM_PROFILE=local`)

| Need | Production (unchanged) | Local adapter |
|---|---|---|
| Database | Supabase Postgres | Portable PostgreSQL 17 binaries in `.local/pgsql`, data in `.local/pgdata`, port 5433, no TLS on loopback. Migrations applied with a small local shim creating `auth.sessions`. |
| Login | Supabase Google | Local accounts: name + password (PBKDF2 via stdlib `hashlib`), server-signed session token (existing PyJWT, HS256). First account becomes administrator. |
| Storage | R2 via boto3 | `LocalObjectStore` in `data/objects`, same interface; `sign()` returns short-lived HMAC URL served by FastAPI with range support. Usable on a VPS too. |
| Code runner | Judge0 | `LocalRunner`: `python -I` subprocess with timeouts, output cap, temp dir, no env secrets. **Local profile only**; refused when `PLATFORM_PROFILE` is not `local`. |
| PDF/PPTX parsing | Docker no-network sandbox | Separate `python -I` subprocess running existing `extract_document` with time limit (no Docker; Docker Desktop stores images on C:). |
| Topic prompt | Python-docs allowlist | Any topic: Wikipedia REST summary + sections as evidence, plus the student's own prompt text as a typed evidence block. |

Readiness checks report the local adapters honestly (e.g. "runner: local,
not isolated").

### 2. Remotion visuals

- Remove Manim from the platform path. A block's assets become: per-scene
  narration audio (WAV→AAC/M4A via existing FFmpeg), captions (VTT, existing
  cue timing), and the validated scene JSON.
- New client package code: `client/src/remotion/` with one composition per
  template, driven by the existing `VisualSpec` plus cue times (each utterance
  advances `visual_step`). Played with `@remotion/player` synced to the audio.
- Templates: existing `process`, `cycle`, `tree`, `plot`, `code_trace`, plus
  `bullets` (title + revealing points), `compare` (2-column table),
  `array` (indexed cells with pointer), `equation` (KaTeX-rendered steps).
  Schema bounds stay server-side.
- Immutability/review: block checksum covers script JSON + audio hashes +
  template version.
- Licence: Remotion is free for individuals/teams ≤3 and non-commercial
  education use — verify before any commercial use.

### 3. Lesson length

Authoring prompt asks for 3–6 scenes per block with a worked example scene;
validation requires ≥3 scenes for `normal`, ≥2 for `recap`/`reinforced`.
Utterance bounds stay as-is. No lesson-level cap.

### 4. Assessments

- Planner picks the kind per objective with explicit guidance: concepts →
  MCQ/multi-select; code reading → trace; implementation → Python; definitions
  / reasoning → short answer.
- New `short` kind: private key holds a model answer + rubric points; graded
  by the verifier model asynchronously (like Python), returning passed,
  score, missed rubric points, feedback. Rubric-missed points feed adaptation.
- With a 4B model, Python validation is relaxed to: reference passes, at least
  one known-wrong fails (instead of alt + two wrongs); failures trigger one
  bounded repair instead of failing the whole curriculum.

### 5. Adaptive schedule

- Session start: requires block 1 + recap + checks (existing gate).
- On session start and on each block start: enqueue next objective's
  `normal` block at lookahead priority (enable speculation by default locally).
- On grading assessment for objective *k*: compute a performance profile
  `{passed, attempts, weak: [tags], strong: bool}` and enqueue objective
  *k+2* with profile `adapted` and `context_hash = digest(performance)`;
  the author prompt receives the performance summary. If objective *k+1*'s
  block is not ready yet when needed, it is generated with the latest profile.
- When objective *k+2* is reached, the session plays the adapted block if
  ready, else the normal block if ready, else shows a preparing state with
  the recap/practice available.
- Contract change: `BlockDraft.profile` gains `adapted`.

### 6. Running it

`scripts/start-local.ps1` starts Postgres (init + migrate on first run),
Ollama (models in `.local/models`), the API, the generation and grading
workers, and serves the built client. All temp/cache dirs point under
`.local`. Legacy MVP stays in the repo but is not started.

## Constraints

- Nothing written to C: (caches, temp, DB, models, Docker images).
- 16 GB RAM, RTX 3050 4 GB: one model loaded at a time; author and verifier
  both `qwen3:4b-q4_K_M` locally.
- Existing tests must keep passing; new adapters get focused tests.

## Risks

- **Model quality**: a 4B model will sometimes produce weak or rejected
  content; verifier rejections cost minutes. Mitigation: bounded repair,
  clear error state, and the option to point `PLATFORM_TEXT_PROVIDER` at
  Gemini later.
- **Speed**: ~3–5 min per block locally. The k+2 rule gives one block of
  slack (≈ one block's watch time + assessment time).

## Decided by Claude (check these)

- Build on the platform, retire the legacy MVP from use.
- Portable PostgreSQL rather than SQLite (worker locking needs Postgres; same
  as VPS).
- Local password accounts for local/VPS; Supabase stays optional.
- Remotion in-browser playback, not server-side MP4 rendering.
- Wikipedia as topic-only evidence source.
- Short-answer grading by the local model.

## Delivery phases

1. Local adapters + one-command start; one text-notes lesson generated and
   played end to end with existing Manim path.
2. Remotion player + templates; Manim removed from the platform path.
3. Assessment kinds (short answer, kind selection), lesson length, and the
   k+2 adaptive schedule.
4. PDF/PPTX/topic/mixed sources end to end; final verification.
