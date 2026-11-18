@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 exit /b 1
if not exist ".venv\Scripts\python.exe" (
  echo Python environment not found. Please follow README.md first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 -B main.py web --open %*
if errorlevel 1 pause
