// On newer macOS versions, the plain Electron binary that `npm install`
// downloads into node_modules/electron/dist/Electron.app fails Apple's
// Certificate Transparency signature check (AMFI: "no CMS blob" /
// "Unrecoverable CT signature issue"). Gatekeeper's enforcement daemon
// (syspolicyd) then silently deletes the binary the moment anything tries
// to launch it ("Attempting to move malware to trash... Successfully moved
// malware to trash") — it's not actually malware, just an ad-hoc/dev
// signature that no longer clears current signing requirements.
//
// An ad-hoc local signature (matching the same fix already used for the
// packaged app in postbuild:sign) satisfies the check. Runs automatically
// before `electron:dev` via npm's pre<script> convention; safe to re-run.
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const appPath = path.join(__dirname, '..', 'node_modules', 'electron', 'dist', 'Electron.app');

if (process.platform !== 'darwin') {
  process.exit(0);
}

if (!fs.existsSync(appPath)) {
  console.log('[fix-electron-dev-signing] No Electron.app found yet (npm install will fetch it) — skipping.');
  process.exit(0);
}

try {
  execSync(`codesign --deep --force --sign - "${appPath}"`, { stdio: 'inherit' });
  execSync(`xattr -rd com.apple.quarantine "${appPath}"`, { stdio: 'ignore' });
  console.log('[fix-electron-dev-signing] Electron.app ad-hoc signed.');
} catch (e) {
  console.warn('[fix-electron-dev-signing] Could not sign Electron.app:', e.message);
}
