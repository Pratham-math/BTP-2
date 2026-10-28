# Project working instructions

Implement `Tinker_Complete_Platform_Implementation_Plan.md`. The user confirmed
on 22 October 2026 that it supersedes the old MVP-only restrictions. Keep React,
FastAPI, provider adapters and the safe Manim/FFmpeg renderer. Add authenticated
independent study and classrooms, source ingestion, versioned curricula,
checkpoints, isolated Python grading, durable jobs and persistent progress.

The user requested a three-block adaptive lead on 28 October 2026. Independent
study prepares blocks 1–3 normally; assessment k schedules block k+3 in the
background from a frozen, provisional understanding signal. Required objectives
and assessment contracts stay fixed. Classroom routes remain teacher-reviewed.

Keep answer keys, runner tokens, storage credentials and provider keys on the
server. Learner code must run only on a separately isolated runner, except for
the user's 28 October 2026 laptop-only demo authorization: the explicit local
profile plus `PLATFORM_LOCAL_DEMO_PYTHON=true` may execute trusted demo code in
a local subprocess. It is not a secure sandbox or release isolation evidence;
production retains the separate-runner requirement. Private
independent work is never visible to course teachers. Classroom publication
requires review of the exact immutable lesson version and all reachable assets.
Never label development fixtures as generated or human-reviewed release content.
Missing infrastructure must produce actionable readiness errors, not fake success.

Keep the React interface and FastAPI implementation small and explainable.
Never put the Gemini key in frontend code or logs. A synthetic test tone may
verify rendering in offline tests, but it is not evidence of live narration.

Core checks are `.venv\Scripts\python -m pytest -q`, plus `npm test` and
`npm run build` from the `client` directory. `scripts/checks.ps1` runs all three.

Read `PROJECT_CONTEXT.md`, `IMPLEMENTATION_PROGRESS.md` and `PLATFORM_STATUS.md`
for current decisions, progress and acceptance gaps. `LEGACY_MVP_PROGRESS.md`
contains historical evidence, not current scope or installed-runtime status.
Ollama text/verification and Piper narration are implemented alternatives to
Gemini. Do not require a Gemini key for that path or silently change the host's
provider settings. Image/YouTube extraction currently uses the Gemini adapter.
