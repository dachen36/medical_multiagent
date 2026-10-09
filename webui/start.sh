#!/usr/bin/env bash
# Start the OpenHarness WebUI: backend (FastAPI :8000) + frontend (Vite :5173)
# Usage: ./start.sh [dev|build]
#
# dev   (default): run both in foreground, Ctrl+C stops both
# build: build the frontend to dist/ and serve via FastAPI on :8000

set -euo pipefail

cd "$(dirname "$0")"

MODE="${1:-dev}"

# --- Backend deps -----------------------------------------------------------
if [ ! -d "../.venv" ]; then
    echo "[start] no .venv found in project root; using system python"
fi

# --- Frontend deps ----------------------------------------------------------
if [ ! -d "node_modules" ]; then
    echo "[start] installing frontend dependencies (one-time)..."
    npm install
fi

# --- Mode -------------------------------------------------------------------
if [ "$MODE" = "build" ]; then
    echo "[start] building frontend..."
    npm run build
    echo "[start] starting backend (serves built frontend on :8000)..."
    cd ..
    PYTHONPATH=src:. uv run python -m webui.server.app
    exit 0
fi

# Default: dev mode
echo "[start] dev mode: backend :8000 + frontend :5173"
echo "[start] opening http://localhost:5173 in your browser"

# Trap to clean up both processes
cleanup() {
    echo ""
    echo "[start] shutting down..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Start backend (use -m so relative imports work)
(
    cd ..
    PYTHONPATH=src:. uv run python -m webui.server.app
) &
BACKEND_PID=$!

# Give backend a moment to start
sleep 1

# Start frontend
npm run dev &
FRONTEND_PID=$!

# Wait for either to exit
wait $BACKEND_PID $FRONTEND_PID
