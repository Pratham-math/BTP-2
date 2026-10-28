# Complete-platform status

> Python checkpoint validation fix, 28 October 2026: the observed failed lesson
> contained a function-only reference and function calls in stdin, incompatible
> with the runner's complete-program contract. Preparation now performs up to two
> bounded repairs, re-verifies/re-tests the repaired private checkpoint and preserves
> objective/variant/kind. References and supplied alternatives must pass all tests;
> accepted known-wrong programs trigger repair. Expected answers are no longer
> overwritten from generated reference output. The full backend run passed **216
> tests**; the final expanded repair suite passed **8 tests**, including the exact
> function/stdin mismatch and infrastructure-error propagation. The idle generation
> worker was restarted. The failed live job was not automatically retried; no live
> model repair or teaching-quality acceptance is claimed. Frontend was unchanged.

> GPU narration update, 28 October 2026: Piper supports explicit CPU/CUDA
> selection, CUDA/cuDNN DLL preloading and verification of the actual voice
> session. CUDA mode rejects silent CPU fallback. All **210 backend tests**
> passed, including six GPU-path regressions. The local configuration now requests
> CUDA, but the offline checker correctly reports CPU-only ONNX Runtime: manual
> installation is pending. No dependencies or models were downloaded, and GPU
> narration performance is not yet verified. See [LOCAL_GPU_SETUP.md](LOCAL_GPU_SETUP.md).
> Frontend files were unchanged; the preceding 46-test/build evidence still applies.

> Lesson/classroom management update, 28 October 2026: confirmed lesson deletion
> removes lessons from active study and assignments while retaining classroom
> history. Students can leave and voluntarily rejoin; teacher revocation still
> blocks rejoining. Permanent enrollment codes are visible only to the owning
> teacher in classroom Settings; pausing enrollment preserves the code. Lesson
> actions are grouped in card menus, and classroom tabs separate lessons,
> members, progress and settings. Checks passed: **204 backend tests, 46 frontend
> tests, production build**. Migration 005 was applied and rerun successfully on
> local PostgreSQL only. Interaction tests use disposable fixtures; no real
> lessons or memberships were deleted for verification. Browser visual review
> remains unavailable; production release gaps below remain open.

> Adaptive-generation update, 28 October 2026: the old k+2 speculative route could
> be cancelled during advancement or bypassed by a normal clip. Independent study
> now keeps a three-block lead: normal blocks 1–3, assessment k → adapted block
> k+3. A provisional, transparent learning signal drives scaffolding and example
> complexity; queue admission retries during playback, snapshots prevent repeated
> rendering on retakes, and classrooms remain reviewed-only. Core checks passed:
> **198 backend tests, 39 frontend tests, production build**. These are synthetic
> scheduling/provider fixtures and interaction tests, not a live teaching-quality,
> adaptive-metric validity or zero-wait performance benchmark.

> Branding update, 28 October 2026: the user selected **Tinker**. The app, browser
> and API titles, favicon, client package metadata and project documentation now
> use the new name. The implementation plan was renamed and references updated.
> This pass reran all **37 frontend tests**, the API startup regression and the
> production build successfully. The full 188-test backend result below belongs
> to the preceding local-demo implementation checkpoint.

> Local-demo Python update, 28 October 2026: the user authorized trusted Python
> programs on this laptop without Judge0. The ignored local configuration enables
> the explicit demo flag; production/default behavior remains on the separate
> runner path. Correct/incorrect programs, timeout/output bounds, restart recovery,
> loopback rejection and a worker-driven checkpoint passed. An actual configured
> LocalRunner sample also passed. Core checks: **188 backend tests, 37 frontend
> tests, production build**. This mode is explicitly unisolated and is not release
> security evidence. The earlier separate-host blocker still applies to shared use.

> Theme update, 28 October 2026: persistent dark/light mode, system preference,
> early refresh initialization, cross-tab synchronization and themed Python editor
> are implemented. All core checks passed: **183 backend tests, 37 frontend tests,
> production build**. The running app serves the theme bootstrap as JavaScript.

