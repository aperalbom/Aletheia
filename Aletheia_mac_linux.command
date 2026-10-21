#!/usr/bin/env bash
# Aletheia - one-step installer and launcher (macOS and Linux).
#   Run from Terminal:   bash Aletheia_mac_linux.command
# The first run creates a private environment (.venv) in this folder and installs
# Aletheia (it needs an internet connection). The following runs only start the app.
cd "$(dirname "$0")" || exit 1

pause_exit() { echo; read -r -p "Press Enter to close this window..." _; exit "${1:-1}"; }

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && \
     "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Aletheia needs Python 3.10 or later, and none was found."
  echo "Install it from https://www.python.org/downloads/ and run this file again."
  pause_exit 1
fi
echo "Using $($PY --version) ($(command -v $PY))"

if [ ! -x .venv/bin/python ]; then
  echo "Creating the environment (.venv) ..."
  "$PY" -m venv .venv || { echo "Could not create the environment."; pause_exit 1; }
fi
VPY=".venv/bin/python"

if ! "$VPY" -c "import dash, pandas, scipy, aletheia" >/dev/null 2>&1; then
  echo "Installing Aletheia (first run only, a few minutes) ..."
  "$VPY" -m pip install --upgrade pip setuptools wheel || { echo "pip upgrade failed (check the internet connection)."; pause_exit 1; }
  if ! "$VPY" -m pip install -e ".[full]"; then
    echo "The optional PDF-report packages could not be installed; installing the core only ..."
    "$VPY" -m pip install -e . || { echo "Installation failed."; pause_exit 1; }
  fi
fi

echo "Starting Aletheia. Your browser will open at http://localhost:8050 (close this window to stop)."
"$VPY" -m aletheia.app
pause_exit $?
