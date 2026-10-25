<#
.SYNOPSIS
  Start, stop or inspect the local DB-queue worker that applies for the production site (D-016).

.DESCRIPTION
  Runs `python scripts/db_worker.py --prod` from backend/ as a background process, logging to
  backend/data/logs/db-worker.log and tracking its PID in backend/data/logs/db-worker.pid.
  Reads PROD_DATABASE_URL (and SECRETS__APP_KEYS, ANTHROPIC_API_KEY, BROWSER__LIVE_APPLY) from
  the environment — never from this file. See docs/LOCAL_SETUP.md.

.EXAMPLE
  .\scripts\db-worker.ps1 -DryRun     # read-only: list what would run against production
  .\scripts\db-worker.ps1 -Start
  .\scripts\db-worker.ps1 -Status
  .\scripts\db-worker.ps1 -Stop
#>
param(
    [switch]$Start,
    [switch]$Stop,
    [switch]$Status,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$backend = Join-Path (Split-Path -Parent $PSScriptRoot) 'backend'
$python = Join-Path $backend '.venv\Scripts\python.exe'
$pidFile = Join-Path $backend 'data\logs\db-worker.pid'
$logDir = Join-Path $backend 'data\logs'
$log = Join-Path $logDir 'db-worker.log'

function Get-WorkerProcess {
    if (-not (Test-Path $pidFile)) { return $null }
    $workerPid = [int](Get-Content $pidFile -Raw)
    return Get-Process -Id $workerPid -ErrorAction SilentlyContinue
}

if (-not $env:PROD_DATABASE_URL) {
    if ($Start -or $DryRun) {
        Write-Host 'BLOCKED: set PROD_DATABASE_URL in this shell first (see docs/LOCAL_SETUP.md).'
        exit 2
    }
}

if ($DryRun) {
    Push-Location $backend
    try { & $python scripts/db_worker.py --prod --dry-run } finally { Pop-Location }
    exit $LASTEXITCODE
}

if ($Start) {
    if (Get-WorkerProcess) { Write-Host 'Worker already running.'; exit 0 }
    New-Item -ItemType Directory -Force $logDir | Out-Null
    $proc = Start-Process -FilePath $python -ArgumentList 'scripts/db_worker.py', '--prod' `
        -WorkingDirectory $backend -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err"
    Set-Content -Path $pidFile -Value $proc.Id
    Write-Host "Worker started (PID $($proc.Id)). Log: $log"
    exit 0
}

if ($Stop) {
    $proc = Get-WorkerProcess
    if ($proc) { Stop-Process -Id $proc.Id; Write-Host "Worker stopped (PID $($proc.Id))." }
    else { Write-Host 'Worker was not running.' }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    exit 0
}

$proc = Get-WorkerProcess
if ($proc) { Write-Host "Running (PID $($proc.Id)). Log: $log" } else { Write-Host 'Not running.' }
