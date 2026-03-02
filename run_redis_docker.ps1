$ErrorActionPreference = 'Stop'

$containerName = 'walkingmate-redis'
$redisImage = 'redis:7-alpine'
$portMap = '6379:6379'

$dockerOk = $true
try {
    docker info *> $null
} catch {
    $dockerOk = $false
}

if (-not $dockerOk) {
    Write-Host 'Docker daemon is not reachable.' -ForegroundColor Red
    Write-Host 'Open Docker Desktop first, then retry.' -ForegroundColor Yellow
    exit 1
}

$exists = docker ps -a --format '{{.Names}}' | Select-String -Pattern "^$containerName$" -Quiet
if ($exists) {
    docker start $containerName *> $null
} else {
    docker run -d --name $containerName -p $portMap $redisImage *> $null
}

Write-Host 'Redis container status:' -ForegroundColor Green
docker ps --filter "name=$containerName" --format "table {{.Names}}`t{{.Status}}`t{{.Ports}}"