> Workspace/ETA update, 28 October 2026: private independent-study resume/search,
> student assignment resume and progress, teacher classroom sections, optional
> assignment deadlines and advisory generation-time ranges are implemented.
> Core checks passed: **183 backend tests, 32 frontend tests, production build**.
> ETA initial ranges are rough; clean comparable per-user worker timings refine
> them after three samples. Queue waiting is excluded, and paused/recovered/
> overrun jobs do not get a false countdown. This is fixture evidence, not a live
> generation benchmark. The earlier browser-helper limitation still applies.

> Source-workflow update, 28 October 2026: guided intake with staged uploads,
> search/status filtering, multi-source selection, title editing and section-based
> review are implemented. The required checks passed: **173 backend tests,
> 26 frontend tests, production build**. The desktop/browser helper was unavailable,
> so this pass has component interaction tests rather than a visual browser review.
> The runner setup guide and read-only checker are available; the local checker
> reports missing configuration, and no separate runner or live grading is claimed.

> Source update, 28 October 2026: source-library/preview removal and attachment
> removal are implemented. Configured local YouTube extraction now feeds the
> source-review and independent lesson-planning flow. All core checks passed:
> **168 backend tests, 21 frontend tests, production build**. YouTube tests use
> provider fixtures; no live video extraction or model-quality claim is made.
> Sources referenced by active lessons or pending preparation cannot be deleted.
> Existing release blockers below remain open.

> Current update, 27 October 2026: the local app is running, the full checks
> passed (155 backend, 16 frontend and production build), and Python grading is
> blocked pending a verified separate runner. The current project review found
> an answer-key exposure and other release blockers. See
> [PROJECT_ANALYSIS_2026-10-27.md](PROJECT_ANALYSIS_2026-10-27.md). The detailed
> tables below retain their historical 25 October scope and evidence.

Reviewed: 25 October 2026. Governing specification:
[Tinker_Complete_Platform_Implementation_Plan.md](<Tinker_Complete_Platform_Implementation_Plan.md>).
The user approved the expanded scope on 22 October. Remaining services require
guided setup. The budget remains free-only and no separate runner host is available.

**This is an implementation checkpoint, not a complete or deployed release.**
Local automated checks pass. Live accounts/generation/playback and the full
acceptance matrix remain open. Missing services are not replaced with fake
production behavior. Historical MVP reviews do not approve platform content.

## Final verification

Core checks were rerun on 25 October for this publication checkpoint. Database,
browser, security-advisor and live recovery rows retain the earlier 24 October
evidence; those external checks were not repeated by this documentation pass.

| Check | Result and evidence |
| --- | --- |
| Full Python suite | **142 passed, 0 failed, 0 skipped** in 52.31 seconds on 25 October; `.run/platform-test-results-final.xml` |
| Actual media execution | Manim/FFmpeg render, changing frames, H.264/AAC, duration/decode checks and semantic code trace passed; synthetic audio only |
| Visual QA | Stable trace state inspected in `.run/semantic-code-trace-final-qa.png`; logged-out app inspected in browser |
| Frontend | `npm test`: 15 auth/account/source-preview tests passed; production `npm run build` passed; locked dependencies |
| JavaScript advisories | `npm audit --audit-level=high`: zero vulnerabilities at this check |
| Python compatibility | `uv pip check`: all 87 installed packages compatible; compileall passed |
| Real PostgreSQL | TLS/hostname validation and restricted application/session-function access passed; `.run/platform-readiness.json` |
| Real queue recovery | SKIP LOCKED, expired-lease fencing, stale-publication rejection and persisted-stage reuse passed; `.run/postgres-verification.json` |
| Database security | All 18 application tables have RLS; browser cannot read keys or execute the session checker; backend can; security advisor returned no lints |
| Live local HTTP | Page/health 200, readiness 503 as expected, unsigned account access 401, old MVP route 404, unexpected mutation origin 403 |
| Frontend secret check | Configured backend database URL absent from built assets; other service secrets are unset |
| Publication source check | Configured server-secret values and common private-key/Google/GitHub token patterns absent from the publishable source set; updated handoff/setup links resolve |
| Deployment packaging | API/worker/grader/maintenance definitions exist; Docker CLI is present, but updated image/Compose/isolation runtime acceptance remains unverified |

