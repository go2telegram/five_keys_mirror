@echo off
setlocal
cd /d "%~dp0.."
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_local.ps1" %*
echo.
echo ===================== DONE =====================
echo Log: .\logs\update_*.log
pause
