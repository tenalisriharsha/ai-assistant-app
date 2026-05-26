#!/bin/bash
set -e

# install_macos.sh — Build and install Scheduler AI to /Applications/

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
APP_NAME="Scheduler AI"
ARCH=$(uname -m)

echo "=== Scheduler AI macOS Installer ==="
echo "Architecture: $ARCH"

# Detect the correct build output
if [ "$ARCH" = "arm64" ]; then
    BUILD_DIR="$FRONTEND_DIR/dist/mac-arm64"
    DMG_FILE="$FRONTEND_DIR/dist/${APP_NAME}-0.1.0-arm64.dmg"
else
    BUILD_DIR="$FRONTEND_DIR/dist/mac"
    DMG_FILE="$FRONTEND_DIR/dist/${APP_NAME}-0.1.0.dmg"
fi

APP_BUNDLE="$BUILD_DIR/${APP_NAME}.app"

# Build if not already present
if [ ! -d "$APP_BUNDLE" ]; then
    echo "Building Scheduler AI..."
    cd "$FRONTEND_DIR"
    npm run electron:build
fi

if [ ! -d "$APP_BUNDLE" ]; then
    echo "ERROR: Build failed — $APP_BUNDLE not found"
    exit 1
fi

echo "Installing to /Applications/${APP_NAME}.app ..."

# Remove old installation if present
if [ -d "/Applications/${APP_NAME}.app" ]; then
    echo "Removing existing installation..."
    rm -rf "/Applications/${APP_NAME}.app"
fi

# Copy the .app bundle
cp -R "$APP_BUNDLE" "/Applications/${APP_NAME}.app"

echo "✅ Installed to /Applications/${APP_NAME}.app"
echo ""
echo "Launch with: open '/Applications/${APP_NAME}.app'"
echo ""
echo "NOTE: Since this app is not code-signed, macOS may show a security warning"
echo "on first launch. Right-click the app in /Applications and select 'Open' to"
echo "bypass Gatekeeper."
