@echo off
setlocal
chcp 65001 >nul

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found in PATH. Please install Python 3.10+ and add to PATH.
  pause
  exit /b 1
)

python -X utf8 "scripts\sync_env.py"
if errorlevel 1 (
  echo [ERROR] Sync failed. See messages above.
  pause
  exit /b 1
)

echo [OK] .env synchronized with .env.example
pause
