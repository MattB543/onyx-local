$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendDir = Join-Path $root "backend"
$logDir = Join-Path $root ".dev\logs"
$logPath = Join-Path $logDir "model.log"

New-Item -ItemType Directory -Path $logDir -Force | Out-Null

Set-Location $backendDir
$env:PYTHONPATH = $backendDir
$env:FILE_STORE_BACKEND = "postgres"
$env:LOG_LEVEL = "debug"
$env:DEV_LOGGING_ENABLED = "true"

& (Join-Path $root ".venv\Scripts\uvicorn.exe") model_server.main:app --reload --port 9000 2>&1 |
    Tee-Object -FilePath $logPath
