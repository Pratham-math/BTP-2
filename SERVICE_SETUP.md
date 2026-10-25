# Service setup — current handoff

No paid plan, runner host or cloud subscription has been purchased. Keep secrets
in the existing ignored `.env`, never in chat, frontend files or screenshots.
Do not copy `.env.example` over the database credentials already configured.

## 1. Choose local AI or Gemini

Gemini is optional for text-based lessons. Ollama author/verification calls and
Piper narration are already implemented. Selecting a provider does not install
its runtime, download models/voices or establish teaching quality. Storage and
the separately isolated Python runner are needed independently of this choice.

### Local route: Ollama and Piper

1. Install Ollama and the optional `requirements-local.txt` dependencies in the
   project's Python environment. Install the intended model and Piper voice
   explicitly. [LOCAL_SETUP.md](LOCAL_SETUP.md) contains the download/runtime
   instructions; its video-server UI instructions belong to the historical MVP.
   For a uv-created environment without pip, use:

   ```powershell
   uv pip install --python .venv/Scripts/python.exe -r requirements-local.txt
   ```

2. Keep Ollama on loopback and configure no-cloud mode in the Ollama service's
   environment. `scripts/start-local-runtime.ps1` can start an installed dedicated
   runtime; it does not download the runtime/model and refuses an occupied port.
3. Select the local providers in the existing `.env`:

   ```dotenv
   PLATFORM_TEXT_PROVIDER=ollama
   PLATFORM_TEXT_MODEL=
   PLATFORM_VERIFIER_MODEL=
   PLATFORM_SPEECH_PROVIDER=piper
   PIPER_VOICE=en_US-lessac-medium
   PIPER_VOICES_DIR=./.local/voices
   ```

4. Benchmark installed model candidates, then fill the two blank model IDs with
   their evaluated Ollama tags. The legacy `OLLAMA_MODEL` value does not fill
   these platform settings. Verify the voice model/configuration and actual
   narration. `PLATFORM_SPEECH_MODEL` and `GEMINI_API_KEY` are unnecessary for
   local text generation and Piper narration.
5. Restart the API and configured workers, then exercise real sourced lessons,
   verifier failures/repairs and listening/caption quality. Passing readiness
   configuration checks alone does not complete these tests.

The read-only check on 25 October found the local Ollama endpoint unreachable,
no Piper package in the current virtual environment and no valid voice files.
The existing Qwen3 setting and historical MVP demonstrations do not establish
current installation or full-platform acceptance. No provider was switched by
the documentation update.

Current image/YouTube extraction uses the Gemini adapter. A fully local route
can start with corrected text; full local multimodal extraction is not
implemented. Keep the unverified extraction flags disabled.

### Cloud route: Gemini, if selected

