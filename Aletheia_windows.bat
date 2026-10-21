@echo off
rem Aletheia - one-step installer and launcher (Windows).
rem Double-click this file. The first run creates a private environment (.venv)
rem in this folder and installs Aletheia (internet connection needed).
rem The following runs only start the app.
setlocal
cd /d "%~dp0"

set "PY="
for %%V in (3.13 3.12 3.11 3.10) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo Aletheia needs Python 3.10 or later, and none was found.
  echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^)
  echo and double-click this file again.
  pause
  exit /b 1
)
echo Using: %PY%

if not exist ".venv\Scripts\python.exe" (
  echo Creating the environment ^(.venv^) ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Could not create the environment.
    pause
    exit /b 1
  )
)
set "VPY=.venv\Scripts\python.exe"

"%VPY%" -c "import dash, pandas, scipy, aletheia" >nul 2>&1
if errorlevel 1 (
  echo Installing Aletheia ^(first run only, a few minutes^) ...
  "%VPY%" -m pip install --upgrade pip setuptools wheel
  if errorlevel 1 (
    echo pip upgrade failed. Check the internet connection.
    pause
    exit /b 1
  )
  "%VPY%" -m pip install -e ".[full]"
  if errorlevel 1 (
    echo The optional PDF-report packages could not be installed; installing the core only ...
    "%VPY%" -m pip install -e .
    if errorlevel 1 (
      echo Installation failed.
      pause
      exit /b 1
    )
  )
)

echo Starting Aletheia. Your browser will open at http://localhost:8050 ^(close this window to stop^).
"%VPY%" -m aletheia.app
pause
