$ErrorActionPreference = 'Stop'

$root = 'C:\androidApp\server'
$python = 'C:\androidApp\server\.venv\Scripts\python.exe'
$serverOut = Join-Path $root '_server_runtime.out.log'
$serverErr = Join-Path $root '_server_runtime.err.log'
$workerOut = Join-Path $root '_worker_runtime.out.log'
$workerErr = Join-Path $root '_worker_runtime.err.log'

@($serverOut, $serverErr, $workerOut, $workerErr) | ForEach-Object {
    if (Test-Path $_) {
        try {
            Remove-Item $_ -Force -ErrorAction Stop
        } catch {
            Write-Host "Skipped log cleanup (in use): $_" -ForegroundColor Yellow
        }
    }
}

Push-Location $root

Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -eq $python
} | ForEach-Object {
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}

$env:USE_WAITRESS = '1'
$env:PORT = '18080'
$env:PYTHONUNBUFFERED = '1'
# __pycache__/pyc 생성 억제로 실행 폴더 오염을 줄인다.
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:RQ_SIMPLE_WORKER = '1'
$env:NUMBA_DISABLE_JIT = '1'
if (-not $env:REDIS_URL) { $env:REDIS_URL = 'redis://127.0.0.1:6379/0' }

$redisReachable = $false
$oldErrorPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $python -B -c "from music_server.services.infra import ping_redis; ping_redis()" *> $null
if ($LASTEXITCODE -eq 0) { $redisReachable = $true }
$ErrorActionPreference = $oldErrorPreference

if (-not $redisReachable) {
    Write-Host 'Redis is not reachable.' -ForegroundColor Red
    Write-Host 'Start Redis first, then run this script again.' -ForegroundColor Yellow
    Write-Host 'Example: run .\run_redis_docker.ps1 (requires Docker Desktop running).' -ForegroundColor Yellow
    exit 1
}

Start-Process -FilePath $python -ArgumentList 'C:\androidApp\server\server.py' -WorkingDirectory $root -RedirectStandardOutput $serverOut -RedirectStandardError $serverErr
Start-Process -FilePath $python -ArgumentList 'C:\androidApp\server\run_worker.py' -WorkingDirectory $root -RedirectStandardOutput $workerOut -RedirectStandardError $workerErr

Start-Sleep -Seconds 2

Write-Host '=== Running processes ==='
Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -eq $python
} | Select-Object Id, ProcessName, Path | Format-Table -AutoSize

Write-Host ''
Write-Host '=== Listening port 18080 ==='
Get-NetTCPConnection -State Listen -LocalPort 18080 -ErrorAction SilentlyContinue | Select-Object LocalAddress, LocalPort, OwningProcess, State | Format-Table -AutoSize

Write-Host ''
Write-Host '=== Tailing logs (Ctrl+C to stop tail only) ==='
Get-Content -Path $serverOut, $serverErr, $workerOut, $workerErr -Wait
Pop-Location
