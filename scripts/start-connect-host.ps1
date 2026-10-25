<#
.SYNOPSIS
  One step: start this PC as the sign-in host for Settings -> Platforms -> Connect.

.DESCRIPTION
  Pulls the production settings of the cvil-war-api Vercel project into a temporary file,
  loads the database URL and encryption keys into this process only, deletes the file, and
  starts the DB-queue worker with -ConnectOnly (sign-in windows only, never applications).
  Values are never printed. Needs `npx vercel login` to have been run once on this PC.

.EXAMPLE
  .\scripts\start-connect-host.ps1
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("cvilwar-prod-{0}.env" -f [guid]::NewGuid())

Push-Location $backend
try {
    npx --yes vercel env pull $tmp --environment=production --yes | Out-Null
    if (-not (Test-Path $tmp)) { Write-Host 'BLOCKED: vercel env pull failed (run: npx vercel login).'; exit 2 }

    $vars = @{}
    foreach ($line in Get-Content $tmp) {
        if ($line -match '^\s*([A-Z0-9_]+)\s*=\s*"?(.*?)"?\s*$') { $vars[$Matches[1]] = $Matches[2] }
    }
} finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    Pop-Location
}

$db = $vars['DATABASE_URL']
$keys = $vars['SECRETS__APP_KEYS']
if (-not $db) { Write-Host 'BLOCKED: DATABASE_URL came back empty (marked Sensitive on Vercel?).'; exit 2 }
if (-not $keys) { Write-Host 'BLOCKED: SECRETS__APP_KEYS came back empty (marked Sensitive on Vercel?).'; exit 2 }

# The worker holds a session for minutes at a time: use Supabase's session pooler (5432),
# not the transaction pooler (6543) the serverless API uses.
$env:PROD_DATABASE_URL = $db -replace ':6543/', ':5432/'
$env:SECRETS__APP_KEYS = $keys
$env:ENVIRONMENT = 'production'
if ($vars['ANTHROPIC_API_KEY']) { $env:ANTHROPIC_API_KEY = $vars['ANTHROPIC_API_KEY'] }

& (Join-Path $PSScriptRoot 'db-worker.ps1') -Start -ConnectOnly
Write-Host 'Sign-in host running. Click Connect on https://cvil-war.vercel.app/settings.'
