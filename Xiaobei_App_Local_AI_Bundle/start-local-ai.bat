@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.9 or later is required.
  pause
  exit /b 1
)

python run-public-local-ai.py
if errorlevel 1 echo The local AI sharing service stopped with an error.
pause
