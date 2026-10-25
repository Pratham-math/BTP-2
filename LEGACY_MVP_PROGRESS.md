# Historical MVP implementation progress

> Historical MVP report. The user superseded this scope on 22 October 2026.
> Current platform implementation and acceptance evidence are tracked in
> [IMPLEMENTATION_PROGRESS.md](IMPLEMENTATION_PROGRESS.md) and
> [PLATFORM_STATUS.md](PLATFORM_STATUS.md); setup is in
> [PLATFORM_SETUP.md](PLATFORM_SETUP.md). Statements below describe only the old MVP.
> Installation claims, process IDs and running-service statements are historical,
> not a description of the current machine. The deferred-scope instructions below
> no longer govern work; follow AGENTS.md and the complete-platform plan.

**Implementation checkpoint, 7 October 2026.** Work resumed after the earlier
user-requested pause. Changes are saved but uncommitted. The user-supplied plan
was not edited. Use this file, `LOCAL_SETUP.md` and `CONTENT_REVIEW.md` for handoff.

Updated: 7 October 2026. Scope: Stages 0–3 of
`Prompt_to_Video_Implementation_Plan.md`; interactive lessons and imports remain
deferred under the project instructions.

## Implemented

- Extracted canonical script models and Gemini text/speech adapters; preserved
  the existing SDK request format and renderer helpers.
- Added Ollama loopback discovery, capability/schema probe, bounded JSON
  outline/scene generation, one repair per invalid unit and saved accepted units.
- Added Piper voice discovery/checksums and one supervised, cached-voice process
  per job, returning measured, validated WAV artifacts.
- Added Local/Cloud presets, backend-host wording, readiness checks, profile
  selection, elapsed time, cancellation, refresh restoration and recovery actions.
- Added versioned non-secret job settings, atomic manifests, input hashes and
  checksums for scripts, audio, animations, narrated clips and final outputs.
- Added measured timing with lead-in/tail, 720p/480p profiles, bounded decode
  verification, single executor/job admission, duplicate-request handling,
  restart interruption, owned process cleanup, data-directory lease and limits.
- Added loopback-only owner settings, control tokens, host/origin restrictions,
  safe validation/provider errors and uncertain Ollama inference recovery.
- Added optional local requirements, launch script, diagnostics and setup guide.
- Recorded ten existing ready jobs in `.run/baseline.json` without private text;
  their narration has not been manually reviewed in this implementation session.

## Verified so far

Client build passed. The final full pytest suite passed: **50 tests**, including all
four actual Manim/FFmpeg templates, provider/admission/security/recovery,
artifact-invalidation, owned-process cancellation and a parent-only Windows
backend-crash test. Two existing Starlette
deprecation warnings remain. `pip check` passed. This run includes the selected
Ollama template grammar, bounded Gemini repair, damaged-manifest handling,
delivery-checksum recovery and actual child-process credential removal. Windows
children now enter a kernel Job Object before running; backend exit closes its
sole handle and terminates the owned tree. Store Python workers launch the real
interpreter image with their virtual environment preserved, bypassing execution
aliases that could escape ownership. No existing Ollama service is attached.

A fresh live Gemini water-cycle job completed in 111 seconds:
`data/d1f44197766c448e88386674104c9b6e/video.mp4` (70.08 seconds, 480p H.264/AAC).
HTTP seeking returned 206 with the requested 1024-byte range; download returned
200 with an attachment filename. A frame was inspected and labels were readable.
The actual narration has not been manually listened to in this session.

Piper 1.4.2 and ONNX Runtime 1.23.2 are installed. The example English voice and
its model card are retained under ignored `.local/voices/`. Two real speech
samples verified at 22,050 Hz with one cached voice process. A saved-script
adapter fixture exported actual Piper narration plus Manim to
`.run/piper-acceptance/piper-scene.mp4` (17.35 seconds, 480p H.264/AAC). This is
**not** a fresh local LLM job or a fully network-disabled acceptance test.

Browser/computer automation reported no available browsers/apps. The user
subsequently confirmed playback, seeking and complete scene narration for the
local HTTP demonstration below. Interactive Settings inspection is unverified.

## Fresh local evidence

Ollama v0.35.1 was downloaded from the official release, verified against its
SHA-256 and extracted under `%LOCALAPPDATA%/PromptToVideo/`, outside OneDrive.
The private service is PID 38352 on loopback port 11434 with `OLLAMA_NO_CLOUD=1`.
Installed Qwen3 tag: `qwen3:4b-q4_K_M`; model digest:
`2bfd38a7daaf4b1037efe517ccb73d1a3bbd4822cf89f1a82be1569050a114e0`.
The owned model was explicitly unloaded at the earlier pause to release memory;
subsequent review runs loaded it again. Use `scripts/start-local-runtime.ps1`
to start the dedicated service again after stopping it.

A fresh three-scene photosynthesis job completed in **79.09 seconds**, with
actual Qwen3 script generation, real Piper narration, Manim and FFmpeg:
`.run/local-acceptance/data/52faf438a5374ca381c5289381c7ce76/video.mp4`.
Its report is `.run/local-acceptance/report.json`; all three scene clips,
audio, measured timing and checksummed final output are saved. A frame was
inspected and labels were readable. The acceptance process removed both cloud
keys, forbade creating a Gemini client and denied external Python sockets;
Piper also denies network calls. **OS networking was not disconnected and
manual listening is still pending.** This is useful local evidence, not a
claim that the full offline release gate passed.

