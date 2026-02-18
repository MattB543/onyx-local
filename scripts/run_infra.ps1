param(
    [switch]$WithMinio,
    [switch]$Down
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$composeDir = Join-Path $root "deployment\docker_compose"
$composeArgs = @("-f", "docker-compose.yml", "-f", "docker-compose.dev.yml")
$services = @("index", "relational_db", "cache")

if ($WithMinio) {
    $services += "minio"
}

Push-Location $composeDir
try {
    if ($Down) {
        docker compose @composeArgs down
        return
    }

    if ($WithMinio) {
        docker compose @composeArgs --profile s3-filestore up -d --wait @services
    }
    else {
        docker compose @composeArgs up -d --wait @services
    }

    docker compose @composeArgs ps
}
finally {
    Pop-Location
}
