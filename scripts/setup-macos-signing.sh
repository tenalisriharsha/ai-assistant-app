#!/bin/bash
set -e

echo "=========================================="
echo "  macOS Code Signing Setup for Scheduler AI"
echo "=========================================="
echo ""

# Check for existing signing identities
IDENTITIES=$(security find-identity -v -p codesigning 2>/dev/null | grep -c "valid identities found" || true)
VALID_COUNT=$(security find-identity -v -p codesigning 2>/dev/null | grep -oE '^\s+[0-9]+\)' | wc -l | tr -d ' ')

if [ "$VALID_COUNT" -gt 0 ]; then
  echo "✅ Found $VALID_COUNT signing identity/ies:"
  security find-identity -v -p codesigning 2>/dev/null | grep -E '^\s+[0-9]+\)' || true
  echo ""
  echo "Electron-builder will auto-detect and use these. You're good to go!"
  echo ""
  echo "To build a signed app, run:"
  echo "  cd frontend && npm run electron:build"
  exit 0
fi

echo "❌ No code signing identities found."
echo ""
echo "To create a FREE personal team certificate (for local use):"
echo ""
echo "1. Open Xcode"
echo "2. Go to Xcode → Settings → Accounts (or Cmd+, then Accounts tab)"
echo "3. Click '+' and add your Apple ID"
echo "4. Select your account → Click 'Manage Certificates...'"
echo "5. Click '+' → Add 'Apple Development' certificate"
echo "6. Close Xcode preferences"
echo ""
echo "7. Create a dummy macOS project in Xcode:"
echo "   File → New → Project → macOS → App → Next → any name → Create"
echo "   Then build it once (Cmd+B) — this forces Xcode to create the cert."
echo ""
echo "8. After that, run this script again to verify."
echo ""
echo "──────────────────────────────────────────"
echo "NOTE: Free personal certs are good for local testing only."
echo "For distribution, you need a paid Apple Developer account ($99/yr)"
echo "and a 'Developer ID Application' certificate."
echo "──────────────────────────────────────────"
echo ""

# Offer to open Xcode automatically
read -p "Open Xcode now? (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
  open -a Xcode
  echo "Xcode opened. Follow the steps above, then re-run this script."
fi
