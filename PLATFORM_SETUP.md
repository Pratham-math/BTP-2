# Platform setup

This is the full-platform entry point, not the old single-owner MVP. Service
configuration is not release acceptance. Track both in PLATFORM_STATUS.md.

## Current workspace

The current build additionally requires `migrations/005_classroom_management.sql`
on its target database for stable enrollment codes and voluntary departures.
It has been applied to local PostgreSQL; the previously provisioned remote
Supabase project has not been migrated by this local-demo update.

For guided remaining-service setup, start with [SERVICE_SETUP.md](SERVICE_SETUP.md).
The user's chosen existing account now has an audited administrator grant.
Free-only operation is still required; no separate runner server is available.

- Existing Supabase project (legacy name **BTP2**), ref `psemolfpnygfbngkjtuk`, in Mumbai, was created
  with explicit permission after Supabase quoted $0. No paid upgrade was made.
- Migrations 001–004 are applied. The restricted `btp2_app` login is saved only
  in ignored `.env`. Its temporary bootstrap credential table was removed.
- The session-pooler host supplied by the user is
  `aws-0-ap-south-1.pooler.supabase.com`, port 5432. Its username includes the
  project suffix: `btp2_app.psemolfpnygfbngkjtuk`. Do not replace it with the
  non-resolving direct endpoint or disable TLS verification.
- The public CA is `.local/supabase-ca.crt`; the connection uses `verify-full`.
- Google OAuth's provider and redirect configuration pass checks; the user
  confirms real login works. Session/profile restoration is regression-tested;
  live logout and revocation acceptance remain pending. R2 and Judge0 are absent.
  Platform generation is unconfigured: Gemini is currently selected with blank
  model IDs, but Ollama/Piper are implemented alternatives for text lessons.
  On 25 October, Ollama was unreachable and Piper/voices were absent from this
  environment. Docker's CLI is present; parser-image/isolation acceptance is open.
- CPython 3.12 `.venv`, client dependencies and a verified FFmpeg download are
  already present. The repository files are in this directory, but `.git` is
  currently absent. Publishing must preserve the existing GitHub history;
  see [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md). No production deployment exists.

Do not overwrite `.env` with `.env.example`. Add missing values by editing the
local file, never by pasting secrets into chat. Restart all three processes
after changing it. Environment settings are loaded at process startup.

## Dependencies on another machine

Use CPython 3.12, Node.js 22, and FFmpeg/ffprobe with H.264/AAC support. Install
Manim's native Cairo/Pango dependencies on Linux; the worker Dockerfile includes
them. From a fresh checkout only:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-platform.txt
Set-Location client
npm ci
npm run build
Set-Location ..
```

If this virtual environment was created by `uv` and has no pip, use
`uv pip install --python .venv/Scripts/python.exe -r requirements-platform.txt`.
Use `requirements-api.txt` only for a separate lightweight API host. Do not run
user document parsers in that service or install a learner-code execution fallback.

## Database

Reuse the existing project. For a separate new environment, an operator applies
`migrations/001_platform.sql` through `004_session_check.sql` in order using the
Supabase SQL editor or a privileged migration connection. These are initial
migrations, not an idempotent script to rerun against populated tables. Review
and back up before future schema changes. Never give the API permission to
create databases, roles or tables.

The backend role needs only application DML and execute permission on the
minimal `btp2_session_active` function. Browser roles have no direct table
access. The function returns only a session-validity boolean, not Auth records.
Use asymmetric Supabase signing keys (ES256/RS256); the API deliberately does
not accept a shared HS256 JWT secret.

```powershell
.venv\Scripts\python scripts/check_platform.py --database-only
```

## Google sign-in — first manual setup

Open [the Tinker dashboard](https://supabase.com/dashboard/project/psemolfpnygfbngkjtuk).
Following [Supabase's Google guide](https://supabase.com/docs/guides/auth/social-login/auth-google):

1. In your Google Cloud project, configure the consent application's audience
   and a web OAuth client. Use only the identity scopes required by Supabase.
2. Register the provider callback
   `https://psemolfpnygfbngkjtuk.supabase.co/auth/v1/callback` with Google.
3. Enter that client's ID and secret in Supabase Auth → Providers → Google,
   then enable the provider. The secret belongs there, not in frontend code.
