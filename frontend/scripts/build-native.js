const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const projectRoot = path.join(__dirname, '..', '..');
const swiftPackageDir = path.join(projectRoot, 'native', 'macOS-helpers');
const outputDir = path.join(__dirname, '..', 'electron', 'assets', 'native');

if (!fs.existsSync(swiftPackageDir)) {
  console.log('[BuildNative] Swift package not found, skipping');
  process.exit(0);
}

console.log('[BuildNative] Building Swift native helpers...');
try {
  execSync('swift build -c release', { cwd: swiftPackageDir, stdio: 'inherit' });
} catch (e) {
  console.error('[BuildNative] Swift build failed:', e.message);
  process.exit(1);
}

fs.mkdirSync(outputDir, { recursive: true });

const binaries = ['calendar-sync', 'spotlight-index'];
for (const bin of binaries) {
  const src = path.join(swiftPackageDir, '.build', 'release', bin);
  const dest = path.join(outputDir, bin);
  if (fs.existsSync(src)) {
    fs.copyFileSync(src, dest);
    console.log(`[BuildNative] Copied ${bin} → ${dest}`);
  } else {
    console.warn(`[BuildNative] Binary not found: ${src}`);
  }
}

console.log('[BuildNative] Done');
