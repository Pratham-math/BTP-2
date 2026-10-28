# Project context and handoff

Updated: 28 October 2026. The current review and open issues are in
[PROJECT_ANALYSIS_2026-10-27.md](PROJECT_ANALYSIS_2026-10-27.md).

## Scope and user decisions

- The user selected **Tinker** as the project name on 28 October 2026. App,
  browser/API titles, package metadata and documentation use this name. The
  governing plan is `Tinker_Complete_Platform_Implementation_Plan.md`.
  Existing database/login names, backup format, browser-storage keys and GitHub
  repository URLs retain their compatibility identifiers so the rename does
  not reset accounts, saved code, preferences or existing infrastructure.

- Implement `Tinker_Complete_Platform_Implementation_Plan.md`; it supersedes
  the old MVP-only restrictions. Keep React, FastAPI, provider adapters and the
  safe Manim/FFmpeg renderer.
- Keep service use free-only. Billing details do not authorize spending. No
  separate Linux server is available for learner-code execution.
- On 28 October the user authorized Python execution on this laptop for a local
  demo, skipping Judge0. `PLATFORM_PROFILE=local` plus
  `PLATFORM_LOCAL_DEMO_PYTHON=true` selects the opt-in LocalRunner. This exception
  covers trusted demo programs, not public/shared submissions or secure isolation.
- The explicitly selected existing account received an audited administrator
  grant. Do not infer permission to promote other users.
- Account deletion removes private study/name/email and retains anonymized
  classroom records. A backup-expiry policy is still unresolved.
- Ask about material ambiguity; do not silently replace infrastructure, switch
  providers or report fixtures as live acceptance.

## Current implementation

Python checkpoint preparation now repairs failed executable checks up to twice
instead of reusing the same invalid question forever. The reproduced failure
was a function-only reference with Python function calls placed in stdin, while
the runner executes complete stdin/stdout programs. Planning/repair instructions
now state that contract explicitly. References and supplied alternatives must
pass every test; known-wrong programs must be rejected. Validation no longer
rewrites expected outputs from reference execution. Successful repaired questions
replace the private plan item before persistence, with resumable stage inputs
and objective/variant/kind checks. No live model-quality claim follows from the
fixture tests, and existing failed jobs still need Retry in the app.

Piper narration supports explicit `PIPER_DEVICE=cpu|cuda`. The user requested
GPU support without downloads on 28 October. Local `.env` now selects CUDA;
the installed ONNX Runtime is CPU-only, so narration is blocked with an
actionable readiness error until the user installs the GPU runtime. CUDA mode
preloads runtime DLLs, checks the actual voice session and rejects silent CPU
fallback. No packages/models were downloaded. See `LOCAL_GPU_SETUP.md` and
`scripts/check_piper_gpu.py`. Gemini text selection is unchanged.

Lesson deletion is an archived removal from the workspace: it hides sessions and
personal reports, retires all versions, fences related jobs and prevents retry.
Sources remain separate; classroom assessment history is retained and labelled
archived in teacher reports. Native confirmation dialogs and card option menus
are shared in `client/src/platform/actions.jsx`.

Classroom codes are permanent, readable only by the owning teacher through the
enrollment API/Settings panel. Pausing enrollment preserves the code. A legacy
hash-only code stays valid while a stable visible code is allocated once.
Voluntary leaving differs from teacher revocation: leavers can rejoin with the
code, revoked learners need teacher restoration. Migration
`005_classroom_management.sql` is applied to the local PostgreSQL database and
is safely rerunnable; the local launcher also applies it. No remote Supabase
schema was changed during this update.

Independent video teaching now uses a three-block rolling lead: blocks 1–3 are
normal; the first result on assessment k freezes a teaching plan for block k+3.
The heuristic considers first/latest scores, retries, hints, shown solutions,
recency and relevant prerequisites. Its provisional support/balanced/challenge
levels change scaffolding and worked-example complexity, not fixed objectives or
checkpoint contracts. See `server/learning/adaptation.py`. Startup/background
admission and polling live in `server/learning/service.py`; background jobs no
longer get cancelled as disposable speculation, and normal clips cannot bypass
a committed adaptive plan. Quota-deferred plans persist for retry. Classroom
routes remain reviewed-only. These are implementation/fixture checks, not a
validated student-ability model or a live teaching-quality benchmark.

Local demo Python now uses separate temporary subprocesses with five-second wall
timeouts, bounded captured output, filtered inherited environment and owned-tree
cleanup. Outcome files live under the worker job cache for restart recovery.
The API restricts this mode to loopback clients and publicly labels it as
`runner_mode=local_demo`, `runner_isolated=false`. Production/default settings
continue using Judge0. This is not OS filesystem/network/memory isolation.

The UI supports persistent light/dark mode with toggles on the sign-in screen
and workspace header. The initial theme follows the system preference until a
manual choice is saved in `btp2.theme`. The early `/assets/theme-init.js` script
sets the theme before React loads; the Python editor follows the chosen mode.
Theme code is in `client/src/platform/theme.jsx` and `client/src/themes.css`.
Source originals and reviewed lesson artwork preserve their source colours.

Independent study now separates private sessions from classroom work and offers
searchable lesson states, resume/progress cards and preparation recovery. Classroom
workspaces separate student assignments from teacher drafts/review, members and
course progress. Assignment creation supports an optional due date.

