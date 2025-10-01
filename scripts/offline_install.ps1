param(
  [string]$WheelsDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $WheelsDir -or [string]::IsNullOrWhiteSpace($WheelsDir)) {
  if ($env:WHEELS_DIR) {
    $WheelsDir = $env:WHEELS_DIR
  } else {
    $WheelsDir = Join-Path (Split-Path -Parent $PSScriptRoot) "wheels"
  }
}

if (-not (Get-Command pip -ErrorAction SilentlyContinue)) {
  throw "Activate your venv first (.\\.venv\\Scripts\\Activate.ps1)"
}

if (-not (Test-Path $WheelsDir -PathType Container)) {
  throw "Offline wheels directory not found: $WheelsDir`nРаспакуйте артефакт wheels-win_amd64-cp311.zip в $WheelsDir или передайте -WheelsDir."
}

$wheelFiles = Get-ChildItem -Path $WheelsDir -Filter '*.whl' -File -Recurse -ErrorAction SilentlyContinue
if (-not $wheelFiles) {
  throw "В каталоге $WheelsDir не найдено файлов .whl`nРаспакуйте wheels-win_amd64-cp311.zip и повторите установку."
}

$resolvedWheels = (Resolve-Path $WheelsDir).Path
Write-Host "Using wheels from: $resolvedWheels"

$requirementsPath = Join-Path (Split-Path -Parent $PSScriptRoot) "requirements.txt"
$manifestPath = Join-Path (Split-Path -Parent $PSScriptRoot) "wheels-packages.txt"

Write-Host "Installing project requirements from offline bundle..."
& pip install --isolated --no-index --find-links $resolvedWheels `
  -r $requirementsPath `
  -r $manifestPath

$requiredPackages = @("SQLAlchemy", "alembic", "aiosqlite", "aiogram", "python-dotenv")
$missing = @()
foreach ($pkg in $requiredPackages) {
  & pip show $pkg > $null 2>&1
  if ($LASTEXITCODE -ne 0) {
    $missing += $pkg
  }
}

if ($missing.Count -gt 0) {
  throw "Package(s) missing after offline install: $($missing -join ', ')`nПроверьте содержимое каталога $resolvedWheels."
}

Write-Host "Offline install: done ($($requiredPackages.Count) packages verified)."
