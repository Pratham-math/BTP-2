# Project context and handoff

Updated: 25 October 2026.

## Scope and user decisions

- Implement `BTP2_Complete_Platform_Implementation_Plan (1).md`; it supersedes
  the old MVP-only restrictions. Keep React, FastAPI, provider adapters and the
  safe Manim/FFmpeg renderer.
- Keep service use free-only. Billing details do not authorize spending. No
  separate Linux server is available for learner-code execution.
- The explicitly selected existing account received an audited administrator
  grant. Do not infer permission to promote other users.
- Account deletion removes private study/name/email and retains anonymized
  classroom records. A backup-expiry policy is still unresolved.
- Ask about material ambiguity; do not silently replace infrastructure, switch
  providers or report fixtures as live acceptance.

## Current implementation

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
- Current local configuration selects Gemini for platform text/speech, with
  blank platform model IDs. A read-only check on 25 October found Ollama
  unreachable and no installed Piper package or valid voice files in this
  environment. The configured legacy Qwen3 tag is not proof of installation.
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

Supabase PostgreSQL is provisioned, migrations 001–004 are applied, and the
restricted backend connection uses verified TLS. Google login works according
to the user; real multi-account/logout/revocation acceptance is still open.
The selected initial administrator is configured. Keep all credentials only in
the ignored local `.env`; never replace it with the example.

Private R2 storage, isolated Python grading, production hosting and live model
acceptance remain unavailable. Missing services deliberately produce readiness
errors. Document extraction/isolation is unverified and related release flags
remain disabled. Requested identity erasure also needs a host-only Auth admin
credential and an operating maintenance worker.

Use [SERVICE_SETUP.md](SERVICE_SETUP.md) for the provider choices and guided
services, [PLATFORM_SETUP.md](PLATFORM_SETUP.md) for exact configuration, and
[OPERATIONS.md](OPERATIONS.md) for recovery, retention and acceptance workloads.

```powershell
.\scripts\checks.ps1
.\scripts\start-platform.ps1
```

The checks run backend tests, frontend tests and a production client build.
Each run creates its own pytest temp/cache directory under ignored `.run` to
avoid stale Windows temp-directory permissions.
Worker switches are `-Worker`, `-Grader` and `-Maintenance`; do not start
unconfigured workers or enable verification flags to hide readiness errors.

## Repository publication

The destination is [Pratham-math/BTP-2](https://github.com/Pratham-math/BTP-2),
whose default branch is `main`. The current workspace has no `.git` directory.
Preserve the existing remote history when publishing this source snapshot; do
not initialize an unrelated history, force-push or discard remote changes.

Publish source, migrations, tests, dependency lockfiles and documentation.
Exclude `.env` variants, `.venv`, `.local`, `.run`, `data`, `node_modules` and
`client/dist`; rebuild generated assets from the committed source. GitHub
publication does not imply deployment or completion of the release gates.
