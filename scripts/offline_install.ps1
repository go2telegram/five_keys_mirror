param(
  [string]$WheelsDir = "$(Resolve-Path "$PSScriptRoot\..\wheels")"
)

Write-Host "Using wheels from: $WheelsDir"

# venv must be active; fail fast if not
if (-not (Get-Command pip -ErrorAction SilentlyContinue)) {
  Write-Error "Activate your venv first (.\.venv\Scripts\Activate.ps1)" ; exit 1
}

# 1) aiohttp low level
pip install --isolated --no-index --find-links "$WheelsDir" `
  multidict==6.0.5 yarl==1.9.4 frozenlist==1.4.1 attrs==24.2.0 aiosignal==1.3.1

# 2) aiohttp
pip install --isolated --no-index --find-links "$WheelsDir" aiohttp==3.9.5

# 3) pydantic stack + helpers
pip install --isolated --no-index --find-links "$WheelsDir" `
  typing_extensions==4.12.2 pydantic_core==2.23.4 pydantic==2.9.2 `
  pydantic-settings==2.3.4 greenlet==3.0.3 magic_filter==1.0.12 aiofiles==23.2.1

# 4) project runtime + tooling
pip install --isolated --no-index --find-links "$WheelsDir" `
  SQLAlchemy==2.0.32 alembic==1.13.2 python-dotenv==1.0.1 `
  aiogram==3.22.0 aiosqlite==0.21.0 APScheduler==3.10.4 httpx==0.27.2

Write-Host "Offline install: done"
