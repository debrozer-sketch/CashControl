@echo off
setlocal
cd /d "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"

if exist "%VENV_PY%" goto deps

echo Creating virtual environment...

rem ---- find a suitable Python (py launcher first, then PATH python) ----
set "PYCMD="
py -3.12 -c "print(1)" >nul 2>&1
if not errorlevel 1 set "PYCMD=py -3.12"
if defined PYCMD goto create_venv

py -3.13 -c "print(1)" >nul 2>&1
if not errorlevel 1 set "PYCMD=py -3.13"
if defined PYCMD goto create_venv

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 set "PYCMD=python"
if defined PYCMD goto create_venv

echo [ERROR] Python 3.11+ not found. Install: https://www.python.org/downloads/
pause
exit /b 1

:create_venv
%PYCMD% -m venv .venv
if errorlevel 1 (
  echo [ERROR] venv creation failed.
  pause
  exit /b 1
)

:deps
echo Checking dependencies...
"%VENV_PY%" -m pip install --upgrade pip -q
if errorlevel 1 goto pip_fail
"%VENV_PY%" -m pip install -r requirements.txt -q
if errorlevel 1 goto pip_fail
goto run

:pip_fail
echo [ERROR] dependency install failed. Check internet connection.
pause
exit /b 1

:run
if "%~1"=="--setup-only" (
  echo Setup complete.
  exit /b 0
)

echo Starting SSH terminal...
"%VENV_PY%" -X utf8 main.py
if errorlevel 1 pause
