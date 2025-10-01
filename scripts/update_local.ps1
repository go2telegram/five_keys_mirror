param(
  [string]$Branch,
  [string]$WheelsDir,
  [switch]$UseArtifact = $false
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Throw-WithHint {
  param(
    [string]$Message,
    [string]$Hint = $null
  )

  $ex = [System.Exception]::new($Message)
  if ($Hint) {
    $ex.Data["Hint"] = $Hint
  }
  throw $ex
}

function Ensure-Success {
  param(
    [string]$Message,
    [string]$Hint = $null
  )

  if ($LASTEXITCODE -ne 0) {
    Throw-WithHint -Message $Message -Hint $Hint
  }
}

$ROOT = Split-Path -Parent $PSCommandPath
Set-Location $ROOT
[Environment]::CurrentDirectory = (Get-Location).Path

if (-not $Branch) {
  $Branch = (git rev-parse --abbrev-ref HEAD).Trim()
}

if (-not $WheelsDir -or [string]::IsNullOrWhiteSpace($WheelsDir)) {
  if ($env:WHEELS_DIR) {
    $WheelsDir = $env:WHEELS_DIR
  } else {
    $WheelsDir = Join-Path $ROOT "wheels"
  }
}

$logsDir = Join-Path $ROOT "logs"
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = Join-Path $logsDir "update_$timestamp.log"

$failed = $false
$hintMessage = $null
$errorMessage = $null

Start-Transcript -Path $logPath -Append | Out-Null

try {
  Write-Host "Update log: $logPath"
  Write-Host "Target branch: $Branch"
  Write-Host "Wheels dir: $WheelsDir"

  if (-not (Test-Path ".\\.venv\\Scripts\\Activate.ps1")) {
    Write-Host "Creating local virtual environment (.venv)..."
    python -m venv .venv
    Ensure-Success -Message "Failed to create virtual environment." -Hint "Install Python 3.11 and retry."
  }

  Write-Host "Activating virtual environment..."
  & .\\.venv\Scripts\Activate.ps1

  Write-Host "Stashing local changes (excluding wheels/var/logs/dist)..."
  git stash push -u -m "local-wip (auto)" -- . ':(exclude)wheels' ':(exclude)var' ':(exclude)logs' ':(exclude)dist' | Out-Null

  Write-Host "Fetching updates..."
  git fetch --all --prune
  Ensure-Success -Message "git fetch failed." -Hint "Check network access or Git remote configuration."

  Write-Host "Resetting to origin/$Branch..."
  git reset --hard "origin/$Branch"
  Ensure-Success -Message "git reset failed." -Hint "Verify the branch name or fetch permissions."

  if ($UseArtifact) {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
      Write-Warning "GitHub CLI not found; skipping artifact download."
    } else {
      Write-Host "Downloading wheels artifact via GitHub CLI..."
      $artifactRoot = Join-Path $ROOT "dist"
      New-Item -ItemType Directory -Path $artifactRoot -Force | Out-Null
      $zipPath = Join-Path $artifactRoot "wheels-win_amd64-cp311.zip"
      Remove-Item $zipPath -ErrorAction SilentlyContinue
      gh run download --name wheels-win_amd64-cp311 --dir $artifactRoot -L 1
      Ensure-Success -Message "GitHub artifact download failed." -Hint "Убедитесь, что авторизованы в GitHub CLI и workflow завершился успешно."
      if (Test-Path $zipPath) {
        Write-Host "Extracting wheels artifact..."
        Expand-Archive $zipPath -DestinationPath $artifactRoot -Force
        $downloadedWheels = Join-Path $artifactRoot "wheels"
        if (-not (Test-Path $downloadedWheels)) {
          Throw-WithHint -Message "Wheels artifact not found after extraction." -Hint "Проверьте содержимое wheels-win_amd64-cp311.zip."
        }
        if (-not (Test-Path $WheelsDir)) {
          New-Item -ItemType Directory -Path $WheelsDir -Force | Out-Null
        }
        Get-ChildItem -Path $WheelsDir -Filter '*.whl' -File -Recurse -ErrorAction SilentlyContinue | Remove-Item -Force
        Copy-Item -Path (Join-Path $downloadedWheels '*') -Destination $WheelsDir -Recurse -Force
      } else {
        Throw-WithHint -Message "Wheels artifact not found after download." -Hint "Запустите Build offline wheels workflow и повторите обновление."
      }
    }
  }

  if (-not (Test-Path $WheelsDir -PathType Container)) {
    Throw-WithHint -Message "Offline wheels directory not found: $WheelsDir." -Hint "1) Скачайте wheels-win_amd64-cp311.zip из GitHub Actions; 2) Распакуйте в указанный путь или передайте -WheelsDir."
  }

  if (-not (Get-ChildItem -Path $WheelsDir -Filter '*.whl' -File -Recurse | Select-Object -First 1)) {
    Throw-WithHint -Message "No wheel files detected in $WheelsDir." -Hint "Распакуйте wheels-win_amd64-cp311.zip и повторите запуск."
  }

  Write-Host "Installing dependencies from offline bundle..."
  & (Join-Path $ROOT "scripts/offline_install.ps1") -WheelsDir $WheelsDir
  Ensure-Success -Message "Offline dependency installation failed." -Hint "Review the log and ensure the offline wheel bundle is up to date."

  if (-not (Test-Path ".\\.env") -and (Test-Path ".\\.env.example")) {
    Write-Host "Creating .env from template..."
    Copy-Item .env.example .env
  }

  Write-Host "Ensuring var directory exists..."
  New-Item -ItemType Directory -Path .\var -Force | Out-Null

  Write-Host "Running database migrations (alembic upgrade head)..."
  alembic upgrade head
  Ensure-Success -Message "Database migrations failed." -Hint "Check the log for Alembic errors or run alembic upgrade head manually."

  Write-Host "Running database health check..."
  python scripts\db_check.py
  if ($LASTEXITCODE -ne 0) {
    Throw-WithHint -Message "Database health check reported issues." -Hint "Run alembic upgrade head and review scripts/db_check.py output."
  }

  $botTokenLine = Select-String -Path .env -Pattern '^BOT_TOKEN=' -SimpleMatch -ErrorAction SilentlyContinue | Select-Object -First 1
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

  Write-Host "Bot is running… (Ctrl+C to stop)" -ForegroundColor Green
  Write-Host "Log: $logPath"
  python -m app.main
  if ($LASTEXITCODE -ne 0) {
    Throw-WithHint -Message "Bot exited with a non-zero code." -Hint "Review the log for runtime errors."
  }
}
catch {
  $failed = $true
  $errorMessage = $_.Exception.Message
  if ($_.Exception.Data.Contains("Hint")) {
    $hintMessage = [string]$_.Exception.Data["Hint"]
  }
  Write-Error $errorMessage
  if ($hintMessage) {
    Write-Host "Hint: $hintMessage" -ForegroundColor Yellow
  }
}
finally {
  try {
    Stop-Transcript | Out-Null
  } catch {
    # ignore transcript errors
  }

  if ($failed) {
    Write-Host "Update failed. See log: $logPath" -ForegroundColor Red
    if (-not $hintMessage) {
      Write-Host "Частое решение: скачайте wheels-win_amd64-cp311.zip из GitHub Actions и распакуйте его в указанный каталог." -ForegroundColor Yellow
    }
    exit 1
  } else {
    exit 0
  }
}
