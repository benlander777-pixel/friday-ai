#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo
echo "Initializing F.R.I.D.A.Y..."
echo

PY_PID=""
cleanup() {
    if [ -n "$PY_PID" ] && kill -0 "$PY_PID" 2>/dev/null; then
        kill "$PY_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

PYTHON_BIN="python3"
if [ -x ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
fi

echo "Starting backend server..."
"$PYTHON_BIN" server.py &
PY_PID=$!

# Give the server a moment to come up (Electron's main.js also waits/retries
# on its own before loading the UI, so this is just a head start)
sleep 4

echo "Launching FRIDAY interface..."
npx electron . "$@"

echo
echo "FRIDAY closed."
