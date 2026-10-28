# Project analysis — 27 October 2026

This is an implementation and local-runtime assessment against
`Tinker_Complete_Platform_Implementation_Plan.md`. Passing automated tests
do not establish release readiness, teaching quality, full source extraction,
live provider quotas, or classroom/user acceptance.

## Current local runtime

- The React/FastAPI app is running on `http://127.0.0.1:8000` with local
  PostgreSQL, a generation worker, and a grading worker. Health returns 200.
- Readiness returns 503 because a separately isolated Python runner is not
  configured. The app's local profile now uses the separate-runner adapter
  instead of the unisolated local subprocess implementation; Python code
  grading and code-trace validation remain unavailable until one is verified.
- The existing environment selects Gemini text and Piper narration. Its
  provider settings were not changed. A real local Piper sample was generated;
  this does not verify a complete lesson or the Gemini account's quota.
- FFmpeg 9.0.2 was installed from the publisher's archive and verified against
  its published checksum. The generation worker was restarted with its path.
- Ollama 0.40.11 and `qwen3:4b-q4_K_M` are installed and running from verified
  downloads. The model passed a small schema-constrained local prompt; this is
  not a full lesson or a teaching-quality benchmark. The active text provider
  remains Gemini.

## Findings, ordered by impact

1. **Independent learners can obtain answer keys.**
   `server/platform_api.py:474` allows an independent lesson owner to call the
   review endpoint and returns assessment `private` keys. A controlled SQLite
   fixture reproduced the issue: the student received the correct answer from
   `/api/reviews/{curriculum_id}`. Existing no-leak tests exercise other routes
   and do not catch this endpoint. Restrict the review endpoint to authorized
   classroom reviewers and keep learner-facing assessment keys server-side.

2. **Local verification can be marked accepted despite critical findings.**
   `server/lessons/authoring.py:129` ignores critical source-audit findings in
   local mode; `:170` can return a rejected draft after repair. At
   `server/worker/tasks.py:195` the persisted block is marked `accepted: true`
   regardless of the verifier result. Local assessment findings are similarly
   bypassed at `server/worker/tasks.py:78`, and assessments are stored as
   validated at `:118`. `publication_ready` checks the accepted flag, so this
   undermines the intended verification gate. Require an accepted verification
   or a clearly blocked review state before exposing or approving content.

3. **Quick lessons bypass source and curriculum confirmation.**
   `server/worker/tasks.py:356` automatically discards evidence blocks with
   uncertainty, creates a confirmed source version, and confirms the curriculum
   before an author reviews them. Skipped sections are reported only in the job
   result. This conflicts with the plan's correction and coverage contract;
   pause for explicit source/scope confirmation and preserve uncertainty.

4. **Local document parsing is not an OS isolation boundary.**
   `server/local_services.py:194` starts a separate interpreter, and
   `server/ingestion/local_parse.py:13` replaces Python socket functions. This
   does not enforce filesystem, process, memory, or native-code network
   isolation. The local feature configuration advertises document support
   without the verified container gate. The parser also removes figure
   uncertainty at `server/ingestion/local_parse.py:25`. Treat document parsing
   as unverified until an actual isolated parser and source review are in place.

5. **Local account erasure is incomplete.**
   Local identities are stored in `local_credentials` (`server/database.py:34`),
   but the erasure workflow does not remove them and always calls Supabase Auth
   (`server/erasure.py:190` and `:243`). Thus a local login identifier and
   password hash can remain, and the job blocks on unrelated Supabase admin
   configuration. The maintenance worker is also not started by the local
   launcher. Implement and test local credential deletion and the chosen
   classroom-retention policy before claiming complete erasure.

6. **A classroom review does not freeze the browser renderer.**
   The publication fingerprint (`server/platform_api.py:104`) includes scripts,
   stored media and assessment keys. In Remotion mode the stored clip is audio
   (`server/lessons/production.py:76`), while the visual is drawn by the current
   frontend (`client/src/player/Player.jsx:136`). Changing deployed renderer
   code can therefore alter a reviewed lesson's visuals without changing its
   fingerprint. Bind reviewed versions to immutable renderer assets or render
   immutable video and review those exact assets.

7. **Local logout does not revoke the issued token.**
   Local tokens last 14 days (`server/local_services.py:60`); logout only removes
   the browser copy (`client/src/platform/auth.jsx:87`). A previously copied
   token remains valid until expiry or account deactivation. Add server-side
   session revocation and test logout and password recovery before shared use.

## Verification and remaining scope

- Backend full suite: **155 passed**, one Starlette/httpx deprecation warning.
- Frontend suite: **16 passed**; the production build passed with a large-chunk
  advisory. The app homepage and health endpoint responded after startup.
- A targeted test confirms the local app does not select the unisolated Python
  runner. An analysis-only fixture separately reproduced the answer-key leak.
- Existing checks cover scoped accounts, lessons, jobs, assessment routing,
  source previews, reviews and erasure fixtures. They do not prove the missing
  real runner, live generated lessons, full narration/playback, input breadth,
  account-recovery flows, load targets, backup restoration, or production
  deployment. The 26 October work report records a prior generation failure;
  no fresh complete lesson has been verified in this setup.

The current context and progress documents were updated for this checkout;
older detailed status tables retain their historical dates. The review findings
above are not fixed by starting the app or by a passing test suite.
