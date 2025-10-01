param(
  [string]$WheelsDir = (Join-Path (Split-Path -Parent $PSScriptRoot) "wheels")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path $WheelsDir)) {
  throw "Wheels directory not found: $WheelsDir"
}

$resolvedWheels = (Resolve-Path $WheelsDir).Path
Write-Host "Using wheels from: $resolvedWheels"

if (-not (Get-Command pip -ErrorAction SilentlyContinue)) {
  throw "Activate your venv first (.\\.venv\\Scripts\\Activate.ps1)"
}

Write-Host "Installing project requirements..."
$requirementsPath = Join-Path (Split-Path -Parent $PSScriptRoot) "requirements.txt"
$manifestPath = Join-Path (Split-Path -Parent $PSScriptRoot) "wheels-packages.txt"
& pip install --isolated --no-index --find-links $resolvedWheels `
  -r $requirementsPath `
  -r $manifestPath

$groups = @(
  @("typing_extensions==4.12.2", "pydantic_core==2.23.4", "pydantic==2.9.2", "pydantic-settings==2.3.4", "greenlet==3.0.3"),
  @("SQLAlchemy==2.0.32", "alembic==1.13.2", "python-dotenv==1.0.1"),
  @("aiogram==3.22.0", "magic_filter==1.0.12", "aiofiles==23.2.1", "aiosqlite==0.21.0"),
  @("attrs==24.2.0", "multidict==6.0.5", "frozenlist==1.4.1", "yarl==1.9.4", "aiosignal==1.3.1"),
  @("aiohttp==3.9.5"),
  @("APScheduler==3.10.4", "tzlocal==5.3.1", "tzdata==2025.1", "pytz==2025.2", "six==1.17.0"),
  @("httpx==0.27.2", "httpcore==1.0.9", "anyio==4.11.0", "sniffio==1.3.1", "h11==0.16.0"),
  @("reportlab==4.2.2", "pillow==10.4.0")
)

foreach ($group in $groups) {
  if ($group.Count -eq 0) {
    continue
  }
  Write-Host ("Ensuring packages: {0}" -f ($group -join ", "))
  $args = @("--isolated", "--no-index", "--find-links", $resolvedWheels) + $group
  & pip install @args
}

$requiredPackages = @("SQLAlchemy", "alembic", "aiosqlite", "aiogram", "python-dotenv")
foreach ($pkg in $requiredPackages) {
  & pip show $pkg > $null 2>&1
  if ($LASTEXITCODE -ne 0) {
    throw "Package $pkg is missing after offline install"
  }
}

Write-Host "Offline install: done"
