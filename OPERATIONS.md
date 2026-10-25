# Operations and release gates

This runbook describes implementation behavior and required operator drills.
It does not claim that those drills ran on a production host.

## Safety boundaries

- The browser holds a Supabase identity token, never database, R2, runner,
  provider or backup credentials. The API checks scope on every data request.
- Backend RLS permits the restricted application role; tenant authorization is
  still enforced by the API. Do not grant browser roles direct table access.
- Learner Python and model-authored trace examples go only to the verified
  external runner. Manim renders validated data through fixed templates.
- User documents go only to the separately verified, credential-free no-network
  parser container. Missing isolation disables extraction, not its safeguards.
- Classroom material is publishable only after exact-version human approval of
  all required normal/recap media, captions, hints and assessment keys. Fixes to
  approved/started material require a new draft version.
- Local API fixtures, synthetic audio and historical MVP reviews are never
  launch lessons or real-account acceptance evidence.

## Health and failure handling

Use `/api/health` for liveness and `/api/ready` for configuration/database checks.
`scripts/check_platform.py` checks DB access and the provider's public OAuth
setting without printing credentials. Keep its JSON output as private evidence.
Monitor API failures/latency, queue age, expired leases, model-call audit counts,
storage/runner errors, disk/cache use and the vendors' actual quotas. No
production alert destination or recurring monitor has been configured yet.

| Failure | Expected behavior and operator action |
| --- | --- |
| Missing key, model, storage or sandbox | Saved job waits/fails with a safe code; finish configuration, restart processes and retry saved stages |
| Worker killed or lease expires | Jobs remain in PostgreSQL; a new owner increments the fence and reuses matching stages; a stale owner cannot publish |
| Cancel generation | Fence increments; owned child processes stop cooperatively and later remote results cannot publish |
| Cancel/fail grading | Attempt becomes `service_failed`; code survives; no failed-learning evidence is added; retry from the checkpoint |
| Model/content verification fails | Hold for author review; do not auto-publish or weaken checks |
| Uncached next explanation | Show a real wait and optional relevant ready recap; retain the full objective map |
| Runner outage | Ready videos remain independent of it; saved code can be retried when service returns |
| Serious classroom defect | Suspend the version immediately; fresh media access is rejected; publish a reviewed replacement, not a silent edit |
| Revoked membership/account session | API access stops; already issued media links may remain valid for five minutes |

Recovery drills must kill a real generation worker during speech/render/upload,
restart it, inspect persisted stage reuse and check a ready classroom lesson
still plays. Repeat with model/storage/runner outages and browser refresh.
`scripts/check_postgres_transactions.py` uses disposable generated fixture IDs
to test real SKIP LOCKED and fencing, then removes only those fixtures. Its
claims are restricted to that newly created fixture owner, so it cannot claim
or modify real learners' jobs.

## Encrypted application backups

`scripts/platform_backup.py` snapshots all 18 application tables from one
consistent database transaction and can include every referenced original/media
object. AES-256-GCM authenticates each encrypted file. Set `BTP_BACKUP_KEY` from
an independently retained 64-hex-character password-manager key. Keep the key
separate from backup storage and the normal app secret distribution.

This is an **application-only** backup. It does not include Supabase Auth users,
OAuth configuration, DB roles, policies/migrations, infrastructure or the key.
A complete recovery also needs an approved Supabase/Auth backup procedure and
restored identity IDs. Do not call this utility a complete Supabase backup.

Use a fresh private destination (never an existing directory):

```powershell
.venv\Scripts\python scripts/platform_backup.py snapshot E:\PRIVATE_BACKUP\btp2-YYYYMMDD --include-objects
```

Do not use the example path until you have selected a real protected backup
destination. A records-only snapshot preserves object references, not object
bytes; it is insufficient for media recovery. A failed partial directory lacks
the `COMPLETE` marker and is not restorable. Generated backups and decrypted
temporary files contain sensitive material; restrict the backup/temp directory
to the host operator, encrypt its disk, and do not share it through Git or chat.

For an isolated drill, point environment variables to a **different empty
migrated database and a different empty private bucket**, leaving production stopped
or untouched. The restore utility refuses the source DB and any nonempty target;
it never drops/truncates tables. It authenticates a file before using its data.

```powershell
.venv\Scripts\python scripts/platform_backup.py restore E:\PRIVATE_BACKUP\btp2-YYYYMMDD --confirm-empty-restore-target
```

Active jobs are restored stopped for operator review. In-flight grading restores
as a retryable service failure rather than a learner failure. After restoring
Auth identities/configuration, verify teacher/student permissions, source
originals, exact-version media/captions, attempts, code drafts and resumed routes.
Record start/end time, backup age and hashes. The plan's proposed 24-hour RPO and
four-hour recovery target are **unproven** until this full drill passes.

Daily scheduling, off-machine copies, access/expiry policy and production restore
approval still require an owner and user-selected retention policy. No recurring
backup automation was created, and no existing user data was backed up or
deleted by the implementation tests. The encrypted exporter/restore fixtures
test cryptographic tampering and fresh-target safety, not live disaster recovery.

## Data deletion and retention

Implemented: owners can retire a lesson and delete an unused source. Source
deletion removes its original and stored evidence, retaining its ID/audit record.
Referenced lessons must be retired first; active classroom versions are not
silently erased. Backup copies remain until the eventual expiry policy runs.

