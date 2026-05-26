/**
 * Pre-build script: copies the Python backend into frontend/backend/
 * so electron-builder can bundle it as an extraResource.
 */
const fs = require('fs');
const path = require('path');

const projectRoot = path.join(__dirname, '..', '..');
const backendDir = path.join(__dirname, '..', 'backend');

// Files at project root to copy
const rootFiles = [
  'app.py',
  'requirements.txt',
  'appointments.db',
  'crud.py',
  'models.py',
  'database.py',
  'schemas.py',
  'openai_handler.py',
  'nl_creation_flow.py',
  'excel_handler.py',
  'generate_sample_excel.py',
  'inspect_db.py',
];

// Packages (directories) to copy
const packages = [
  'utils',
  'intents',
  'flows',
  'scheduler',
  'handlers',
  'scripts',
];

function rmrf(dir) {
  if (!fs.existsSync(dir)) return;
  fs.rmSync(dir, { recursive: true, force: true });
}

function copyFile(src, dest) {
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(src, dest);
}

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  const entries = fs.readdirSync(src, { withFileTypes: true });
  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.name === '__pycache__') continue;
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
    } else {
      copyFile(srcPath, destPath);
    }
  }
}

console.log('[prebuild-backend] Cleaning', backendDir);
rmrf(backendDir);
fs.mkdirSync(backendDir, { recursive: true });

for (const f of rootFiles) {
  const src = path.join(projectRoot, f);
  if (fs.existsSync(src)) {
    copyFile(src, path.join(backendDir, f));
    console.log('[prebuild-backend] Copied', f);
  }
}

for (const pkg of packages) {
  const src = path.join(projectRoot, pkg);
  if (fs.existsSync(src)) {
    copyDir(src, path.join(backendDir, pkg));
    console.log('[prebuild-backend] Copied package', pkg);
  }
}

console.log('[prebuild-backend] Done');
