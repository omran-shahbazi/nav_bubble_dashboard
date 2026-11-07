#!/bin/bash
# Double-click this file in Finder to start the dashboard (macOS).
# First run installs everything (takes a minute); later runs start in seconds.
# Close this window, or press Ctrl+C in it, to stop the dashboard.

cd "$(dirname "$0")" || exit 1
PORT=8501
URL="http://localhost:$PORT"

RUNNING=$(lsof -tiTCP:$PORT -sTCP:LISTEN 2>/dev/null | head -1)
if [ -n "$RUNNING" ]; then
    RUNNING_DIR=$(lsof -a -p "$RUNNING" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')
    if [ "$RUNNING_DIR" = "$PWD" ]; then
        echo "The dashboard is already running. Opening $URL"
        open "$URL"
        exit 0
    fi
    # Something else (e.g. a copy of the dashboard from another folder) holds the port: stop it.
    echo "Stopping the program on port $PORT (from: ${RUNNING_DIR:-unknown}) ..."
    kill "$RUNNING"
    sleep 2
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python is not installed. Install it from https://www.python.org/downloads/ and run this again."
    read -r -p "Press Enter to close."
    exit 1
fi

if ! .venv/bin/python -c "import streamlit" >/dev/null 2>&1; then
    echo "First run: installing the dashboard's packages..."
    python3 -m venv --clear .venv && .venv/bin/pip install --quiet --disable-pip-version-check -r requirements.txt || {
        echo "Installation failed (see the messages above)."
        read -r -p "Press Enter to close."
        exit 1
    }
fi

echo "Starting the dashboard at $URL"
echo "Keep this window open. Close it or press Ctrl+C to stop."
(sleep 4 && open "$URL") &
exec .venv/bin/python -m streamlit run app.py --server.port $PORT