The Account page now accepts explicitly confirmed deletion requests. Access is
disabled immediately; memberships and enrollment codes are revoked, and active
owned jobs are fenced. A separate `scripts/start-platform.ps1 -Maintenance`
dispatcher claims erasure after a two-minute drain and requires shutdown
acknowledgment from every previously running owned worker. It inventories exact
owner/version storage namespaces, including unattached uploads, preserves shared
classroom keys and deletes private objects/local job caches. It scrubs private sources/lessons/answers and profile
names/emails, and retains anonymized classroom grades/completion and shared
teaching assets. It never runs just because the maintenance process starts.

Supabase identity removal requires the host-only `SUPABASE_AUTH_ADMIN_KEY` in
the maintenance process. The parser/browser/runner must never receive it.
Missing Auth credentials produce `AUTH_ERASURE_NOT_CONFIGURED`, not fake success.
Storage/Auth failures are retryable; administrators inspect/retry requests in
Account. The sole administrator must appoint another active administrator first.
Supabase guidance informed blocking app access before deletion; PostgreSQL
guidance informed per-user mutation serialization and fenced maintenance.

If a crashed/old worker cannot acknowledge shutdown, stop and inspect that exact
process on its host first. Only then may an operator run
`scripts/manage_platform.py confirm-worker-stopped JOB_UUID --confirm-host-process-stopped --reason "Verified stopped on its host"`.
The command refuses jobs not awaited by a disabled-account erasure and audits
the attestation; it does not stop the process or prove isolation itself. Retry
the blocked erasure only after verifying all its worker hosts and cache copies.

All worker caches must be on the declared shared cache host. Other-host copies,
general orphan uploads/media collection and automatic backup expiry remain
operator policy/implementation work. The user selected anonymized classroom
retention, but no backup expiry interval or statutory erasure guarantee was
agreed. No real account or learner data was erased during implementation.

## Runner acceptance

An operator of the actual isolated host must record tests for infinite loops,
output floods, fork/process abuse, oversized memory/allocation, file-size limits,
read/write containment, no network/DNS access and no cross-run state. Use only
disposable exercises on that authorized host. Inspect host enforcement/logs;
an expected HTTP response or failed test alone does not prove isolation.

Then check both reference implementations pass, at least two known-wrong
implementations fail meaningful checks, essential tests cannot be offset by easy
cases, runtime failure differs from runner outage, and identical retries produce
one attempt. Never set `JUDGE0_ISOLATION_VERIFIED=true` merely to hide a setup
error. There is no verified runner or measured submission capacity yet.

## Performance and release evidence

Use actual generated/reviewed content and real authorized test accounts. Prepare
disposable classroom assignments, not private production learner sessions.
Measure cold and warm p50/p95 with failures, host/network conditions, concurrency,
bytes, queueing, model/voice costs and retries. Preserve raw private results with
redacted shareable summaries. Do not infer capacity from fixture tests.

Required workloads include 100 classroom viewers with progress writes and a
shared checkpoint, 20 Python submissions, then a synchronized 100-person burst.
Independent unique generation concurrency is a separate measured limit. Verify
same-scope coalescing, cross-user isolation, wrong speculation, quota admission,
worker outages, expiring media URLs and slow networks.

`scripts/load_platform.py --help` describes the opt-in protocol load harness.
Use a private ignored `.run/` JSON file containing distinct test bearer tokens,
a teacher-approved disposable classroom assignment and a separate private JSON
answer file. Never put tokens or code on the command line or in shared reports.
`--confirm-authorized-test-writes` is required; the harness changes test progress
and can consume provider/storage/runner quota. Do not run it on real students.

Use viewing mode for 100 accounts with `--seconds`, an explicit `--media-host`
allowlist and a new `--output` path. It simulates progress and bounded signed
range traffic without forwarding API credentials to media storage. It is not
browser playback. Add `--answer-file` for a synchronized checkpoint burst after
viewing, or use submissions mode with 20 and then 100 accounts already at the
same checkpoint. Identity and checkpoint mismatch fail closed. Only one attempt
per account is submitted; asynchronous grade time includes polling/queue wait.

Reports include successful and all-request distributions, p50/p95, failures,
HTTP statuses and bytes, never raw account IDs/tokens/answers/signed URLs. Attach
separate browser buffering/gap measurements, queue/cache/cost observation and
actual host conditions. Only the harness's mock fixtures have run; actual live
deployment and load remain unverified.

For each input category, retain at least two cases including malformed/uncertain
material and author corrections. Review all media and checkpoints in a sourced
20+ minute multi-concept lesson, then a 45–60 minute cross-batch stress lesson.
Measure first-block availability separately from full-lesson preparation. A
human teacher must publish/assign and students must finish both real independent
and classroom journeys without developer intervention.

## Deployment and rollback

1. Choose an approved always-on API host, one heavy worker and separate grading
   dispatcher; confirm costs before provisioning. Build/test all images first.
2. Inject host-managed secrets, mount the public CA read-only, enable HTTPS at
   the reverse proxy and exact origins. Never expose the legacy MVP endpoints.
3. Back up before schema changes. Apply additive compatible migrations through
   an operator; the API role does not run migrations.
4. Verify real Google teacher/student accounts, R2 private range/CORS playback,
   model availability, sandbox enforcement and all acceptance rows.
5. Record release source/configuration versions, reviewed curriculum IDs, actual
   supported inputs, load limits, alerts, recovery owner and rollback artifact.
6. On incident, stop new preparation/speculation, preserve ready objects and DB
   records, suspend defective content, and roll back compatible application code.
   Do not reset the database or mutate pinned curriculum/assessment content.

No production host or release artifact is currently deployed. See the status
matrix for unfinished code paths as well as external blockers.
