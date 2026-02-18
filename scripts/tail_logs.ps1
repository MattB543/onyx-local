param(
    [ValidateSet("all", "web", "api", "model", "bg")]
    [string]$Service = "all",
    [int]$Tail = 120
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logDir = Join-Path $root ".dev\logs"
$serviceLogFiles = @{
    web   = "web.log"
    api   = "api.log"
    model = "model.log"
    bg    = "bg.log"
}

New-Item -ItemType Directory -Path $logDir -Force | Out-Null

if ($Service -eq "all") {
    $paths = $serviceLogFiles.Values | ForEach-Object {
        $path = Join-Path $logDir $_
        if (-not (Test-Path $path)) {
            New-Item -ItemType File -Path $path -Force | Out-Null
        }
        $path
    }

    Write-Host "Tailing all logs in $logDir (Ctrl+C to stop)..." -ForegroundColor Cyan
    Get-Content -Path $paths -Tail $Tail -Wait
    return
}

$selectedPath = Join-Path $logDir $serviceLogFiles[$Service]
if (-not (Test-Path $selectedPath)) {
    New-Item -ItemType File -Path $selectedPath -Force | Out-Null
}

Write-Host "Tailing $Service logs in $selectedPath (Ctrl+C to stop)..." -ForegroundColor Cyan
Get-Content -Path $selectedPath -Tail $Tail -Wait
