@echo off
cd /d "%~dp0"
if not exist .venv (
  echo Creating virtual environment...
  py -3 -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate
fc /b requirements.lock .venv\requirements.lock >nul 2>&1
if errorlevel 1 (
  echo Installing dependencies...
  pip install -q -r requirements.lock && copy /y requirements.lock .venv\requirements.lock >nul
)
echo Starting WaterCaste...
python run_dev.py
pause
