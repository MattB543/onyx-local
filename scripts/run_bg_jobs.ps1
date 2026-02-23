$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendDir = Join-Path $root "backend"
$logDir = Join-Path $root ".dev\logs"
$logPath = Join-Path $logDir "bg.log"

New-Item -ItemType Directory -Path $logDir -Force | Out-Null

Set-Location $backendDir
$env:PYTHONPATH = $backendDir
$env:AUTH_TYPE = "basic"
$env:DEV_MODE = "true"
$env:FILE_STORE_BACKEND = "postgres"
$env:LICENSE_ENFORCEMENT_ENABLED = "false"
$env:LOG_LEVEL = "debug"
$env:DEV_LOGGING_ENABLED = "true"
$env:REQUIRE_EMAIL_VERIFICATION = "False"
$env:ENABLE_CUSTOM_JOBS = "true"
$env:EMAIL_CRM_CUSTOM_JOB_ID = "3ac43005-1312-4d55-8ed1-f7303ddb36e2"
$env:PATH = (Join-Path $root ".venv\Scripts") + ";" + $env:PATH

& (Join-Path $root ".venv\Scripts\python.exe") scripts/dev_run_background_jobs.py 2>&1 |
    Tee-Object -FilePath $logPath
