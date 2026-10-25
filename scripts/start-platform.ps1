param([switch]$Worker, [switch]$Grader, [switch]$Maintenance)
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectPath
$ffmpegFolder = Join-Path $projectPath '.local/bin/ffmpeg'
if (Test-Path -LiteralPath $ffmpegFolder) {
    $ffmpegExecutable = Get-ChildItem -LiteralPath $ffmpegFolder -Filter ffmpeg.exe -Recurse | Select-Object -First 1
    if ($ffmpegExecutable) { $env:PATH = $ffmpegExecutable.DirectoryName + ';' + $env:PATH }
}
if ($Maintenance) { & .venv/Scripts/python.exe -m server.worker --queue maintenance }
elseif ($Grader) { & .venv/Scripts/python.exe -m server.worker --queue grading }
elseif ($Worker) { & .venv/Scripts/python.exe -m server.worker --queue generation }
else { & .venv/Scripts/python.exe -m uvicorn server.platform:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers }
exit $LASTEXITCODE
