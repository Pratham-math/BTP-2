# Implementation progress

Updated: 28 October 2026. The governing specification is
[Tinker_Complete_Platform_Implementation_Plan.md](<Tinker_Complete_Platform_Implementation_Plan.md>).
The user explicitly approved this scope in place of the original video MVP.

**The current build is an implementation checkpoint, not a completed release.**
See [PLATFORM_STATUS.md](PLATFORM_STATUS.md) for detailed evidence and the full
acceptance matrix, and [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) for handoff.
The current code and local-runtime review, including newly identified critical
issues, is in [PROJECT_ANALYSIS_2026-10-27.md](PROJECT_ANALYSIS_2026-10-27.md).

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

- Added confirmed lesson deletion from card/detail options, scoped job fencing
  and hidden retired lessons/sessions/reports. Classroom assessment history is
  retained and identified as archived; independent source material is separate.
- Added voluntary classroom leaving and progress-preserving rejoining, while
  retaining teacher revocation rules. Permanent teacher-only enrollment codes
  replace rotation; pausing/reopening enrollment preserves the code and legacy
  invitations remain valid. Local migration 005 applied and rerun successfully.
- Consolidated destructive controls in option menus/native confirmation dialogs,
  moved enrollment to Settings with a roster invite shortcut, aligned card actions
  and reduced the independent-study onboarding banner once lessons exist.

- Replaced the ineffective k+2 speculative adaptation with the user-requested
  three-block rolling lead. Normal blocks 1–3 prepare first; assessment k queues
  an adapted block k+3 while intervening blocks play. Committed background work
  survives route changes, and adapted continuations cannot be silently bypassed.
- Added a provisional understanding metric, frozen teaching-plan snapshots,
  difficulty/scaffolding instructions for author/verifier calls, persisted block
  metadata and a learner-facing explanation of the signal. Fixed curriculum and
  checkpoint contracts remain intact; classrooms remain reviewed-only.
- Queue-full plans retry admission during polling/playback without duplicate
  work. Independent bulk preparation is capped to the initial three blocks.

- Renamed project branding to **Tinker**, including sign-in/sidebar marks,
  browser and API titles, favicon, client package metadata and project documents.
  Renamed the complete-platform plan and updated its references. Existing data,
  infrastructure, backup-format and browser-storage identifiers are preserved.

- Added the explicitly user-authorized, opt-in laptop-only Python demo mode.
  API and workers share runner selection, remote clients are denied, and the UI
  and readiness endpoints disclose that it is unisolated. Local subprocesses
  enforce wall/output bounds, clean up their owned process trees and preserve
  grading outcomes for worker recovery. Default/production still require Judge0.

- Added a system-aware, persistent dark/light theme with accessible toggles on
  sign-in and authenticated workspaces, early initialization on refresh, storage
  failure handling and cross-tab synchronization. Workspace, source review,
  classroom, feedback/form and Python-editor surfaces follow the theme.

- Improved independent-study navigation with scoped resume/progress, lesson
  search/readiness filters, source/topic entry points and visible recovery jobs.
- Added searchable classroom lists, student assignment resume/status/due dates,
  teacher sections for drafts/review, members and course progress, optional
  assignment due dates, membership-revocation confirmation and invite-code copy.
- Added server-calculated advisory generation ETA ranges to job detail, workspace
  preparation cards and lesson paths. Worker timing metadata survives completed
  jobs without being exposed as raw result data. Estimates learn from comparable
  clean per-user runs; initial ranges are labelled and paused, recovered or
  overrun jobs avoid false countdowns. No schema migration or provider change.

- Redesigned source intake, library organization and review into one guided
  workflow: staged upload/removal, search/status filters, extraction-failure
  visibility, private title edits, warning progress, preserved corrections and
  confirmed-source selection for combined lessons. Summary reads batch versions
  and job states without exposing source text.
- Added a separate-host Python-runner setup guide and read-only configuration
  checker. It discovers Python language IDs and checks authentication/network/
  limit configuration; it neither executes learner code nor certifies isolation.

- Added confirmed source removal in the library and preview, removable file
  attachments before lesson submission, and deletion protection for sources used
  by pending lesson jobs or active lessons (including forks by another owner).
- Connected local YouTube extraction when configured: watch/share/mobile/Shorts/
  live/embed URL validation and canonicalization, derived-note provenance,
  original-video link, uncertainty confirmation and confirmed-source lesson
  planning. Optional `PLATFORM_VISION_MODEL` keeps extraction model selection
  separate from Ollama. Live YouTube provider access has not been tested.

- A local PostgreSQL database and frontend were set up, and the API and
  generation/grading workers were started on loopback. Piper and FFmpeg passed
  local execution checks. The app now selects the isolated-runner adapter in
  the local profile and reports the missing runner instead of executing learner
  code on the host. An isolated test confirmed this behavior.
- Project analysis reproduced an independent-student answer-key exposure and
  identified verification, source handling, local erasure and review-version
  gaps. These findings remain open; see the analysis report.
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

GPU narration follow-up: 210 backend tests passed. Added explicit Piper CUDA selection, safe missing-runtime
errors, actual-session verification and an offline inference checker. The local
setting requests CUDA, but installation is pending the user; no downloads were
performed. See [LOCAL_GPU_SETUP.md](LOCAL_GPU_SETUP.md).

The latest 28 October run passed 204 backend tests, 46 frontend tests and the
production client build. Exact latest results and limitations belong
in [PLATFORM_STATUS.md](PLATFORM_STATUS.md). Run all three with:

```powershell
.\scripts\checks.ps1
```

Render fixtures use synthetic audio. They do not prove live narration quality,
full source extraction, classroom acceptance or production capacity.

## Still open

- Evaluate the AI route. The local profile currently selects Gemini text and
  Piper narration; a real Piper sample passed, but a full lesson has not. The
  Ollama and `qwen3:4b-q4_K_M` are installed and passed a small local schema
  check; a full teaching-quality evaluation remains open. Gemini is optional for
  text-based lessons; current image/YouTube extraction uses the Gemini adapter.
- Configure private object storage and verify signed playback/ranges/CORS.
- Obtain a separately isolated Python runner. The budget is free-only, and no
  separate server or suitable managed allocation has been established.
- Complete source-figure/OCR validation, general orphan/remote-cache cleanup,
  backup expiry, deployment/monitoring and the live/human acceptance matrix.
- Configure and exercise maintenance/Auth erasure and a real restore drill.

Do not mark any item complete because a credential exists, a flag is enabled or
an offline fixture passes. No paid infrastructure or production deployment has
been authorized by this checkpoint.