Two earlier local attempts safely failed after one invalid-scene repair. The
saved candidates exposed process node/edge constraints and outline selection
issues. The earlier `local-v4` prompt grounds the model in the schema, applies
the selected template's bounds, requires a limitation for unsupported requests
and supplies short previous-scene summaries.

The complete fixed twelve-prompt script run is saved in
`.run/local-script-review-v4/report.json`: ten supported requests yielded
validated three-scene scripts; two requests correctly stopped with
`UNSUPPORTED_REQUEST` (missing presentation and cinematic output). All nine
requests with a specific supported diagram type matched it in every scene,
covering process/cycle/tree/plot. Eight units used their one allowed repair.
Total script generation time was 217.24 seconds; supported cases ranged from
16.91 to 27.88 seconds. These are observations, not speed promises; some core
checks overlapped. Constant-x meaning and factual accuracy still need review.
The earlier v3 report is retained to show its failures rather than hiding them.
The text/specification review is now recorded in `CONTENT_REVIEW.md`. It found
factual and instructional issues beyond schema validation. `local-v7` adds
plot/constant-x, explicit fitted-line, example-continuity, animal-hierarchy and
tree-height guidance. It also retains the corrected cyclic-stage constraints.
Saved settings are reconciled to the actual provider template version before
checking script reuse; older versions regenerate text. Identical accepted text
or visuals can still reuse matching downstream artifacts.

The final fixed twelve-prompt `local-v7` run saved ten valid supported scripts
and two correct limitation responses in `.run/local-script-review-v7/report.json`.
All explicit diagram types matched. Five units required repair; total text time
was **355.27 seconds**, supported cases **25.74–45.72 seconds**. Temperature
coordinates were preserved; constant-x plots and fitted-line flags improved.
The agent review still found inaccurate photosynthesis/classification wording,
water-cycle imprecision and causal/efficiency overstatements. Content quality
therefore remains an outstanding release gate; see `CONTENT_REVIEW.md`.

Hardware observed: Windows 11 Home, 15.3 GB physical RAM, RTX 4060 Laptop GPU
with 8 GB VRAM. During the warm run only about 0.83 GB system RAM remained free
and GPU usage was about 4 GB; these are individual observations, not peak
measurements or a supported minimum. No unrelated applications were stopped.
During the final review a sampled free RAM reading was 1.34 GB, with 5,589 MiB
GPU memory in use and 96% GPU utilization. This is not a measured process peak.

## Live HTTP restart/resume and human review

The first HTTP local attempt, `f28d171a513e43bc8b4712d4526fe5e4`, stopped safely
after one scene-3 repair because the cycle included an external Sun node and
incorrect closure. That failure prompted the cyclic-stage guidance.

Job `e3f16117f978454c924e7f86b61849f4` then generated real Qwen3/Piper output
through FastAPI. A controlled backend tree stop occurred after scene 1 was
complete. Startup marked the job interrupted; retry completed in **16.52 seconds**
with unchanged hashes for script, all three WAVs, scene-1 clip and silent render.
The result is **43.47 seconds, 720p/24 fps H.264/AAC**, with successful bounded
decode, HTTP range 206 and download 200 checks. Health/status remained responsive.
The user confirmed playback/seek and complete narration, including scene endings.
Evidence: `.run/live-api-acceptance/e3f16117f978454c924e7f86b61849f4.report.json`.
This earlier run used a tree-kill command, separate from the new native
parent-death guard; its stronger live acceptance is recorded below.

The native guard then passed a fresh HTTP job with actual local text/speech:
`2e6f5118d04b403eb17713339cef9356` using `local-v7`. The acceptance-only backend
had blank cloud keys, prohibited Gemini client creation and denied external
Python socket/DNS requests; the separate owned Ollama service had no-cloud mode.
At **57.05 seconds**, during rendering scene 2, only the backend PID was killed.
Both observed render descendants exited automatically. Ollama was left running.
Startup marked the job interrupted, and retry completed in **35.97 seconds**.
Script, three WAVs, scene-1 clip and silent render hashes were all unchanged.
Final output: **39.67 seconds, 720p/24 fps H.264/AAC**, 683,024 bytes. Decode,
range 206 and download 200 passed. Maximum sampled health/status latencies were
125/32 ms. Evidence:
`.run/live-api-acceptance/2e6f5118d04b403eb17713339cef9356.report.json`.
OS networking remained connected; this specific latest output is not manually
listened to. The earlier local demonstration has the user's listening approval.

The normal backend was restored with one loopback worker and
`--no-proxy-headers`, using the existing `.env` for Cloud API mode. Logs:
`.run/backend-20261007-final.{out,err}.log`. No job is active. Refresh the browser
after this restart to obtain the new control token.
Final health/frontend returned 200, both local demonstration jobs remained ready,
and range delivery still passed after restoring the normal server. Wrapper/server
PIDs are 3288/5508. Backend logs were scanned against actual configured cloud
keys without printing them; none were present. The exclusively owned private
Qwen3 model was unloaded (`done_reason=unload`, zero resident models), while the
Ollama service remains available. First-use model loading will occur on demand.

## Remaining release evidence

Do not report a fully local release as accepted until a fresh OS-network-disabled
three-scene job succeeds with no cloud key. The local demonstration's listening,
playback and seek were confirmed by the user; download/ranges were checked over
HTTP. A second demonstration review is pending. The twelve scripts have an agent
text/specification review, with unresolved content quality findings documented.

Repeat core checks only after further code changes. Keep later interactive
lessons, quizzes, uploads, accounts, databases and worker frameworks deferred.
