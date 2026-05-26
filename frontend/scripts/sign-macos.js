const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const appName = 'Scheduler AI.app';
const candidates = [
  path.join(__dirname, '..', 'dist', 'mac-arm64', appName),
  path.join(__dirname, '..', 'dist', 'mac-x64', appName),
  path.join(__dirname, '..', 'dist', 'mac', appName),
];

for (const appPath of candidates) {
  if (fs.existsSync(appPath)) {
    console.log('[Sign] Signing', appPath);
    try {
      execSync(`codesign --deep --force --verify --verbose --sign - "${appPath}"`, { stdio: 'inherit' });
      console.log('[Sign] Done');
    } catch (e) {
      console.error('[Sign] Signing failed:', e.message);
      process.exit(1);
    }

    // Also sign embedded Swift binaries explicitly
    const nativeDir = path.join(appPath, 'Contents', 'Resources', 'native');
    if (fs.existsSync(nativeDir)) {
      const binaries = ['calendar-sync', 'spotlight-index'];
      for (const bin of binaries) {
        const binPath = path.join(nativeDir, bin);
        if (fs.existsSync(binPath)) {
          console.log(`[Sign] Signing embedded binary: ${bin}`);
          try {
            execSync(`codesign --force --sign - "${binPath}"`, { stdio: 'inherit' });
          } catch (e) {
            console.warn(`[Sign] Could not sign ${bin}:`, e.message);
          }
        }
      }
    }

    console.log('[Sign] Stripping quarantine xattr...');
    try {
      execSync(`xattr -rd com.apple.quarantine "${appPath}"`, { stdio: 'inherit' });
      console.log('[Sign] Quarantine stripped');
    } catch (e) {
      console.warn('[Sign] Could not strip quarantine (may need manual xattr -rd):', e.message);
    }

    process.exit(0);
  }
}

console.log('[Sign] No .app bundle found in dist/ (skipping)');
