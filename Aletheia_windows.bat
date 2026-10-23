@echo off
rem Aletheia - one-step installer and launcher (Windows).
rem Double-click this file. The first run creates a private environment (.venv)
rem in this folder and installs Aletheia (internet connection needed).
rem The following runs only start the app.
setlocal
cd /d "%~dp0"

rem --- Make sure the project files (pyproject.toml) are next to this installer. ---
rem If only this file was downloaded, fetch the whole project from GitHub first.
if exist "pyproject.toml" goto have_project
if exist "Aletheia-main\pyproject.toml" goto enter_project
set "ZIPURL=https://github.com/aperalbom/Aletheia/archive/refs/heads/main.zip"
if defined ALETHEIA_ZIP_URL set "ZIPURL=%ALETHEIA_ZIP_URL%"
echo The Aletheia project files were not found next to this installer.
echo Downloading Aletheia from GitHub ^(internet connection needed^) ...
powershell -NoProfile -Command "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%ZIPURL%' -OutFile 'Aletheia_download.zip' } catch { exit 1 }"
if errorlevel 1 (
  echo Download failed. Download the whole project instead: open
  echo https://github.com/aperalbom/Aletheia , choose Code - Download ZIP, unzip it,
  echo and double-click Aletheia_windows.bat inside the unzipped folder.
  pause
  exit /b 1
)
powershell -NoProfile -Command "try { Expand-Archive -Path 'Aletheia_download.zip' -DestinationPath '.' -Force } catch { exit 1 }"
if errorlevel 1 (
  echo Could not unzip the download. Unzip Aletheia_download.zip by hand and run
  echo Aletheia_windows.bat from inside the unzipped folder.
  pause
  exit /b 1
)
del "Aletheia_download.zip" >nul 2>&1
:enter_project
if not exist "Aletheia-main\pyproject.toml" (
  echo The downloaded project was not found. Download the whole project from
  echo https://github.com/aperalbom/Aletheia ^(Code - Download ZIP^) and try again.
  pause
  exit /b 1
)
cd /d "Aletheia-main"
:have_project

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
