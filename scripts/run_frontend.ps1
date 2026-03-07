$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$webDir = Join-Path $root "web"
$logDir = Join-Path $root ".dev\logs"
$logPath = Join-Path $logDir "web.log"

New-Item -ItemType Directory -Path $logDir -Force | Out-Null

Set-Location $webDir
$env:AUTH_TYPE = "basic"
$env:DEV_MODE = "true"
# Keep frontend EE assumptions aligned with the local backend scripts,
# which disable license enforcement and therefore boot the MIT route set.
$env:LICENSE_ENFORCEMENT_ENABLED = "false"
$env:INTERNAL_URL = "http://127.0.0.1:8080"

npm run dev 2>&1 | Tee-Object -FilePath $logPath
