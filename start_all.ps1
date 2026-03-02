$ErrorActionPreference = 'Stop'

$root = 'C:\androidApp\server'
$python = Join-Path $root '.venv\Scripts\python.exe'
$redisScript = Join-Path $root 'run_redis_docker.ps1'
$appScript = Join-Path $root 'run_both_with_logs.ps1'

if (-not (Test-Path $redisScript)) {
    Write-Host "Missing script: $redisScript" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $appScript)) {
    Write-Host "Missing script: $appScript" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $python)) {
    Write-Host "Missing python executable: $python" -ForegroundColor Red
    exit 1
}

Write-Host '[1/2] Checking Redis availability...' -ForegroundColor Cyan
$redisReachable = $false
try {
    & $python -B -c "from music_server.services.infra import ping_redis; ping_redis()" *> $null
    if ($LASTEXITCODE -eq 0) { $redisReachable = $true }
} catch {
    $redisReachable = $false
}

if (-not $redisReachable) {
    Write-Host 'Redis is not reachable from Python. Trying Docker Redis...' -ForegroundColor Yellow
    powershell -ExecutionPolicy Bypass -File $redisScript
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Failed to start Redis. Aborting.' -ForegroundColor Red
        exit $LASTEXITCODE
    }
} else {
    Write-Host 'Redis is already reachable. Skipping Docker start.' -ForegroundColor Green
}

Write-Host '[2/2] Starting API server + worker...' -ForegroundColor Cyan
powershell -ExecutionPolicy Bypass -File $appScript
