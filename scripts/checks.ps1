$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectPath
$ffmpegFolder = Join-Path $projectPath '.local/bin/ffmpeg'
if (Test-Path -LiteralPath $ffmpegFolder) {
    $ffmpegExecutable = Get-ChildItem -LiteralPath $ffmpegFolder -Filter ffmpeg.exe -Recurse | Select-Object -First 1
    if ($ffmpegExecutable) { $env:PATH = $ffmpegExecutable.DirectoryName + ';' + $env:PATH }
}
# Use a fresh workspace-owned directory instead of a stale shared Windows
# pytest temp/cache directory, which may belong to a previous execution account.
$checkRunPath = Join-Path $projectPath ('.run/checks-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $checkRunPath | Out-Null
$pytestTempPath = Join-Path $checkRunPath 'pytest'
$pytestCachePath = Join-Path $checkRunPath 'cache'
& .venv/Scripts/python.exe -m pytest -q --basetemp $pytestTempPath -o "cache_dir=$pytestCachePath" --junitxml .run/platform-test-results-final.xml
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Push-Location client
try {
    npm test
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    npm run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally { Pop-Location }