1. Open [AI Studio API keys](https://aistudio.google.com/apikey). Sign in yourself.
2. Select/create the intended Google Cloud project and create a Gemini API key.
   Confirm its actual account eligibility and free quota; do not enable a paid
   plan to bypass a quota failure. Restrict the key to the Gemini API where the
   console supports it. [Google's key guide](https://ai.google.dev/gemini-api/docs/api-key)
3. Replace only `GEMINI_API_KEY` in the local `.env` with the real value and
   explicitly select `PLATFORM_TEXT_PROVIDER=gemini` and
   `PLATFORM_SPEECH_PROVIDER=gemini` for cloud text and narration.
4. Tell the developer the key is saved, without sending its value. Model access,
   current free eligibility, structured output and narration still need testing.
   `PLATFORM_TEXT_MODEL`, `PLATFORM_VERIFIER_MODEL` and `PLATFORM_SPEECH_MODEL`
   remain blank intentionally until that evaluation; a key alone is not readiness.

Use non-confidential CSE examples for free-tier evaluation. Review the actual
provider data-use terms before sending student/college material. Do not assume
that Google sign-in or a Gemini chat subscription grants API quota.

## 2. Cloudflare R2: private media and sources

Following [Cloudflare's S3 setup](https://developers.cloudflare.com/r2/get-started/s3/):

1. Open Cloudflare Dashboard → R2 Object Storage. Check the account activation,
   billing and current [allowances](https://developers.cloudflare.com/r2/pricing/).
   Billing details are not permission to spend; usage beyond an allowance may be
   billable. Stop rather than accepting a paid upgrade or unexpected commitment.
2. Create a **Standard, private** bucket such as `btp2-private`. Keep public
   development URLs and public custom domains disabled.
3. Create an R2 S3 API token with **Object Read & Write**, scoped only to that
   bucket. Copy its Access Key ID and Secret Access Key directly into `.env`.
   A general Cloudflare API bearer token is not the S3 secret key.
4. Save these exact settings locally:

   ```dotenv
   S3_ENDPOINT_URL=https://YOUR_ACCOUNT_ID.r2.cloudflarestorage.com
   S3_BUCKET=YOUR_PRIVATE_BUCKET
   S3_ACCESS_KEY_ID=YOUR_ACCESS_KEY_ID
   S3_SECRET_ACCESS_KEY=YOUR_SECRET_ACCESS_KEY
   ```

5. In the bucket's CORS settings, apply `deploy/r2-cors.json` after checking its
   exact local origins. Add a production origin only when chosen. See
   [Cloudflare CORS guidance](https://developers.cloudflare.com/r2/buckets/cors/).
6. After credentials are saved, test private upload/download, unsigned denial,
   signed ranges, captions, URL renewal and revoked-account access. Merely
   creating a bucket does not pass these gates.

## 3. Python runner: blocked under the current resource choice

The user chose free-only and has no separate Linux VM/server. Judge0's current
[shared-cloud page](https://judge0.com/) advertises paid plans; no suitable free
production allocation or isolated host has been established. Do not subscribe,
use the public demo for student submissions, or run learner programs in the API,
renderer or document parser as a shortcut.

To unblock this part, obtain an institution-provided isolated Linux host or an
explicitly approved managed allocation. Then verify the actual Python language
ID/version and host-enforced CPU, wall-time, memory, process, file, network/DNS
and cross-run isolation limits before setting:

```dotenv
JUDGE0_URL=https://YOUR_APPROVED_RUNNER
JUDGE0_TOKEN=HOST_ISSUED_TOKEN
JUDGE0_PYTHON_LANGUAGE_ID=VERIFIED_NUMERIC_ID
JUDGE0_ISOLATION_VERIFIED=false
```

The current adapter uses `X-Auth-Token`. A gateway needing different headers
requires explicit integration and tests; do not paste an unrelated gateway key
into this field and claim it works. Keep verification false until evidence from
the real host passes. See `OPERATIONS.md` for the acceptance cases.

## 4. Account erasure and maintenance

The user's chosen policy is to delete private study and remove profile names/
emails while retaining classroom records under an inactive anonymous identifier.
Classroom teaching materials already referenced by retained versions survive.

- Account → Request deletion requires typing `DELETE`; it immediately disables
  app access and queues a durable maintenance job. No account was deleted during
  implementation. The sole administrator cannot erase their account first.
- Run `scripts/start-platform.ps1 -Maintenance` on the shared worker-cache host.
  Claims wait two minutes and require stopped-worker acknowledgments; a missing
  acknowledgment blocks deletion rather than racing a still-running upload.
- Supabase identity removal needs `SUPABASE_AUTH_ADMIN_KEY`, configured only for
  the maintenance process. This privileged key is not currently present. Do not
  create or copy it into chat. Follow the operator's Supabase security process;
  never give it to the frontend, parser or learner-code runner.
- Missing credentials or failed storage/Auth calls leave an explicit blocked/
  failed cleanup. A different active administrator can inspect and retry it in
  Account. Neither the initial receipt nor private-data cleanup means the Auth
  identity and every backup copy are already erased.
- All generation/grading workers must use the declared shared cache. Copies on
  other hosts, orphan uploads and backup expiry require the operator's retention
  and cleanup policy; automatic general garbage collection is not yet enabled.

The initial app administrator was granted to the existing account explicitly
selected by the user. Refresh after the role change. Teacher access can then be
granted only to intended, already signed-in identities.

## 5. After configuration

Restart the API and configured workers; settings are loaded at process start.
`/api/ready` reports configuration/database checks, not complete release acceptance.
Do not enable input, isolation or lookahead verification flags simply to turn a
status green. Production hosting, real model/voice/content review, multi-account
journeys, browser playback, load, restore and the full plan's release gates remain.