Job responses include advisory ETA ranges. New worker claims record private
`result._timing` metadata (hidden by the API); compatible clean completed runs
refine per-user estimates after three samples. Initial ranges are explicitly
rough, queued estimates exclude waiting, and paused/recovering/overrunning work
has no completion countdown. Full lesson estimates scale by unprepared objectives;
quick-lesson estimates target the first playable block. This is not a capacity
benchmark or a promise that missing infrastructure will succeed.

The source workspace now has staged uploads, live extraction/recovery states,
search/status filters, multi-source lesson selection, private title edits and a
section-by-section review with warning counts, unsaved-edit protection and a
clear confirmation-to-lesson action. Its UI is in `client/src/pages/Sources.jsx`.
`PYTHON_RUNNER_SETUP.md` gives the separate-host Judge0 procedure;
`scripts/check_runner.py` probes configuration without executing code or enabling
the isolation flag. A separate runner is still not configured.

Source-management update, 28 October: saved sources can be removed from the
library or preview with confirmation; selected quick-lesson files can be removed
before upload. Active lesson references/preparation block destructive source
removal. Local YouTube extraction is available when a server-side Gemini key and
Gemini extraction model are configured, with canonical public links, derived
timestamped notes and mandatory author confirmation. Confirmed sources now open
the source-based independent lesson planner. `PLATFORM_VISION_MODEL` optionally
selects a Gemini extraction model independently of Ollama text generation.

The authenticated entry point is `server.platform:app`; the frontend is
`client/src/App.jsx`. The single-owner MVP in `server/main.py` and
`client/src/LegacyVideoApp.jsx` is historical and must not be exposed as the
multi-user platform.

The platform implements accounts, independent study/classrooms, source versions,
batched curricula, adaptive checkpoints, durable jobs, progress, review gates,
private media and retryable account maintenance. See
[IMPLEMENTATION_PROGRESS.md](IMPLEMENTATION_PROGRESS.md) for the current work
and [PLATFORM_STATUS.md](PLATFORM_STATUS.md) for evidence and release gaps.

Server secrets and answer keys stay on the server. Learner code runs only on a
separately isolated runner. Teachers cannot see independent study. Classroom
publication binds review to the exact immutable version and all reachable assets.

## AI providers: Gemini is optional for local text lessons

- `server/lessons/authoring.py` supports explicitly selected Ollama author and
  verifier calls; `server/lessons/production.py` supports Piper narration.
- Select them with `PLATFORM_TEXT_PROVIDER=ollama` and
  `PLATFORM_SPEECH_PROVIDER=piper`; pin evaluated installed models in
  `PLATFORM_TEXT_MODEL` and `PLATFORM_VERIFIER_MODEL`. The legacy `OLLAMA_MODEL`
  setting alone does not select platform author/verifier models.
- Current local configuration selects Gemini for platform text and Piper for
  speech, with text/verifier model IDs configured. Piper and its voice now
  produce a real local sample. Ollama is installed and running; Qwen3 was
  downloaded and passed a small schema-constrained runtime check. Provider
  settings have not been changed and Gemini quota/access is not verified.
- Historical October MVP runs did use real Qwen3/Piper. Preserve that evidence
  in [LEGACY_MVP_PROGRESS.md](LEGACY_MVP_PROGRESS.md); do not reuse its machine
  installation or process claims as current facts.
- A Gemini key is unnecessary for Ollama/Piper text-based lessons. The current
  image/YouTube extraction adapter uses Gemini; corrected text can avoid that
  dependency. Full local multimodal extraction is not implemented.
- Either route needs teaching, verifier and narration review. No full-platform
  model benchmark or real narrated lesson has passed acceptance. There is no
  automatic provider fallback.

## Infrastructure and operation

The current checkout uses a newly initialized local PostgreSQL database and
local password accounts. The separate Supabase project and selected initial
administrator were configured previously; real multi-account/logout/revocation
acceptance remains open. Keep credentials in ignored local `.env`; never
replace it with the example.

Local private storage is available. Private R2 storage, isolated Python grading,
production hosting and live model acceptance remain unavailable. The local
profile currently advertises document extraction even though its parser does
not have verified OS isolation. Local account erasure is incomplete; see the
analysis report for confirmed answer-key exposure and other important gaps.

Use [SERVICE_SETUP.md](SERVICE_SETUP.md) for the provider choices and guided
services, [PLATFORM_SETUP.md](PLATFORM_SETUP.md) for exact configuration, and
[OPERATIONS.md](OPERATIONS.md) for recovery, retention and acceptance workloads.

```powershell
.\scripts\checks.ps1
.\scripts\start-local.ps1
```

The checks run backend tests, frontend tests and a production client build.
Each run creates its own pytest temp/cache directory under ignored `.run` to
avoid stale Windows temp-directory permissions.
Worker switches are `-Worker`, `-Grader` and `-Maintenance`; do not start
unconfigured workers or enable verification flags to hide readiness errors.

## Repository publication

The destination is [Pratham-math/BTP-2](https://github.com/Pratham-math/BTP-2),
whose default branch is `main`. This checkout has a `.git` directory and local
uncommitted setup changes. Preserve existing remote history and local work; do
not force-push or discard changes.

Publish source, migrations, tests, dependency lockfiles and documentation.
Exclude `.env` variants, `.venv`, `.local`, `.run`, `data`, `node_modules` and
`client/dist`; rebuild generated assets from the committed source. GitHub
publication does not imply deployment or completion of the release gates.
