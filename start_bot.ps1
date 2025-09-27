param(
  [switch]$NoVenv  # если хочешь запустить глобальным python
)

Write-Host "`n===============================" -ForegroundColor Cyan
Write-Host " апуск Telegram-бота" -ForegroundColor Cyan
Write-Host "===============================" -ForegroundColor Cyan

if (-not $NoVenv -and (Test-Path .\.venv\Scripts\Activate.ps1)) {
  Write-Host " ктивирую venv..."
  . .\.venv\Scripts\Activate.ps1
} else {
  Write-Warning " venv не найден или отключён флагом -NoVenv  запускаю глобальный Python."
}

# апуск
python .\run.py