One warning remains: Starlette deprecates its current httpx-based test-client
adapter in favor of httpx2. It does not fail the suite. No library was replaced
just to silence the warning.

The first retry hit inaccessible Windows pytest temp/cache directories (96
passed, 46 setup errors). `scripts/checks.ps1` now creates a unique directory
under ignored `.run` for each test run. The fresh full run above passed without
changing permissions on the old directories or weakening the tests.

Disposable PostgreSQL test rows were removed after verification. Test claims
are restricted to their newly generated fixture owner; no real jobs were claimed
or cancelled. No real user data was deleted, backed up or restored by these tests.

## Implemented and fixture-tested

- Authenticated API separate from the old single-owner server, asymmetric JWT
  validation, live-session lookup, student-default signup, explicit trusted role
  grants, course enrollment/revocation and independent-work isolation.
- Versioned source evidence and author corrections; source uncertainty blocks
  confirmation. Public-video URL allowlisting and isolated document/vision
  adapter boundaries. Unverified input adapters remain feature-disabled.
- Complete objective/prerequisite DAG and per-objective assessment contracts;
  bounded original-evidence audit, author/verifier and repair stages.
- Incremental independently playable normal/recap/reinforced teaching blocks,
  measured utterance cues/captions, safe fixed Manim templates and external-runner
  validation of illustrated code traces.
- Durable scoped PostgreSQL jobs, priorities, leases, fences, stage reuse,
  global/per-user admission and daily model-call accounting. Generation and
  grading have separate dispatch processes. One-step lookahead has an operator
  flag and defaults off until measured.
- Deterministic choice/output grading, isolated Python runner adapter, hints,
  equivalent checks and distinct passed/assisted/unresolved outcomes. Duplicate
  answers are idempotent; stale progress/route writes are rejected.
- Scene/offset resume and debounced account-synced code drafts, retry after
  grading-service failure, explicit relevant recaps, optional prerequisite
  review/rejoin without regrading a previously passed objective, issue reporting.
- Exact-version classroom review, approved-content immutability,
  publish/suspend/assign, fork/edit/revalidate paths, scoped media URLs and reports.
- Operator setup/run scripts, deployment definitions and authenticated encrypted
  application-record/object backup/empty-target restore tooling. Backup tests
  use local disposable databases and object fixtures, not a live recovery drill.

These tests establish specific implementation boundaries, not model accuracy,
universal extraction quality, real OAuth behavior or production capacity.

## Completion work from the latest pass

- Current context/progress now have dedicated handoff files, with the old MVP
  report preserved separately. Provider guidance makes Gemini optional for
  Ollama/Piper text lessons and distinguishes current missing local runtimes
  from historical local demonstrations. Existing `.env` settings were preserved.
- Git and Docker exclusions now cover nested environment-file variants so the
  source publication/image context does not include local service credentials.
- Curriculum construction now has resumable source audits, hierarchical scope
  summaries, namespaced objective batches and per-objective assessment pairs.
  Every original selected section is included or explicitly excluded in a
  validated source-coverage ledger visible before scope confirmation. A
  30-objective/60-checkpoint fixture and an interrupted/restarted plan pass.
- Author/verifier requests receive the relevant original evidence, shared
  notation, prerequisite graph/direct context and previous worked example,
  rather than all unrelated lesson material. Prompt/cache identity is v2.
- Credential-free parser code renders bounded PDF/converted-slide page previews.
  Owner-authorized private image access, correction allowlists and encrypted
  backup/restore include the previews. Native rendering of trusted PDF fixtures
  passed; actual Docker/PPT/OCR source acceptance remains open.
- Account deletion requests require explicit typed confirmation, block access
  immediately, fence preparation, and use a dedicated maintenance queue after a
  two-minute drain and explicit stopped-worker acknowledgments. Cleanup inventories
  exact private prefixes (including unattached uploads), preserves retained keys,
  deletes private objects/local job caches and scrubs
  private records, names/emails and submitted code; classroom completion/grade
  records and shared assets survive under an inactive identifier. Storage and
  Auth failures remain retryable, with separate identity-erasure status. No real
  account deletion was executed. The host-only Auth admin credential is absent.
