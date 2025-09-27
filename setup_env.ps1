param(
  [switch]$Freeze = $true
)

Write-Host "`n==========================================" -ForegroundColor Cyan
Write-Host "  одготовка окружения (PowerShell)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1) Python
Write-Host " роверка Python..."
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) {
  Write-Error " Python не найден в PATH. станови Python 3.11+ и перезапусти терминал."
  exit 1
}

# 2) venv
if (-not (Test-Path .\.venv\Scripts\Activate.ps1)) {
  Write-Host " Создаю виртуальное окружение .venv ..."
  python -m venv .venv | Out-Null
}
. .\.venv\Scripts\Activate.ps1

# 3) pip + зависимости
Write-Host " бновляю pip..."
python -m pip install --upgrade pip | Out-Null

if (Test-Path .\requirements.txt) {
  Write-Host " станавливаю зависимости из requirements.txt..."
  python -m pip install -r requirements.txt
} else {
  Write-Warning "requirements.txt не найден  пропускаю."
}

# 4) sync .env (не перетирает секреты)
if (Test-Path .\scripts\sync_env.py) {
  Write-Host " Синхронизирую .env из .env.example..."
  python -X utf8 .\scripts\sync_env.py
} elseif (Test-Path .\.env.example -and -not (Test-Path .\.env)) {
  Write-Host " Создаю .env из .env.example (без секретов)..."
  Copy-Item .\.env.example .\.env
}

# 5) DATABASE_URL по умолчанию
$envText = (Get-Content .\.env -Raw -ErrorAction SilentlyContinue)
if ($null -eq $envText -or $envText -notmatch '^DATABASE_URL=') {
  Add-Content .\.env "DATABASE_URL=sqlite:///five_keys.sqlite3"
}

# 6) lock-файл
if ($Freeze) {
  Write-Host " Сохраняю lock-файл зависимостей (requirements.lock)..."
  pip freeze | Set-Content -Encoding UTF8 .\requirements.lock
}

Write-Host "`n==========================================" -ForegroundColor Green
Write-Host " кружение готово" -ForegroundColor Green
Write-Host "python: $(python --version)"
Write-Host "==========================================" -ForegroundColor Green
