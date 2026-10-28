# Starts the whole local platform: PostgreSQL, Ollama, API and workers.
# Everything (data, models, caches, temp files) stays inside this project folder.
param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$local = Join-Path $root '.local'
$logs = Join-Path $root '.run\logs'
New-Item -ItemType Directory -Force (Join-Path $local 'tmp'), $logs | Out-Null
$env:TEMP = Join-Path $local 'tmp'; $env:TMP = $env:TEMP; $env:PYTHONUTF8 = '1'
$python = Join-Path $root '.venv\Scripts\python.exe'
$pg = Join-Path $local 'pgsql\bin'
$pgdata = Join-Path $local 'pgdata'
$pids = Join-Path $root '.run\local-pids.txt'
$ffmpegRoot = Join-Path $local 'bin\ffmpeg'
if (Test-Path -LiteralPath $ffmpegRoot) {
    $ffmpeg = Get-ChildItem -LiteralPath $ffmpegRoot -Filter ffmpeg.exe -Recurse | Select-Object -First 1
    if ($ffmpeg) { $env:PATH = $ffmpeg.DirectoryName + ';' + $env:PATH }
}
foreach ($required in @($python, (Join-Path $pg 'pg_ctl.exe'), (Join-Path $root 'client\dist\index.html'))) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Missing $required. See LOCAL_PLATFORM.md." }
}
function Listening($p) { [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) }
function Start-Hidden($name, $file, $arguments) {
    $process = Start-Process -FilePath $file -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logs "$name.out.log") -RedirectStandardError (Join-Path $logs "$name.err.log")
    Add-Content -LiteralPath $pids "$name $($process.Id)"
    Write-Output "Started $name (pid $($process.Id))"
}
if (Test-Path -LiteralPath $pids) { throw 'The platform looks already started. Run scripts\stop-local.ps1 first.' }

# 1. Database (loopback only, port 5433).
if (-not (Test-Path -LiteralPath $pgdata)) {
    & (Join-Path $pg 'initdb.exe') -D $pgdata -U postgres --auth=trust -E UTF8 --no-locale | Out-Null
    Add-Content -LiteralPath (Join-Path $pgdata 'postgresql.conf') "listen_addresses = '127.0.0.1'`nport = 5433"
}
if (-not (Listening 5433)) {
    # Wait for pg_ctl only; the server it launches keeps running in the background.
    $ctl = Start-Process -FilePath (Join-Path $pg 'pg_ctl.exe') -ArgumentList @('-D', "`"$pgdata`"", '-l', "`"$(Join-Path $logs 'postgres.log')`"", '-o', '"-p 5433 -h 127.0.0.1"', '-w', 'start') -WindowStyle Hidden -PassThru
    $ctl.WaitForExit()
    if (-not (Listening 5433)) { throw 'PostgreSQL did not start. See .run\logs\postgres.log.' }
}
$psql = Join-Path $pg 'psql.exe'
$exists = & $psql -h 127.0.0.1 -p 5433 -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname = 'btp2'"
if ($exists -ne '1') {
    & $psql -h 127.0.0.1 -p 5433 -U postgres -qc 'CREATE DATABASE btp2' | Out-Null
    $files = @('migrations\local\000_shim.sql') + (Get-ChildItem migrations\0*.sql | Sort-Object Name | ForEach-Object { $_.FullName }) + @('migrations\local\100_local_accounts.sql')
    foreach ($file in $files) { & $psql -h 127.0.0.1 -p 5433 -U postgres -d btp2 -q -v ON_ERROR_STOP=1 -f $file | Out-Null; if ($LASTEXITCODE) { throw "Migration failed: $file" } }
    Write-Output 'Created database btp2 and applied migrations.'
}

# 2. Start Ollama only when selected for platform text generation.
# This additive migration is safe to rerun for an existing local database.
& $psql -h 127.0.0.1 -p 5433 -U postgres -d btp2 -q -v ON_ERROR_STOP=1 -f 'migrations\005_classroom_management.sql' | Out-Null
if ($LASTEXITCODE) { throw 'Classroom-management migration failed.' }
$textProvider = $env:PLATFORM_TEXT_PROVIDER
if (-not $textProvider -and (Test-Path -LiteralPath (Join-Path $root '.env'))) {
    $providerLine = Select-String -LiteralPath (Join-Path $root '.env') -Pattern '^\s*PLATFORM_TEXT_PROVIDER\s*=' | Select-Object -Last 1
    if ($providerLine) { $textProvider = ($providerLine.Line -split '=', 2)[1].Trim().Trim('"', "'") }
}
if ($textProvider -eq 'ollama' -and -not (Listening 11434)) {
    if (-not (Test-Path -LiteralPath (Join-Path $local 'ollama\ollama.exe'))) { throw 'Ollama is selected but not installed. See LOCAL_PLATFORM.md.' }
    $env:OLLAMA_HOST = '127.0.0.1:11434'; $env:OLLAMA_MODELS = Join-Path $local 'models'
    $env:OLLAMA_NO_CLOUD = '1'; $env:OLLAMA_NUM_PARALLEL = '1'; $env:OLLAMA_MAX_LOADED_MODELS = '1'
    # Smaller context cache keeps more of the model on a 4 GB laptop GPU.
    $env:OLLAMA_FLASH_ATTENTION = '1'; $env:OLLAMA_KV_CACHE_TYPE = 'q8_0'
    Start-Hidden 'ollama' (Join-Path $local 'ollama\ollama.exe') 'serve'
}

# 3. API (serves the built client) and the generation + grading workers.
Start-Hidden 'api' $python "-m uvicorn server.platform:app --host 127.0.0.1 --port $Port --workers 1 --no-proxy-headers"
Start-Hidden 'worker-generation' $python '-m server.worker --queue generation'
Start-Hidden 'worker-grading' $python '-m server.worker --queue grading'
Write-Output "Open http://127.0.0.1:$Port  (logs: .run\logs, stop: scripts\stop-local.ps1)"