- `scripts/load_platform.py` implements opt-in protocol viewing/progress/range
  traffic and synchronized checkpoint submissions with p50/p95/failure reports.
  It rejects duplicate identities and keeps tokens/code/signed URLs out of
  reports. Its fixtures do not establish 100-viewer or submission capacity.
- The explicitly selected, already signed-in account received an audited
  administrator grant. No other real account was promoted or changed.
- New access logging strips query strings (including OAuth callback codes), and
  provider URL logging is suppressed. Historical logs were not deleted.

## Fixes from the final pass

- Saved code drafts and retryable grading failures survive refresh.
- Explicit grading retry discards permanently failed runner tokens while keeping
  one attempt; retry locks follow the worker order and avoid waiting on busy jobs.
- Retry admission cannot bypass queue limits. A full preparation queue preserves
  a valid grade and its selected continuation as a recoverable wait.
- Source previews update when asynchronous extraction arrives without discarding
  unsaved corrections or accepting a stale source-version write.
- Manual normal-block revision hashes no longer leak into recap preparation.
- Schema and semantic author repairs share one bounded author-call budget.
- Media state changes reveal promptly and hold steady instead of overlapping
  through an entire utterance; renderer cache identity was updated.
- Platform speech uses separately selected metadata-style narration and the
  current SDK serialization, with quota admission per cloud speech attempt.
- Supabase client is pinned to the installed lockfile version; the PostgreSQL
  skill review informed retry locking, restricted diagnostics and admission fixes.

## Infrastructure still unavailable

| Service | Current state |
| --- | --- |
| Supabase PostgreSQL | Project provisioned under the legacy Supabase name BTP2 with explicit free-only approval; migrations 001–004 applied; restricted login in ignored local `.env`; TLS verified |
| Google OAuth | Provider/redirect checks passed; user confirms real login. Refresh now waits for both session and profile; delayed-profile, token-refresh, account-switch, stale-response, timeout/retry and StrictMode regression tests pass. Live multi-account/logout/revocation acceptance remains pending |
| Private R2 bucket | Not configured; no real signed-range/CORS/media-renewal test |
| AI generation/narration | Ollama/Piper and Gemini paths implemented. Current platform selects Gemini with blank models and no key; Ollama unreachable, Piper/voices absent in current environment. Choose/install/evaluate a route; Gemini is optional for text lessons |
| Image/YouTube interpretation | Current adapter uses Gemini; local multimodal extraction is not implemented. Corrected text can avoid this dependency |
| Judge0-compatible runner | No host, verified isolation or live Python grading |
| Account erasure | Application/maintenance workflow fixture-tested; real Auth admin key, maintenance operation and backup/remote-cache policy still required |
| Document sandbox | Docker CLI present; parser image, running isolation and full source acceptance unverified |
| Deployment | No approved production host, HTTPS domain, alert destination or public release |

No paid upgrade, R2 account, runner, deployment host or cloud billing commitment
was created. Provider keys, database credentials and private answer keys are not
returned by the platform's public configuration endpoint.

## Full-plan acceptance matrix

Every row below remains required for the complete requested release. Local
fixtures are listed honestly rather than promoted to live acceptance.

