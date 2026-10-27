# Stops what start-local.ps1 started, then the local database.
$root = Split-Path -Parent $PSScriptRoot
$pids = Join-Path $root '.run\local-pids.txt'
if (Test-Path -LiteralPath $pids) {
    foreach ($line in Get-Content -LiteralPath $pids) {
        $name, $id = $line -split ' '
        try { Stop-Process -Id ([int]$id) -Force -ErrorAction Stop; Write-Output "Stopped $name" } catch { Write-Output "$name was not running" }
    }
    Remove-Item -LiteralPath $pids
}
$pgdata = Join-Path $root '.local\pgdata'
if (Test-Path -LiteralPath (Join-Path $pgdata 'postmaster.pid')) {
    & (Join-Path $root '.local\pgsql\bin\pg_ctl.exe') -D $pgdata -m fast stop | Out-Null
    Write-Output 'Stopped PostgreSQL'
}
