Get-Process -Name 'uvicorn','celery' -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process | Where-Object {$_.CommandLine -like '*onyx*' -and $_.Name -eq 'python'} | Stop-Process -Force -ErrorAction SilentlyContinue
# Also kill any node dev servers on port 3000
Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Get-NetTCPConnection -LocalPort 9000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Write-Host "All Onyx services stopped."
