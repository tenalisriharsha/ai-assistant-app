#!/bin/bash
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

# Start backend in background
echo "[dev] Starting backend on port 5001..."
source .venv/bin/activate
PORT=5001 python app.py &
BACKEND_PID=$!

# Cleanup on exit
cleanup() {
  echo "[dev] Stopping backend (PID $BACKEND_PID)..."
  kill "$BACKEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" 2>/dev/null || true
  exit
}
trap cleanup INT TERM EXIT

# Give backend a moment to start
sleep 1

# Start frontend
echo "[dev] Starting frontend..."
cd frontend
npm start
