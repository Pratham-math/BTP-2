# Configure Python grading

For the user's **trusted laptop-only demo**, Judge0 can now be skipped with
`PLATFORM_PROFILE=local` and `PLATFORM_LOCAL_DEMO_PYTHON=true`. See
[LOCAL_PLATFORM.md](LOCAL_PLATFORM.md#python-on-this-laptop-for-the-demo) for the
explicit unisolated local mode. The instructions below remain the separate-runner
path for shared or untrusted use.

This app sends learner Python programs to a **separate Judge0-compatible Linux
server**, reached over HTTPS. The API and generation workers never execute those
programs on the app host. Multiple-choice and output questions do not need a
runner; Python submissions and reference/code-trace validation do.

Your budget remains free-only and you previously had no separate server. You
still need an institution-provided Linux VM, a spare separate Linux machine, or
a managed allocation whose actual price, API and isolation meet these requirements.
Self-hosted software is open source; obtaining a server is a separate step.
No subscription or infrastructure has been created by this update. The public
demo and a container on this application's machine are not approved runners.

## 1. Prepare the separate machine

Give these instructions to the host administrator. Use an isolated Linux host
with no application database, provider credentials, private files or mounts from
this app. Review the current upstream security notices before installation.
[Judge0 CE's release instructions](https://github.com/judge0/judge0/releases/tag/v1.13.1)
currently describe v1.13.1, Linux, Docker/Compose and Ubuntu 22.04 cgroup setup;
the release fixes critical issues in older versions. Check newer supported
releases before choosing a version. Kernel/cgroup changes require the host
administrator's review and may require a reboot.

On that host, after the prerequisite checks, the upstream release can be obtained
with:

```bash
curl -fLO https://github.com/judge0/judge0/releases/download/v1.13.1/judge0-v1.13.1.zip
unzip judge0-v1.13.1.zip
cd judge0-v1.13.1
```

Edit `judge0.conf` before starting containers. Generate independent random
credentials locally for `POSTGRES_PASSWORD`, `REDIS_PASSWORD` and `AUTHN_TOKEN`.
Use the exact same authentication token later for the app's `JUDGE0_TOKEN`.

```dotenv
AUTHN_HEADER=X-Auth-Token
AUTHN_TOKEN=REPLACE_WITH_A_LONG_RANDOM_TOKEN
ENABLE_NETWORK=false
ALLOW_ENABLE_NETWORK=false
```

These are Judge0's [upstream configuration fields](https://github.com/judge0/judge0/blob/master/judge0.conf).
Disable unneeded callback/additional-file/command-line features and enforce the
required resource limits at the host. Do not rely solely on client-provided
limits. Keep the runner's own database and Redis inaccessible from the app and
from submitted programs.

Use the release's Compose file to start its database and Redis, then its API and
workers. Modern Compose installations use `docker compose`; the upstream
instructions use `docker-compose`:

```bash
docker compose up -d db redis
# Wait until both services are healthy, then:
docker compose up -d
```

Put an HTTPS reverse proxy with a valid certificate in front of the API. Restrict
access to the application host/VPN and retain token authentication. Bind the raw
Judge0 API port to loopback or firewall it so it cannot bypass the proxy. Do not
expose Redis, PostgreSQL or the container engine. The app uses `X-Auth-Token`;
a vendor requiring different headers is not directly compatible without an
adapter change. Never put runner credentials in browser code.

## 2. Configure this app

In the existing ignored `.env` in the project root, add:

```dotenv
JUDGE0_URL=https://runner.YOUR_DOMAIN
JUDGE0_TOKEN=YOUR_AUTHN_TOKEN
JUDGE0_PYTHON_LANGUAGE_ID=0
JUDGE0_ISOLATION_VERIFIED=false
```

Use the HTTPS API base URL, with no `/submissions`, query or embedded credentials.
`0` is intentionally a placeholder. Language IDs vary between installations.

Run this from the project root in PowerShell:

```powershell
.venv\Scripts\python.exe scripts/check_runner.py
```

The checker only reads `/languages` and `/config_info` and verifies anonymous
requests are denied. It lists the host's Python versions/IDs. Set
`JUDGE0_PYTHON_LANGUAGE_ID` to the ID of its intended **Python 3** runtime and run
the checker again. The [Judge0 API documentation](https://ce.judge0.com/) describes
these endpoints and authentication. The checker neither submits code nor changes
the verification flag. A passing report proves configuration compatibility only.

The app currently requests, for each test case:

| Resource | Requested bound |
| --- | --- |
| CPU time | 2 seconds |
| Wall time | 5 seconds |
| Memory | 131072 KB (128 MiB) |
| Stack | 8192 KB |
| Processes/threads | 1 |
| File/output size | 64 KB; app also rejects oversized output |
| Network | Disabled |

The runner must accept these fields and enforce them. It must also isolate files
and execution state between submissions. The checker tests configuration ceilings
against the requested values; it does not prove enforcement.

## 3. Verify isolation before enabling it

Have the runner administrator test on the actual isolated host: infinite loop,
sleep, memory exhaustion, process/fork attempts, output flooding, file access,
network and DNS attempts, and cross-run files/state. Confirm host files,
credentials and other jobs cannot be reached. Use the full acceptance cases in
[OPERATIONS.md](OPERATIONS.md#runner-acceptance).

Record that evidence, then set `JUDGE0_ISOLATION_VERIFIED=true`. Restart the API,
generation worker and grading worker so all three load the changed `.env`.
`scripts/start-local.ps1` starts these together; avoid launching duplicate workers
or interrupting active jobs. For individual foreground processes use:

```powershell
# API, in one terminal:
.\scripts\start-platform.ps1
# Generation, in a second terminal:
.\scripts\start-platform.ps1 -Worker
# Grading, in a third terminal:
.\scripts\start-platform.ps1 -Grader
```

Check `/api/ready` for `python_runner: true`, then exercise a Python checkpoint
with correct, incorrect, timed-out and retried submissions. Configuration
readiness alone is not a live grading acceptance test.

## Troubleshooting

- **HTTP 401/403:** verify `JUDGE0_TOKEN` matches the runner's `AUTHN_TOKEN` and the
  proxy forwards `X-Auth-Token`.
- **DNS, TLS or timeout:** verify the certificate, hostname, firewall/VPN and host
  reachability. Do not turn off certificate verification.
- **Unknown language:** use the ID from this host's `/languages`, not an online example.
- **HTTP 422 when submitting:** compare accepted limit fields with the table above.
- **Jobs stay queued:** check the grading worker and runner worker processes.
- **Network checks fail:** fix the actual host configuration and keep the
  isolation flag false. A healthy HTTP endpoint is not an isolated runner.

Keep tokens in `.env`, never in chat, screenshots, version control or diagnostic
output. The checker intentionally reports no raw HTTP error bodies or tokens.
