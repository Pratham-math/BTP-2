# Implementation progress

Updated: 25 October 2026. The governing specification is
[BTP2_Complete_Platform_Implementation_Plan (1).md](<BTP2_Complete_Platform_Implementation_Plan (1).md>).
The user explicitly approved this scope in place of the original video MVP.

**The current build is an implementation checkpoint, not a completed release.**
See [PLATFORM_STATUS.md](PLATFORM_STATUS.md) for detailed evidence and the full
acceptance matrix, and [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) for handoff.

## Implemented

- React/FastAPI accounts and role-controlled classrooms, private independent
  study, live-session verification and tenant-scoped resources.
- Versioned source evidence, correction and scope confirmation; bounded PDF/page
  preview tooling and isolated extraction boundaries. Unverified adapters remain
  disabled.
- Resumable curriculum planning with explicit source coverage, objective batches,
  prerequisite context, assessment pairs and bounded author/verifier repairs.
- Incremental lesson blocks, normal/recap/reinforced routes, semantic narration
  cues, captions and fixed Manim/FFmpeg visual templates.
- Durable PostgreSQL jobs, leases, fencing, stage reuse, quotas and separate
  generation, grading and account-maintenance queues.
- Choice/output grading, external Python-runner integration, hint/equivalent
  checks, retryable failures, progress resume and saved code drafts.
- Exact-version classroom review/publication, assignments, forks, suspension,
  scoped media access and teacher reports that exclude private study.
- Retryable requested account erasure: private data deletion and anonymized
  classroom retention, with explicit worker-stop and Auth-erasure checks.
- Deployment definitions, encrypted application backup/restore tooling, protocol
  load tooling and credential-safe access logging.

## Latest changes

- Authentication restoration waits for the saved session and verified profile,
  preventing the login screen from flashing during refresh. Regression cases
  cover delayed/stale responses, account changes, token refresh and retry.
- Planning now records included/excluded source coverage and resumes bounded
  objective/assessment batches. A 30-objective fixture exercises the larger path.
- Private source-page previews, cleanup object inventories, maintenance retries
  and account/source UI paths have automated coverage.
- The check script now uses a unique workspace-owned pytest temp/cache directory
  to avoid inaccessible directories left by a different Windows execution user.
- Documentation now distinguishes optional Gemini services from the implemented
  Ollama text/verification and Piper narration path. No provider setting or local
  secret was changed by this documentation update.
- The old progress report is preserved in
  [LEGACY_MVP_PROGRESS.md](LEGACY_MVP_PROGRESS.md). Its historical local-model
  demonstrations do not establish readiness of the current platform.

## Verification

The 25 October run passed 142 backend tests (52.31 seconds), 15 frontend tests
and the production client build. Exact latest results and limitations belong
in [PLATFORM_STATUS.md](PLATFORM_STATUS.md). Run all three with:

```powershell
.\scripts\checks.ps1
```

Render fixtures use synthetic audio. They do not prove live narration quality,
full source extraction, classroom acceptance or production capacity.

## Still open

- Choose and evaluate the AI route. The platform currently selects Gemini with
  blank author/verifier model IDs. The legacy local model name is
  `qwen3:4b-q4_K_M`, but Ollama is unreachable and Piper/voices are absent from
  the current environment. Gemini is optional for text-based lessons; current
  image/YouTube extraction uses the Gemini adapter.
- Configure private object storage and verify signed playback/ranges/CORS.
- Obtain a separately isolated Python runner. The budget is free-only, and no
  separate server or suitable managed allocation has been established.
- Complete source-figure/OCR validation, general orphan/remote-cache cleanup,
  backup expiry, deployment/monitoring and the live/human acceptance matrix.
- Configure and exercise maintenance/Auth erasure and a real restore drill.

Do not mark any item complete because a credential exists, a flag is enabled or
an offline fixture passes. No paid infrastructure or production deployment has
been authorized by this checkpoint.
