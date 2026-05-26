#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "🚀 Scheduler AI — macOS launcher"

# Ensure Python virtual environment
if [ ! -d ".venv" ]; then
    echo "📦 Creating Python virtual environment..."
    python3 -m venv .venv
fi

# Install/update Python dependencies
echo "📦 Installing Python dependencies..."
./.venv/bin/pip install -q -r requirements.txt

# Ensure frontend node_modules
if [ ! -d "frontend/node_modules" ]; then
    echo "📦 Installing frontend dependencies..."
    cd frontend && npm install && cd ..
fi

# Start the desktop app (Electron will auto-launch the Flask backend)
echo "🖥️  Starting Scheduler AI Desktop..."
cd frontend
npm run electron:dev
