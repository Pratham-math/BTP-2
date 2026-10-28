# Tinker Learning Studio

React/FastAPI teaching platform for private independent study and teacher-reviewed
classrooms. The governing specification is
[Tinker_Complete_Platform_Implementation_Plan.md](<Tinker_Complete_Platform_Implementation_Plan.md>).
The user approved this expanded scope on 22 October 2026.

The platform implementation is **not a completed or deployed release**.
Supabase PostgreSQL is provisioned and its restricted backend connection is
verified. Multi-account acceptance, storage, model/voice evaluation, isolated execution,
human lesson review and production acceptance remain open. See
[PLATFORM_STATUS.md](PLATFORM_STATUS.md) for the evidence and remaining work.

Google login works and the user-selected initial administrator is configured.
Remaining services are guided in [SERVICE_SETUP.md](SERVICE_SETUP.md); no free
isolated runner host is currently available.

Lesson generation/verification can use **Ollama**, with **Piper** narration;
Gemini is optional for that text-based path. Local provider support is
implemented, but this environment still needs its runtime/model/voice setup and
quality evaluation. Current image/YouTube extraction uses Gemini. Storage and
isolated Python grading are separate requirements for either AI route.

## Run it on one laptop (no cloud accounts)

See [LOCAL_PLATFORM.md](LOCAL_PLATFORM.md): `.\scripts\start-local.ps1`, then open
http://127.0.0.1:8000. Local PostgreSQL, Ollama, Piper and Remotion visuals,
all stored inside this folder.

## Start here

1. Read [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) and
   [IMPLEMENTATION_PROGRESS.md](IMPLEMENTATION_PROGRESS.md) for the current
   handoff. Follow [PLATFORM_SETUP.md](PLATFORM_SETUP.md) for services, dependencies and
   the three local processes.
2. Keep secrets in the ignored local `.env`; never copy it into a frontend or
   image. Do not replace the existing configured `.env` with the example.
3. Build the client and run `scripts/start-platform.ps1`. Open
   [the local app](http://127.0.0.1:8000).
4. Use [OPERATIONS.md](OPERATIONS.md) for worker recovery, private storage,
   encrypted application backups and the release checklist.

## Implemented paths

- Supabase signed identity and live-session verification, trusted database roles,
  course enrollment/revocation and server-enforced tenant boundaries.
- Versioned source previews/corrections, complete objective DAGs and assessment
  contracts, bounded author/verifier/repair stages.
- Incremental independently playable blocks, semantic narration cues, captions
  and five fixed Manim visuals, including a runner-verified Python trace.
- Durable PostgreSQL jobs with scoped deduplication, leases, fencing, admission
  limits and a separate grading queue.
- Idempotent assessments, hints/recaps/equivalent checks, explicit assisted and
  unresolved outcomes, revision-checked progress and account-synced code drafts.
- Exact-version classroom review, immutable approval, publication, assignments,
  draft forks/edits and private-versus-classroom reporting.

Unverified source adapters are disabled by default. A feature flag or passing
fixture does not establish that an input or a generated lesson meets release
acceptance.

## Development checks

Use CPython 3.12 and Node.js 22. The worker also needs FFmpeg/ffprobe and Manim's
native dependencies. From PowerShell:

```powershell
.\scripts\checks.ps1
```

This runs the Python suite, frontend auth-screen regression tests and production
client build. The current baseline is **142 backend and 15 frontend tests**;
see [PLATFORM_STATUS.md](PLATFORM_STATUS.md) for the latest verification.
The media tests use synthetic tones, not real narration. SQLite and injected
identities are test fixtures only; production uses PostgreSQL and Supabase Auth.
The checked-in migration scripts require operator execution, not the API login.

## Repository map

| Area | Responsibility |
| --- | --- |
| `server/platform.py`, `platform_api.py`, `auth/` | Authenticated API and resource permissions |
| `server/lessons/`, `ingestion/` | Evidence, contracts, authoring, safe extraction, production and edits |
| `server/learning/`, `assessment/` | Sessions, routing, grading and external runner |
| `server/worker/` | Durable generation and grading dispatch |
| `client/src/platform/`, `pages/`, `player/` | Accounts, independent/classroom UI and playback |
| `migrations/`, `deploy/`, `scripts/`, `tests/` | Schema, host packaging, checks and operations |

The original single-owner video MVP remains in `server/main.py` and
`client/src/LegacyVideoApp.jsx`, with historical instructions in
[LEGACY_MVP.md](LEGACY_MVP.md) and [LOCAL_SETUP.md](LOCAL_SETUP.md).
Historical progress and local-model demonstrations are preserved in
[LEGACY_MVP_PROGRESS.md](LEGACY_MVP_PROGRESS.md).
It is not mounted by the platform and must not be exposed as a multi-user API.
