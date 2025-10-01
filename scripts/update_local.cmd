@echo off
set SCRIPT_DIR=%~dp0
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%update_local.ps1" %*
echo.
echo Log files (if any) saved under .\logs
pause
