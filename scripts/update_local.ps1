param(
  [string]$Branch = "codex/check-project-for-errors-and-inconsistencies",
  [string]$WheelsDir = $null,
  [switch]$NoRunBot
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $PSCommandPath
$RepoRoot  = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot
[Environment]::CurrentDirectory = $RepoRoot

function Restore-OfflineScript {
  param([string]$Path)
  $safeLines = @(
    'param([string]$WheelsDir=".\wheels")'
    '$ErrorActionPreference = ''Stop'''
    'function Fail([string]$m){ Write-Host ("ERROR: {0}" -f $m); exit 1 }'
    'Write-Host ("Offline install from: {0}" -f $WheelsDir)'
    ''
    'if (-not (Test-Path $WheelsDir)) { Fail ("No wheels dir: " + $WheelsDir) }'
    '$whl = Get-ChildItem $WheelsDir -Filter *.whl -ErrorAction SilentlyContinue'
    'if (-not $whl -or $whl.Count -lt 1) { Fail ("No .whl files in " + $WheelsDir) }'
    ''
    'if (Test-Path ".\wheels-packages.txt") {'
    '  pip install --isolated --no-index --find-links "$WheelsDir" -r .\wheels-packages.txt'
    '}'
    'if (Test-Path ".\requirements.txt") {'
    '  pip install --isolated --no-index --find-links "$WheelsDir" -r .\requirements.txt'
    '}'
    ''
    '$need = @(''SQLAlchemy'',''alembic'',''aiosqlite'',''aiogram'',''python-dotenv'')'
    'foreach ($p in $need) {'
    '  if (-not (pip show $p 2>$null)) { pip install --isolated --no-index --find-links "$WheelsDir" $p }'
    '}'
    'foreach ($p in $need) {'
    '  if (-not (pip show $p 2>$null)) { Fail ("Missing package: " + $p) }'
    '}'
    'Write-Host "Offline install: done."'
  )
  $text = ($safeLines -join "`r`n") + "`r`n"
  $utf8 = New-Object System.Text.UTF8Encoding($false)
  [IO.File]::WriteAllText($Path, $text, $utf8)
}

function Ensure-AsciiOfflineScript {
  param([string]$Path)
  if (-not (Test-Path $Path -PathType Leaf)) {
    Write-Warning ("offline_install.ps1 missing at {0}. Restoring safe copy..." -f $Path)
    Restore-OfflineScript -Path $Path
    return
  }
  $bytes = [IO.File]::ReadAllBytes($Path)
  if (($bytes | Where-Object { $_ -gt 127 }).Count -gt 0) {
    Write-Warning "offline_install.ps1 contains non-ASCII bytes. Restoring safe version..."
    Restore-OfflineScript -Path $Path
  }
}

$logsDir = Join-Path $ScriptDir 'logs'
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$logPath = Join-Path $logsDir ("update_{0}.log" -f $timestamp)
Start-Transcript -Path $logPath -Force | Out-Null

$failed = $false

try {
  Write-Host ("Update log: {0}" -f $logPath)
  if ([string]::IsNullOrWhiteSpace($Branch)) {
    $Branch = "main"
  }
  if ([string]::IsNullOrWhiteSpace($WheelsDir)) {
    if ($env:WHEELS_DIR) {
      $WheelsDir = $env:WHEELS_DIR
    } else {
      $WheelsDir = Join-Path $RepoRoot 'wheels'
    }
  }
  Write-Host ("Target branch: {0}" -f $Branch)
  Write-Host ("Wheels dir: {0}" -f $WheelsDir)

  if (-not (Test-Path "$RepoRoot\.venv\Scripts\Activate.ps1")) {
    Write-Host "Creating virtual environment (.venv)..."
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Failed to create virtual environment." }
  }

  Write-Host "Activating virtual environment..."
  . "$RepoRoot\.venv\Scripts\Activate.ps1"

  Write-Host "Checking offline wheels directory..."
  if (-not (Test-Path $WheelsDir -PathType Container)) {
    throw ("Offline wheels directory not found: {0}" -f $WheelsDir)
  }
  $wheelProbe = Get-ChildItem -Path $WheelsDir -Filter *.whl -File -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $wheelProbe) {
    throw ("No wheel files detected in {0}" -f $WheelsDir)
  }

  Write-Host "Stashing local changes (code only)..."
  git stash push -u -m "auto-local-wip" -- . ':(exclude)wheels' ':(exclude)var' ':(exclude)logs' ':(exclude)dist' | Out-Null

  Write-Host "Fetching updates..."
  git fetch --all --prune
  if ($LASTEXITCODE -ne 0) { throw "git fetch failed." }

  Write-Host ("Resetting to origin/{0}..." -f $Branch)
  git reset --hard ("origin/" + $Branch)
  if ($LASTEXITCODE -ne 0) { throw "git reset failed." }

  $offline = Join-Path $ScriptDir 'offline_install.ps1'
  Ensure-AsciiOfflineScript -Path $offline

  Write-Host ("Call: powershell -File {0} -WheelsDir {1}" -f $offline, $WheelsDir)
  & powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File $offline -WheelsDir $WheelsDir
  if ($LASTEXITCODE -ne 0) { throw "Offline dependency installation failed." }

  if (-not (Test-Path "$RepoRoot\.env") -and (Test-Path "$RepoRoot\.env.example")) {
    Write-Host "Creating .env from template..."
    Copy-Item "$RepoRoot\.env.example" "$RepoRoot\.env"
  }

  Write-Host "Ensuring var directory exists..."
  New-Item -ItemType Directory -Path "$RepoRoot\var" -Force | Out-Null

  Write-Host "Running database migrations..."
  alembic upgrade head
  if ($LASTEXITCODE -ne 0) { throw "Database migrations failed." }

  Write-Host "Running database health check..."
  python scripts\db_check.py
  if ($LASTEXITCODE -ne 0) { throw "Database health check failed." }

  $envPath = "$RepoRoot\.env"
  if (Test-Path $envPath -PathType Leaf) {
    $botTokenLine = Select-String -Path $envPath -Pattern '^BOT_TOKEN=' -SimpleMatch -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($botTokenLine) {
      $token = $botTokenLine.Line.Replace('BOT_TOKEN=', '').Trim()
      if ($token) {
        Write-Host "Deleting Telegram webhook..."
        try {
          Invoke-WebRequest -UseBasicParsing -Uri ("https://api.telegram.org/bot{0}/deleteWebhook?drop_pending_updates=true" -f $token) | Out-Null
        } catch {
          Write-Warning ("Failed to delete webhook: {0}" -f $_.Exception.Message)
        }
      }
    }
  }

  if ($NoRunBot) {
    Write-Host "NoRunBot flag set. Skipping bot startup."
  } else {
    Write-Host "Starting bot... Ctrl+C to stop."
    python -m app.main
    if ($LASTEXITCODE -ne 0) { throw "Bot exited with a non-zero code." }
  }
}
catch {
  $failed = $true
  Write-Error $_
}
finally {
  try { Stop-Transcript | Out-Null } catch {}
  Write-Host ("Log: {0}" -f $logPath)
  if ($failed) {
    Write-Host "Update failed. See log for details." -ForegroundColor Red
    exit 1
  } else {
    Write-Host "Update complete." -ForegroundColor Green
    exit 0
  }
}
