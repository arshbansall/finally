# Stop FinAlly (Windows PowerShell). Removes the container but keeps the
# 'finally-data' volume, so your portfolio persists. Safe to run repeatedly.
# Native docker errors are checked via $LASTEXITCODE; 'Stop' would make
# Windows PowerShell 5.1 throw on redirected stderr from docker.
$ErrorActionPreference = 'Continue'

$Container = 'finally'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error 'docker is not installed.'
    exit 1
}

docker container inspect $Container *> $null
if ($LASTEXITCODE -eq 0) {
    docker stop $Container *> $null
    docker rm -f $Container *> $null
    Write-Host "FinAlly stopped (data volume 'finally-data' kept)."
}
else {
    Write-Host 'FinAlly is not running.'
}
