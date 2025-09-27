$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path .\logs)) { New-Item -ItemType Directory -Path .\logs | Out-Null }
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$log = ".\logs\start_$stamp.log"

Start-Transcript -Path $log -Force | Out-Null
try {
  Write-Host " Старт полного цикла: подготовка + бот" -ForegroundColor Cyan

  if (Test-Path .\setup_env.ps1) {
    Write-Host " setup_env.ps1..."
    . .\setup_env.ps1
  } else {
    Write-Warning "setup_env.ps1 не найден  пропускаю подготовку."
  }

  if (Test-Path .\start_bot.ps1) {
    Write-Host " start_bot.ps1..."
    . .\start_bot.ps1
  } else {
    Write-Error "start_bot.ps1 не найден  бот не будет запущен."
  }

  Write-Host "`n ог запуска: $log" -ForegroundColor Green
} finally {
  Stop-Transcript | Out-Null
}
