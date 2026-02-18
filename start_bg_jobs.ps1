$ErrorActionPreference = "Stop"

$Host.UI.RawUI.WindowTitle = "Onyx: Background Jobs"
& (Join-Path $PSScriptRoot "scripts\run_bg_jobs.ps1")
