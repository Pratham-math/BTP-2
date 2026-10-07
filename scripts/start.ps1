param([ValidateRange(1024, 65535)][int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Create the project .venv and install requirements.txt first.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'client\dist\index.html'))) { throw 'Run npm run build from client first.' }
foreach ($toolName in @('ffmpeg', 'ffprobe')) {
    if (-not (Get-Command $toolName -ErrorAction SilentlyContinue)) { throw "$toolName must be available on PATH." }
}
if (-not $env:APP_ORIGINS) {
    $env:APP_ORIGINS = "http://127.0.0.1:$Port,http://localhost:$Port,http://127.0.0.1:5173,http://localhost:5173"
}
Write-Output "Open http://127.0.0.1:$Port. Stop this server with Ctrl+C."
& $pythonPath -m uvicorn server.main:app --host 127.0.0.1 --port $Port --workers 1 --no-proxy-headers
