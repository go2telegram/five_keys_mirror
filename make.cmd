@echo off
REM Minimal make wrapper for Windows without GNU make
REM Usage examples:
REM   make.cmd dry
REM   make.cmd prod TOKEN=123:AA...
set TGT=%1
set ARG=%2
if "%TGT%"=="" set TGT=help
bash -lc "make %TGT% %ARG%"
