# Start FinAlly in Docker (Windows PowerShell). Safe to run repeatedly.
#
#   .\scripts\start_windows.ps1            # build image if missing, start container, open browser
#   .\scripts\start_windows.ps1 -Build     # force an image rebuild (and restart the container)
#   .\scripts\start_windows.ps1 -NoOpen    # don't open a browser
#
# Env: FINALLY_PORT (host port, default 8000)
[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$NoOpen
)

# Native docker errors are checked via $LASTEXITCODE; 'Stop' would make
# Windows PowerShell 5.1 throw on redirected stderr from docker.
$ErrorActionPreference = 'Continue'

$Image = 'finally'
$Container = 'finally'
$Volume = 'finally-data'
$Port = if ($env:FINALLY_PORT) { $env:FINALLY_PORT } else { '8000' }
$Url = "http://localhost:$Port"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error 'docker is not installed. Install Docker Desktop: https://docs.docker.com/get-docker/'
    exit 1
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Error 'The Docker daemon is not running. Start Docker Desktop and try again.'
    exit 1
}

docker image inspect $Image *> $null
if ($Build -or $LASTEXITCODE -ne 0) {
    Write-Host "Building Docker image '$Image'..."
    docker build -t $Image .
    if ($LASTEXITCODE -ne 0) { Write-Error 'Docker build failed.'; exit 1 }
}

$running = docker inspect -f '{{.State.Running}}' $Container 2>$null
$exists = ($LASTEXITCODE -eq 0)

if ($running -eq 'true' -and -not $Build) {
    Write-Host "FinAlly is already running at $Url"
}
else {
    # Replace any stale (stopped, or pre-rebuild) container; the data volume is untouched.
    if ($exists) {
        docker stop $Container *> $null
        docker rm -f $Container *> $null
    }

    $envArgs = @()
    if (Test-Path '.env') {
        $envArgs = @('--env-file', '.env')
    }
    else {
        Write-Warning 'No .env file found - AI chat needs OPENROUTER_API_KEY.'
        Write-Warning 'Create one with: Copy-Item .env.example .env   (then add your key)'
    }

    Write-Host "Starting container '$Container'..."
    docker run -d --name $Container -p "${Port}:8000" -v "${Volume}:/app/db" @envArgs --restart unless-stopped $Image | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Error 'Failed to start the container.'; exit 1 }

    Write-Host -NoNewline 'Waiting for the app to become ready'
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri "$Url/api/health" -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -eq 200) { $ready = $true; break }
        }
        catch { }
        Write-Host -NoNewline '.'
        Start-Sleep -Seconds 1
    }
    Write-Host ''
    if (-not $ready) {
        Write-Warning "The app did not report healthy yet. Check logs with: docker logs $Container"
    }
}

Write-Host "FinAlly: $Url"

if (-not $NoOpen) {
    Start-Process $Url
}