4. Add your app URL and exact `/auth/callback` redirect to Supabase's Auth URL
   configuration. Locally use `http://127.0.0.1:8000` consistently; do not mix it
   with `localhost` during a PKCE flow. Add production HTTPS redirects later.
5. Set `GOOGLE_OAUTH_VERIFIED=true` for a controlled operator login test, restart
   the API, then test a real account, logout, refresh and rejected old sessions.
   Reset the flag if the test fails. Do not open enrollment on a flag alone.

New accounts always start as students. After an intended teacher has signed in,
an authorized host operator can grant a role explicitly:

```powershell
.venv\Scripts\python scripts/manage_platform.py grant-role USER_UUID teacher --reason "Approved course instructor"
```

The CLI records an audit event. Never expose it as a signup role selector. The
same operator command can bootstrap an administrator. Password signup/recovery
is not implemented or advertised; Google is the only configured identity path.

## Private R2 storage

Create a private bucket only after checking the account's actual billing and
limits; no bucket or billing account was provisioned by this implementation.
Use bucket-scoped object credentials in `S3_ENDPOINT_URL`, `S3_BUCKET`,
`S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY`.

Keep public access disabled. Adapt `deploy/r2-cors.json` to the exact app
origins. Browser playback uses short-lived signed GET URLs, so test CORS and
`Range` requests, not just a server download. See
[Cloudflare's signed-URL CORS guidance](https://developers.cloudflare.com/r2/buckets/cors/).
Verify a valid signed request returns partial content, an unsigned request
fails, captions load, URLs renew and revoked users cannot get fresh links.
Previously issued links remain usable for at most their five-minute lifetime.

## Generation and narration

Choose the text and narration providers explicitly. Gemini is optional for
Ollama/Piper text-based lessons; follow the two routes in
[SERVICE_SETUP.md](SERVICE_SETUP.md). For Gemini, set `GEMINI_API_KEY` locally.
Benchmark candidate models against the same sourced CSE examples before
pinning `PLATFORM_TEXT_MODEL` and `PLATFORM_VERIFIER_MODEL`.

For YouTube extraction, add a public video in the Source library, inspect its
timestamped derived notes against the video, clear corrected uncertainty flags,
then confirm and choose **Use in a lesson**. The adapter uses Gemini, even when
text lessons use Ollama. Set the server-only `GEMINI_API_KEY` and optionally
`PLATFORM_VISION_MODEL`; the extraction model otherwise defaults to
`PLATFORM_TEXT_MODEL` only when the text provider is Gemini. Local mode exposes
YouTube when these are configured. Production additionally requires
`PLATFORM_ENABLE_YOUTUBE_SOURCES=true` after acceptance. Videos longer than one
hour require explicit transcript batches. Inaccessible videos require a permitted
transcript or source file. No automatic provider switch or paid service setup is
performed. Implementation follows the
[Gemini video-input documentation](https://ai.google.dev/gemini-api/docs/video-understanding).
No author/verifier is selected by default and no live quality benchmark passed.

For cloud speech, set `PLATFORM_SPEECH_PROVIDER=gemini` and pin
`PLATFORM_SPEECH_MODEL` after testing account access, quota and full listening
quality. The platform uses the metadata-style Interactions speech request so
delivery directions are not narrated as lesson text. SDK 2.25.0 and its request
serialization have fixture coverage, not live narration acceptance. Compare the
selected model with [Google's current speech documentation](https://ai.google.dev/gemini-api/docs/speech-generation).
The old MVP's `GEMINI_TTS_MODEL` is not the platform's speech selection.

An explicitly selected local path uses `PLATFORM_TEXT_PROVIDER=ollama` and
`PLATFORM_SPEECH_PROVIDER=piper`; install the intended model and voice first.
Set the two platform model IDs explicitly; legacy `OLLAMA_MODEL` does not select
the platform's author/verifier. A Gemini key and platform cloud speech model are
unnecessary for this local generation/narration path. Current image/YouTube
extraction still uses Gemini; corrected text can avoid that dependency.
It still requires the same teaching-quality review, database, storage and
separate runner. A local model running successfully is not automatic approval.
There is no silent switch to another provider after a failure.

The rolling 24-hour call limit includes platform text calls and cloud speech
attempts. `MAX_JOBS_PER_USER` and `MAX_QUEUED_JOBS` bound admission. Provider
charges/quotas and rendering capacity still need account-specific measurement.
Independent study now uses the explicitly requested three-block rolling pipeline:
blocks 1–3 are normal and assessment k queues adapted block k+3. This committed
preparation is separate from the legacy optional `PLATFORM_SPECULATION_ENABLED`
flag; the flag does not disable the requested rolling pipeline. Admission and
model-call limits still apply. See LOCAL_PLATFORM.md for the metric and timing.

## Isolated Python runner

Follow [PYTHON_RUNNER_SETUP.md](PYTHON_RUNNER_SETUP.md) for the installation,
environment variables, read-only checker and actual-host isolation acceptance.

Set `JUDGE0_URL`, `JUDGE0_TOKEN`, and the actual host's Python language ID in
`JUDGE0_PYTHON_LANGUAGE_ID`. Do not assume an ID from another provider. The host
must be separate from the API/generation machine and reached over HTTPS.

Keep `JUDGE0_ISOLATION_VERIFIED=false` until its administrator verifies CPU/wall
time, memory, process, file/output, disabled network, filesystem and cross-run
isolation on that actual host. Required abuse cases are listed in OPERATIONS.md.
Only then enable the flag and test submissions. See the
[Judge0 API contract](https://ce.judge0.com/) for request fields; sending a limit
does not prove the host enforces it. There is no host-Python or browser-authority
fallback.

## Source-adapter release flags

Typed notes are available. These separate flags default to false:

| Flag | Additional prerequisites before enabling |
| --- | --- |
| `PLATFORM_ENABLE_TOPIC_SOURCES` | Two reviewed topic cases against the initial authoritative Python collection |
| `PLATFORM_ENABLE_DOCUMENT_SOURCES` | Private storage, a verified no-network parser container, PDF/PPTX/PPT acceptance |
| `PLATFORM_ENABLE_VISION_SOURCES` | Private storage, Gemini access, reviewed scans/handwriting/diagram cases |
| `PLATFORM_ENABLE_YOUTUBE_SOURCES` | Public-video interpretation, provenance/timestamp/uncertainty acceptance |

Build the document image with
`docker build -f deploy/Parser.Dockerfile -t btp2-parser:local .` on a controlled
host with Docker running. The build downloads parser/OCR models. Verify it at
runtime with no network, credentials, writable root, capabilities or host
directories beyond its one input and output. Then set
`DOCUMENT_SANDBOX_VERIFIED=true`. Do not mount the Docker socket into the API.
The current Compose worker deliberately keeps that flag false; document
extraction requires the separately verified host worker configuration.

The adapters are implemented but their full-scope extraction and generated-lesson
gates have not passed. Long material may require explicit smaller source units;
the current context limit rejects an oversized unit instead of truncating it.
Cross-batch orchestration and source-figure annotation still need acceptance/work.

## Run locally

Build the client first, then use three terminals at the project root:

```powershell
# Terminal 1: authenticated API + built frontend
.\scripts\start-platform.ps1
# Terminal 2: one heavy generation job at a time
.\scripts\start-platform.ps1 -Worker
# Terminal 3: external-runner submission/polling, independent of video jobs
.\scripts\start-platform.ps1 -Grader
```

Open [the local app](http://127.0.0.1:8000). The scripts locate the downloaded
local FFmpeg automatically. For frontend development, run `npm run dev` in
`client`; the default API proxy uses port 8000. For separate hosting set
`VITE_API_BASE_URL` **at frontend build time** and allow that exact origin in
`PLATFORM_ORIGINS`. Never place secrets in any `VITE_` variable.

Workers require PostgreSQL. Their local cache is disposable; PostgreSQL and
private objects are authoritative. Use one generation worker and one grading
dispatcher initially, each with its separate local runtime lease. Do not start
duplicate workers on different machines until host capacity is measured.

## Verify and deploy

Run `scripts/checks.ps1`, `scripts/check_platform.py`, and the acceptance matrix
in PLATFORM_STATUS.md. `/api/health` is liveness; `/api/ready` reports configured
services and DB reachability, not sandbox enforcement or release acceptance.

`deploy/Api.Dockerfile`, `Worker.Dockerfile`, `Parser.Dockerfile` and
`compose.yaml` are starting host packaging, **not verified deployments**.
The API binds behind a TLS reverse proxy; Compose's host port is loopback-only.
Choose and authorize an actual always-on host, set HTTPS origins and secret
injection, verify container builds, backups and load before public enrollment.
No deployment host, domain, SMTP service or paid resource was created.
