param(
    [string]$OllamaPath = '',
    [string]$ModelDirectory = (Join-Path $env:LOCALAPPDATA 'PromptToVideo\models')
)
$ErrorActionPreference = 'Stop'
if (-not $OllamaPath) {
    $installedCommand = Get-Command ollama -ErrorAction SilentlyContinue
    if ($installedCommand) { $OllamaPath = $installedCommand.Source }
    else { $OllamaPath = Join-Path $env:LOCALAPPDATA 'PromptToVideo\ollama-v0.35.1\ollama.exe' }
}
if (-not (Test-Path -LiteralPath $OllamaPath -PathType Leaf)) {
    throw 'Install the official Ollama runtime or pass -OllamaPath with its executable path.'
}
if (Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue) {
    throw 'An Ollama service already uses port 11434. Use that service, or stop your dedicated instance before starting this one.'
}
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_MODELS = [System.IO.Path]::GetFullPath($ModelDirectory)
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_MAX_LOADED_MODELS = '1'
Remove-Item Env:\GEMINI_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:\GOOGLE_API_KEY -ErrorAction SilentlyContinue
Write-Output "Local Ollama uses $env:OLLAMA_MODELS. Stop this dedicated runtime with Ctrl+C."
& $OllamaPath serve
