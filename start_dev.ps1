$ErrorActionPreference = "Stop"

$root = (Resolve-Path $PSScriptRoot).Path
$scriptsDir = Join-Path $root "scripts"
$logDir = Join-Path $root ".dev\logs"

New-Item -ItemType Directory -Path $logDir -Force | Out-Null

function Start-OnyxServiceWindow {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title,
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath
    )

    Start-Process powershell -ArgumentList "-NoExit", "-Command", @"
`$Host.UI.RawUI.WindowTitle = '$Title'
& '$ScriptPath'
"@
}

Write-Host "Starting Onyx dev services..." -ForegroundColor Cyan
Write-Host "Shared logs: $logDir" -ForegroundColor DarkGray

Write-Host "  [1/4] Model Server (9000)..." -ForegroundColor Green
Start-OnyxServiceWindow -Title "Onyx: Model Server (9000)" -ScriptPath (Join-Path $scriptsDir "run_model_server.ps1")

Write-Host "  [2/4] API Server (8080)..." -ForegroundColor Green
Start-OnyxServiceWindow -Title "Onyx: API Server (8080)" -ScriptPath (Join-Path $scriptsDir "run_api_server.ps1")

Write-Host "  [3/4] Background Jobs..." -ForegroundColor Green
Start-OnyxServiceWindow -Title "Onyx: Background Jobs" -ScriptPath (Join-Path $scriptsDir "run_bg_jobs.ps1")

Write-Host "  [4/4] Frontend (3000)..." -ForegroundColor Green
Start-OnyxServiceWindow -Title "Onyx: Frontend (3000)" -ScriptPath (Join-Path $scriptsDir "run_frontend.ps1")

Write-Host ""
Write-Host "All services launching! Open http://localhost:3000 once ready." -ForegroundColor Cyan
Write-Host "Tail logs live: powershell -ExecutionPolicy Bypass -File scripts\\tail_logs.ps1" -ForegroundColor Yellow
Write-Host "Stop app services: powershell -ExecutionPolicy Bypass -File scripts\\stop_all.ps1" -ForegroundColor Gray
