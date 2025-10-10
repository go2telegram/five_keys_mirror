@echo off
REM Windows wrapper: forwards all args to Git Bash script
set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%\..
bash "%SCRIPT_DIR%\dev_up.sh" %*
