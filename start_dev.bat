@echo off
setlocal

REM ===== Определяем папку, где лежит батник =====
set "BASE_DIR=%~dp0"
REM Убираем завершающий слэш, если есть
set "BASE_DIR=%BASE_DIR:~0,-1%"

REM ===== Пути к подпапкам =====
set "BOT_DIR=%BASE_DIR%"
set "TUNNEL_DIR=%BASE_DIR%\tunnel"

REM ===== Запуск =====
echo [INFO] Папка проекта: %BASE_DIR%

REM Окно 1 — бот
start "BOT" cmd /k "cd /d "%BOT_DIR%" && python run.py"

REM Окно 2 — туннель (Node.js)
start "LT" cmd /k "cd /d "%TUNNEL_DIR%" && node tunnel.js"

echo [INFO] Запущены BOT и LT. Не закрывай окна во время работы.
pause