| Gate | Evidence now | Still required |
| --- | --- | --- |
| Accounts | JWT claim/role fixtures and live DB session-check permissions | Real teacher/student Google login, refresh, logout, session and membership revocation |
| Isolation | Scoped API and key/media-denial fixtures; live RLS/grant check | Real identities, guessed IDs and expired/revoked signed links |
| Core inputs | Typed preview/correction path; bounded PDF parser fixtures | Two reviewed topic/text/PDF-to-complete-lesson journeys |
| Full input breadth | Adapter code and disabled feature flags | PPTX/PPT, scan, handwriting, diagram and public YouTube examples plus malformed cases |
| Extraction quality | Uncertainty/version/indentation checks | Verified code/equations/units/arrows, source locations and diagram/figure treatment |
| 20+ minute lesson | No whole-lesson three-scene or duration cap in contracts | Actually generated, listened-to and reviewed multi-concept lesson |
| 45–60 minute stress lesson | Resumable objective/assessment batching and scoped continuity; 30-objective fixture | Actual multi-batch generated/narrated/reviewed stress lesson and provider context/cost measurements |
| Teaching quality | Independent verifier receives original evidence; bounded repair fixtures | Candidate-model benchmark, release catalog and zero unresolved critical human findings |
| Incremental preparation | First-block admission, manifest and fixed-curriculum APIs | Real first-block start while later media is absent, including restart |
| Adaptation | Five-objective, recap/equivalent, assisted and prerequisite-rejoin fixtures | Real correct/incorrect independent and approved-classroom journeys |
| Cache/lookahead | Scoped dedup/fencing; one-step admission/flag implementation | Actual useful cache hit/miss, wrong prediction, costs and lookahead benefit |
| Waiting/consistency | Revision/idempotency/fallback/queue-full tests | Browser/network/worker-outage acceptance with real media |
| Assessment correctness | Deterministic checks and runner/reference validation adapter | Real reference/alternative/wrong implementation validation for every release key |
| Sandbox | Required limits serialized, unverified host rejected | Actual loop/output/file/network/process/memory/cross-run isolation evidence |
| Classroom review | Exact-fingerprint publication and suspension fixtures | Human review of all reachable clips/keys, publish and assign with real accounts |
| Persistence | API draft/route/attempt resume fixtures | Browser close, auth expiry, stale tabs and second-device resume |
| Media quality | Real rendering and visual sample; synthetic tone only | Full real-narration listening/visual/caption review of normal and remedial paths |
| Recovery | Actual PostgreSQL lease/stage recovery and encrypted restore fixtures | Kill real worker during generation; model/runner outage; live DB/Auth/object restore drill |
| Capacity | Limits, separate queues and opt-in protocol load harness implemented | Actual 100 viewers/20 then 100 submissions, browser timings, p50/p95 and cost/failure report |
| Operations | Setup/runbook/migrations/packaging/backup and requested-erasure workflow | Image builds, HTTPS host, alerts, full restore/erasure drills, orphan-media/remote-cache/backup retention policy and rollback drill |
| User acceptance | No real-user acceptance yet | Teacher assigns and students finish independent/classroom journeys without developer intervention |

## Remaining work is not only credentials

Service setup is the first blocker. Batched planning, requested account erasure
and protocol load tooling now exist, but the full scope still needs more complete
source-figure/OCR interpretation and validation, general orphan-media and remote
cache cleanup, a backup-expiry policy, deployment/monitoring configuration,
reviewed launch content and all live/human acceptance above. There is no approved
free isolated runner host. Do not describe the project as complete while these
items remain open.

## Handoff

- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md): current scope, decisions and provider distinctions.
- [IMPLEMENTATION_PROGRESS.md](IMPLEMENTATION_PROGRESS.md): current implementation progress.
- [LEGACY_MVP_PROGRESS.md](LEGACY_MVP_PROGRESS.md): historical MVP evidence only.
- [PLATFORM_SETUP.md](PLATFORM_SETUP.md): exact variable names and service setup.
- [SERVICE_SETUP.md](SERVICE_SETUP.md): current step-by-step service handoff and free-only runner blocker.
- [OPERATIONS.md](OPERATIONS.md): failure handling, encrypted application backups,
  restore limitations, deletion/retention gaps and release workloads.
- [README.md](README.md): architecture and normal commands.
- Local preview URL: [http://127.0.0.1:8000](http://127.0.0.1:8000). Start the API
  with `scripts/start-platform.ps1`; process liveness is not assumed across
  handoffs. No unconfigured generation/grading worker was started by this pass.
- The current directory has no `.git`. Publish through the existing history of
  `Pratham-math/BTP-2`, preserving remote changes. Do not publish `.env`, local
  runtime/data/test artifacts or generated build output. GitHub publication is
  separate from a deployment or complete release acceptance.
