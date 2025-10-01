param(
  [string]$Branch = "codex/check-project-for-errors-and-inconsistencies",
  [switch]$UseArtifact = $false
)

$ROOT = Split-Path -Parent $PSCommandPath
Set-Location $ROOT
[Environment]::CurrentDirectory = (Get-Location).Path

if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
  Write-Host "Creating local virtual environment (.venv)..."
  python -m venv .venv
}

Write-Host "Activating virtual environment..."
& .\.venv\Scripts\Activate.ps1

Write-Host "Stashing local changes (if any)..."
git stash push -u -m "local-wip (auto)" | Out-Null

Write-Host "Fetching updates..."
git fetch --all --prune

Write-Host "Resetting to origin/$Branch..."
git reset --hard "origin/$Branch"

if ($UseArtifact) {
  if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Warning "GitHub CLI not found; skipping artifact download."
  } else {
    Write-Host "Downloading wheels artifact via GitHub CLI..."
    Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue
    gh run download --name wheels-win_amd64-cp311 --dir dist -L 1
    if (Test-Path "dist\wheels-win_amd64-cp311.zip") {
      Write-Host "Extracting wheels artifact..."
      Expand-Archive dist\wheels-win_amd64-cp311.zip -DestinationPath dist -Force
      Remove-Item -Recurse -Force .\wheels -ErrorAction SilentlyContinue
      Move-Item dist\wheels .\wheels -Force
    } else {
      Write-Warning "Wheels artifact not found; ensure the workflow finished successfully."
    }
  }
}

if ((Test-Path .\scripts\offline_install.ps1) -and (Test-Path .\wheels)) {
  Write-Host "Running offline dependency install..."
  powershell -ExecutionPolicy Bypass -File .\scripts\offline_install.ps1 -WheelsDir .\wheels
} else {
  Write-Warning "Offline install skipped (missing .\\wheels or scripts/offline_install.ps1)."
}

if (-not (Test-Path ".\.env") -and (Test-Path ".\.env.example")) {
  Write-Host "Creating .env from template..."
  Copy-Item .env.example .env
}

Write-Host "Ensuring var directory exists..."
New-Item -ItemType Directory -Path .\var -Force | Out-Null

Write-Host "Running database migrations..."
alembic upgrade head

Write-Host "Running database health check..."
python scripts\db_check.py

$botTokenLine = Select-String -Path .env -Pattern '^BOT_TOKEN=' -SimpleMatch | Select-Object -First 1
if ($botTokenLine) {
  $token = $botTokenLine.Line.Replace('BOT_TOKEN=', '').Trim()
  if ($token) {
    Write-Host "Removing Telegram webhook (drop pending updates)..."
    try {
      Invoke-WebRequest -UseBasicParsing -Uri "https://api.telegram.org/bot$token/deleteWebhook?drop_pending_updates=true" | Out-Null
    } catch {
      Write-Warning "Failed to delete webhook: $($_.Exception.Message)"
    }
  }
}

Write-Host "Starting bot..."
python -m app.main
