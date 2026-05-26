// electron/main.js (CommonJS)
const { app, BrowserWindow, ipcMain, Notification, dialog, Tray, Menu, nativeImage } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;
const DEV_PORT = process.env.ELECTRON_DEV_PORT || '3001';

// Register custom protocol for deep-linking
if (process.defaultApp) {
  if (process.argv.length >= 2) {
    app.setAsDefaultProtocolClient('scheduler-ai', process.execPath, [path.resolve(process.argv[1])]);
  }
} else {
  app.setAsDefaultProtocolClient('scheduler-ai');
}

// If you run the backend separately, set BACKEND_URL (default below)
const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:5001';

// ---------------------------------------------------------------------------
// API secrets — load bundled defaults + optional user overrides
// ---------------------------------------------------------------------------
let bundledSecrets = {};
try {
  bundledSecrets = require('./secrets');
} catch (_) {
  // secrets.js is optional (gitignored)
}

// Allow users to override keys at runtime by dropping a secrets.json into
// ~/Library/Application Support/scheduler-ai/  (macOS)
let userSecrets = {};
if (app.isReady && typeof app.isReady === 'function' && app.isReady()) {
  try {
    const userSecretsPath = path.join(app.getPath('userData'), 'secrets.json');
    if (fs.existsSync(userSecretsPath)) {
      userSecrets = JSON.parse(fs.readFileSync(userSecretsPath, 'utf-8'));
    }
  } catch (_) {}
} else {
  // Defer until app is ready if called before ready
  app.whenReady().then(() => {
    try {
      const userSecretsPath = path.join(app.getPath('userData'), 'secrets.json');
      if (fs.existsSync(userSecretsPath)) {
        userSecrets = JSON.parse(fs.readFileSync(userSecretsPath, 'utf-8'));
      }
    } catch (_) {}
  });
}

function getSecret(key) {
  // Priority: process.env > user secrets.json > bundled secrets.js
  return process.env[key] || userSecrets[key] || bundledSecrets[key] || '';
}

const GROQ_API_KEY = getSecret('GROQ_API_KEY');
const POLL_MS = 60_000; // poll backend for due reminders every 60s (main process)

// Track alarms that are currently ringing (id -> timer)
const ringing = new Map();
// Track reminders already notified (to avoid duplicate popups across polls)
const notified = new Set();

let win;
let tray = null;
let backendProcess = null;
let backendRestartCount = 0;
const MAX_BACKEND_RESTARTS = 3;
const LOG_PATH = path.join(app.getPath('userData'), 'backend.log');

// ---------------------------------------------------------------------------
// Backend discovery (dev vs packaged)
// ---------------------------------------------------------------------------

function getBackendPaths() {
  if (isDev) {
    const projectRoot = path.join(__dirname, '..', '..');
    const venvPython = path.join(projectRoot, '.venv', 'bin', 'python');
    return {
      root: projectRoot,
      python: fs.existsSync(venvPython) ? venvPython : 'python3',
      appPy: path.join(projectRoot, 'app.py'),
    };
  }

  // Packaged mode: backend lives in app resources, but we need a writable copy
  // because macOS .app bundles are read-only.
  const bundledBackend = path.join(process.resourcesPath, 'backend');
  const writableBackend = path.join(app.getPath('userData'), 'backend');
  const venvPython = path.join(writableBackend, '.venv', 'bin', 'python');

  return {
    bundledRoot: bundledBackend,
    root: writableBackend,
    python: venvPython,
    appPy: path.join(writableBackend, 'app.py'),
  };
}

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.name === '__pycache__') continue;
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

function findSuitablePython() {
  // The backend uses Python 3.10+ syntax (e.g. str | None).
  // Search for a recent Python in common locations.
  const candidates = [
    process.env.SCHEDULER_PYTHON,
    '/usr/local/bin/python3',
    '/opt/homebrew/bin/python3',
    '/Library/Frameworks/Python.framework/Versions/3.13/bin/python3',
    '/Library/Frameworks/Python.framework/Versions/3.12/bin/python3',
    '/Library/Frameworks/Python.framework/Versions/3.11/bin/python3',
    '/Library/Frameworks/Python.framework/Versions/3.10/bin/python3',
    'python3.13',
    'python3.12',
    'python3.11',
    'python3.10',
    'python3',
  ].filter(Boolean);

  for (const py of candidates) {
    try {
      const out = require('child_process').execSync(`"${py}" --version 2>&1`, { encoding: 'utf-8', timeout: 3000 }).trim();
      const m = out.match(/Python\s+(\d+)\.(\d+)/);
      if (m) {
        const major = parseInt(m[1], 10);
        const minor = parseInt(m[2], 10);
        if (major > 3 || (major === 3 && minor >= 10)) {
          console.log('[Main] Found suitable Python:', py, '->', out);
          return py;
        }
      }
    } catch (_) {
      // try next candidate
    }
  }
  console.warn('[Main] WARNING: No Python 3.10+ found. Falling back to python3 — venv creation may fail.');
  return 'python3';
}

async function ensureBackendReady(paths) {
  if (isDev) return; // dev uses project root directly

  const needsCopy = !fs.existsSync(paths.root) || !fs.existsSync(paths.appPy);
  const needsVenv = !fs.existsSync(paths.python);

  if (needsCopy) {
    console.log('[Main] Copying bundled backend to writable location:', paths.root);
    if (fs.existsSync(paths.root)) {
      fs.rmSync(paths.root, { recursive: true, force: true });
    }
    copyDir(paths.bundledRoot, paths.root);
  }

  if (needsVenv || needsCopy) {
    console.log('[Main] Creating Python venv for backend...');
    const systemPython = findSuitablePython();
    await new Promise((resolve, reject) => {
      const p = spawn(systemPython, ['-m', 'venv', path.join(paths.root, '.venv')], {
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      p.stdout.on('data', (d) => console.log('[Venv]', d.toString().trim()));
      p.stderr.on('data', (d) => console.error('[Venv]', d.toString().trim()));
      p.on('exit', (code) => {
        if (code === 0) resolve();
        else reject(new Error(`venv creation exited with code ${code}`));
      });
    });

    console.log('[Main] Installing backend requirements...');
    const pip = path.join(paths.root, '.venv', 'bin', 'pip');
    await new Promise((resolve, reject) => {
      const p = spawn(pip, ['install', '-r', path.join(paths.root, 'requirements.txt')], {
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      p.stdout.on('data', (d) => console.log('[Pip]', d.toString().trim()));
      p.stderr.on('data', (d) => console.error('[Pip]', d.toString().trim()));
      p.on('exit', (code) => {
        if (code === 0) resolve();
        else reject(new Error(`pip install exited with code ${code}`));
      });
    });
    console.log('[Main] Backend venv ready');
  }
}

function startBackend() {
  if (process.env.BACKEND_URL && process.env.BACKEND_URL !== BACKEND_URL) {
    console.log('[Main] Using external backend at', process.env.BACKEND_URL);
    return Promise.resolve();
  }

  const paths = getBackendPaths();

  return ensureBackendReady(paths).then(() => {
    console.log('[Main] Starting backend:', paths.python, paths.appPy);
    const backendEnv = { ...process.env, PYTHONUNBUFFERED: '1' };
    if (GROQ_API_KEY) {
      backendEnv.GROQ_API_KEY = GROQ_API_KEY;
      console.log('[Main] Passing GROQ_API_KEY to backend');
    }

    const logStream = fs.createWriteStream(LOG_PATH, { flags: 'a' });
    const ts = () => new Date().toISOString();

    backendProcess = spawn(paths.python, [paths.appPy], {
      cwd: paths.root,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: backendEnv,
    });

    backendProcess.stdout.on('data', (d) => {
      const line = d.toString();
      console.log('[Backend]', line.trim());
      logStream.write(`[${ts()}] ${line}`);
    });
    backendProcess.stderr.on('data', (d) => {
      const line = d.toString();
      console.error('[Backend]', line.trim());
      logStream.write(`[${ts()}] ERR ${line}`);
    });

    backendProcess.on('exit', (code, signal) => {
      logStream.end();
      console.log('[Main] Backend exited with code', code, 'signal', signal);
      backendProcess = null;
      if (code !== 0 && code !== null && backendRestartCount < MAX_BACKEND_RESTARTS) {
        backendRestartCount++;
        console.log(`[Main] Restarting backend in 3s (attempt ${backendRestartCount}/${MAX_BACKEND_RESTARTS})...`);
        setTimeout(() => startBackend().catch(() => {}), 3000);
      } else if (code !== 0 && code !== null) {
        if (!isDev) {
          dialog.showErrorBox('Backend Error', `The Scheduler AI backend exited unexpectedly (code ${code}).\n\nCheck logs at:\n${LOG_PATH}`);
        }
      }
    });

    return new Promise((resolve) => {
      let attempts = 0;
      const check = async () => {
        attempts++;
        try {
          const res = await fetch(`${BACKEND_URL}/health`, { method: 'GET' });
          if (res.ok) {
            console.log('[Main] Backend is ready');
            backendRestartCount = 0;
            resolve();
            return;
          }
        } catch (_) {}
        if (attempts >= 60) {
          console.log('[Main] Backend health check timed out');
          if (!isDev) {
            dialog.showErrorBox('Startup Error', `The Scheduler AI backend failed to start within 30 seconds.\n\nCheck logs at:\n${LOG_PATH}`);
          }
          resolve();
          return;
        }
        setTimeout(check, 500);
      };
      check();
    });
  });
}

function stopBackend() {
  if (!backendProcess) return;
  console.log('[Main] Stopping backend');
  backendProcess.kill('SIGTERM');
  const proc = backendProcess;
  setTimeout(() => {
    try {
      if (proc && !proc.killed) {
        console.log('[Main] Backend did not exit gracefully, forcing SIGKILL');
        proc.kill('SIGKILL');
      }
    } catch (_) {}
  }, 2000);
  backendProcess = null;
}

// ---------------------------------------------------------------------------
// macOS Menubar Tray
// ---------------------------------------------------------------------------

function getTrayIconPath() {
  const iconPath = path.join(__dirname, 'assets', 'trayTemplate.png');
  if (fs.existsSync(iconPath)) return iconPath;
  return path.join(__dirname, 'assets', 'icon.png');
}

async function getNextAppointmentText() {
  try {
    const res = await fetch(`${BACKEND_URL}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'next_upcoming' }),
    });
    const json = await res.json();
    if (json && json.appointment) {
      const a = json.appointment;
      const title = a.title || a.description || 'Untitled';
      const d = a.date;
      const t = a.start_time ? a.start_time.slice(0, 5) : '';
      return `${title} — ${d}${t ? ' at ' + t : ''}`;
    }
    return 'No upcoming appointments';
  } catch (_) {
    return 'Scheduler AI';
  }
}

async function updateTray() {
  if (!tray) return;
  const nextText = await getNextAppointmentText();
  tray.setToolTip(nextText);
}

function createTray() {
  const icon = nativeImage.createFromPath(getTrayIconPath());
  if (icon.isEmpty()) {
    console.warn('[Main] Tray icon not found, skipping tray');
    return;
  }
  tray = new Tray(icon);
  tray.setToolTip('Scheduler AI');

  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Show Scheduler AI',
      click: () => {
        if (win && !win.isDestroyed()) {
          win.show();
          win.focus();
        } else {
          createWindow();
        }
      },
    },
    { type: 'separator' },
    {
      label: 'Refresh',
      click: () => updateTray(),
    },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => {
        stopBackend();
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(contextMenu);

  tray.on('click', () => {
    if (win && !win.isDestroyed()) {
      if (win.isVisible()) {
        win.hide();
      } else {
        win.show();
        win.focus();
      }
    } else {
      createWindow();
    }
  });

  updateTray();
}

function createWindow() {
  win = new BrowserWindow({
    width: 1200,
    height: 800,
    title: 'Scheduler AI',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  if (isDev) {
    win.loadURL(`http://localhost:${DEV_PORT}`);
    win.webContents.openDevTools({ mode: 'detach' });
  } else {
    win.loadFile(path.join(__dirname, '..', 'build', 'index.html'));
  }
}

// Resolve an alarm sound (custom file if present, else macOS built-in)
function alarmSoundPath() {
  const custom = path.join(__dirname, 'assets', 'alarm.m4a'); // you can drop your own file here
  if (fs.existsSync(custom)) return custom;

  // System sounds (any that exists)
  const candidates = [
    '/System/Library/Sounds/Basso.aiff',
    '/System/Library/Sounds/Glass.aiff',
    '/System/Library/Sounds/Blow.aiff',
  ];
  return candidates.find(fs.existsSync) || null;
}

function playAlarmOnce() {
  const file = alarmSoundPath();
  if (!file) {
    // Fallback: system beep
    require('electron').shell.beep();
    return;
  }
  // Use macOS 'afplay' to play the sound without blocking
  const p = spawn('afplay', [file], { detached: true, stdio: 'ignore' });
  p.unref();
}

function startAlarm(id, repeats = 3, gapMs = 5000) {
  if (ringing.has(id)) return;

  let count = 0;
  playAlarmOnce();
  const tm = setInterval(() => {
    count += 1;
    if (count >= repeats) {
      clearInterval(tm);
      ringing.delete(id);
      return;
    }
    playAlarmOnce();
  }, gapMs);

  ringing.set(id, tm);
}

function stopAlarm(id) {
  const tm = ringing.get(id);
  if (tm) {
    clearInterval(tm);
    ringing.delete(id);
  }
}

function showNativeReminder(r) {
  if (!r || notified.has(r.id)) return;
  notified.add(r.id);

  const title = r.title || 'Reminder';
  const infoParts = [];
  if (r.appt_title) infoParts.push(r.appt_title);
  const d = Number(r.appt_duration_minutes);
  if (!Number.isNaN(d) && d > 0) infoParts.push(`${d} min`);
  const when = [r.date, r.time].filter(Boolean).join(' ');
  const body = [when, infoParts.join(' • ')].filter(Boolean).join('\n') || 'You have a due reminder';

  // We'll play our own sound, so set silent:true here
  const n = new Notification({ title, body, silent: true });

  // Start ringing when the notification shows
  n.on('show', () => startAlarm(r.id));

  const sendDismiss = () => {
    stopAlarm(r.id);
    if (win && !win.isDestroyed()) {
      win.webContents.send('reminder:dismissed', r.id);
    }
  };

  n.on('click', () => {
    if (win && !win.isDestroyed()) {
      win.show();
      win.focus();
      // Open the appointment/details view first (renderer should handle this)
      if (r && r.appointment_id) {
        win.webContents.send('appointment:open', {
          id: r.appointment_id,
          title: r.appt_title || r.title || 'Appointment',
          start: r.appt_start || null,
          end: r.appt_end || null,
          date: r.date || null,
          time: r.time || null,
        });
      } else {
        // Fallback: navigate to the appointments/agenda view
        win.webContents.send('navigate', { path: '/appointments' });
      }
    }
    // After surfacing the window/navigation, mark it dismissed (stops alarm + tell renderer)
    sendDismiss();
  });

  n.on('close', sendDismiss);

  n.show();

  // Also inform renderer (so your SPA can toast it if open)
  if (win && !win.isDestroyed()) {
    win.webContents.send('reminder:notify', r);
  }
}

async function pollDueReminders() {
  try {
    // Node 18+ has global fetch
    const res = await fetch(`${BACKEND_URL}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'reminders_due' }),
    });
    const json = await res.json();
    if (json && Array.isArray(json.due_reminders)) {
      json.due_reminders.forEach(showNativeReminder);
    }
  } catch (e) {
    // Ignore transient network errors
  }
}

// Pre-meeting notifications: show a banner 15 min before each upcoming appointment
const notifiedAppointments = new Set();

async function pollUpcomingAppointments() {
  try {
    const today = new Date().toISOString().slice(0, 10);
    const res = await fetch(`${BACKEND_URL}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'list_by_date', date: today }),
    });
    const json = await res.json();
    if (!json || !Array.isArray(json.appointments)) return;

    const now = Date.now();
    for (const appt of json.appointments) {
      if (!appt.start_time) continue;
      const key = `pre-${appt.id}`;
      if (notifiedAppointments.has(key)) continue;

      const start = new Date(`${appt.date}T${appt.start_time}`);
      const minsUntil = (start.getTime() - now) / 60000;
      if (minsUntil > 0 && minsUntil <= 15) {
        notifiedAppointments.add(key);
        const n = new Notification({
          title: 'Upcoming Appointment',
          body: `${appt.title || appt.description || 'Appointment'} at ${appt.start_time.slice(0, 5)}`,
          silent: false,
        });
        n.on('click', () => {
          if (win && !win.isDestroyed()) {
            win.show();
            win.focus();
            win.webContents.send('appointment:open', {
              id: appt.id,
              title: appt.title || appt.description || 'Appointment',
              date: appt.date,
              time: appt.start_time,
            });
          }
        });
        n.show();
      }
    }
  } catch (e) {
    // Ignore transient errors
  }
}

app.whenReady().then(async () => {
  try {
    await startBackend();
  } catch (err) {
    console.error('[Main] Failed to start backend:', err);
    if (!isDev) {
      dialog.showErrorBox('Backend Error', `Failed to start backend: ${err.message}\n\nCheck logs at:\n${LOG_PATH}`);
    }
  }
  createWindow();
  createTray();

  // Application menu with keyboard shortcuts
  const appMenu = Menu.buildFromTemplate([
    {
      label: 'Scheduler AI',
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        { role: 'quit', accelerator: 'Cmd+Q' },
      ],
    },
    {
      label: 'File',
      submenu: [
        {
          label: 'New Appointment',
          accelerator: 'Cmd+N',
          click: () => {
            if (win && !win.isDestroyed()) {
              win.webContents.send('menu:new-appointment');
            }
          },
        },
        { type: 'separator' },
        {
          label: 'Export Backup...',
          accelerator: 'Cmd+Shift+E',
          click: () => {
            if (win && !win.isDestroyed()) win.webContents.send('menu:export-backup');
          },
        },
        {
          label: 'Import Backup...',
          accelerator: 'Cmd+Shift+I',
          click: () => {
            if (win && !win.isDestroyed()) win.webContents.send('menu:import-backup');
          },
        },
        { type: 'separator' },
        {
          label: 'Print to PDF',
          accelerator: 'Cmd+P',
          click: () => {
            if (win && !win.isDestroyed()) win.webContents.send('menu:print-pdf');
          },
        },
      ],
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
      ],
    },
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' },
        { role: 'close' },
      ],
    },
  ]);
  Menu.setApplicationMenu(appMenu);

  ipcMain.on('notify:reminder', (_evt, r) => showNativeReminder(r));
  ipcMain.on('alarm:stop', (_evt, id) => stopAlarm(id));

  // Native macOS integration handlers
  function getNativeBinaryPath(name) {
    if (isDev) {
      return path.join(__dirname, '..', '..', 'native', 'macOS-helpers', '.build', 'debug', name);
    }
    return path.join(process.resourcesPath, 'native', name);
  }

  function runNativeBinary(name, args = []) {
    const binaryPath = getNativeBinaryPath(name);
    if (!fs.existsSync(binaryPath)) {
      console.warn(`[Main] Native binary not found: ${binaryPath}`);
      return;
    }
    const env = { ...process.env, BACKEND_URL };
    const child = spawn(binaryPath, args, { env, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (d) => { stdout += d.toString(); console.log(`[${name}]`, d.toString().trim()); });
    child.stderr.on('data', (d) => { stderr += d.toString(); console.error(`[${name}]`, d.toString().trim()); });
    child.on('exit', (code) => {
      if (win && !win.isDestroyed()) {
        win.webContents.send('native:sync-result', { binary: name, code, stdout: stdout.trim(), stderr: stderr.trim() });
      }
    });
  }

  ipcMain.on('sync:calendar', () => runNativeBinary('calendar-sync', ['--push']));
  ipcMain.on('index:spotlight', () => runNativeBinary('spotlight-index', ['--all']));

  // Print to PDF
  ipcMain.handle('print:to-pdf', async () => {
    if (!win || win.isDestroyed()) return { error: 'No window' };
    try {
      const pdfPath = path.join(app.getPath('downloads'), `Scheduler-AI-${Date.now()}.pdf`);
      const data = await win.webContents.printToPDF({ pageSize: 'A4' });
      fs.writeFileSync(pdfPath, data);
      return { success: true, path: pdfPath };
    } catch (err) {
      return { error: err.message };
    }
  });

  // Backup / restore
  ipcMain.handle('backup:export', async () => {
    const { filePath } = await dialog.showSaveDialog(win, {
      defaultPath: `scheduler-backup-${new Date().toISOString().slice(0, 10)}.json`,
      filters: [{ name: 'JSON', extensions: ['json'] }],
    });
    if (!filePath) return { cancelled: true };
    try {
      const res = await fetch(`${BACKEND_URL}/export`);
      const data = await res.json();
      fs.writeFileSync(filePath, JSON.stringify(data, null, 2), 'utf-8');
      return { success: true, path: filePath };
    } catch (err) {
      return { error: err.message };
    }
  });

  ipcMain.handle('backup:import', async () => {
    const { filePaths } = await dialog.showOpenDialog(win, {
      filters: [{ name: 'JSON', extensions: ['json'] }],
      properties: ['openFile'],
    });
    if (!filePaths || filePaths.length === 0) return { cancelled: true };
    try {
      const raw = fs.readFileSync(filePaths[0], 'utf-8');
      const data = JSON.parse(raw);
      const res = await fetch(`${BACKEND_URL}/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      const result = await res.json();
      return { success: true, result };
    } catch (err) {
      return { error: err.message };
    }
  });

  setInterval(pollDueReminders, POLL_MS);
  pollDueReminders().catch(() => {});

  // Pre-meeting notifications (check every 2 minutes)
  setInterval(pollUpcomingAppointments, 120_000);
  pollUpcomingAppointments().catch(() => {});

  // Update tray tooltip every minute
  setInterval(updateTray, POLL_MS);
  updateTray().catch(() => {});

  app.on('activate', async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      if (!backendProcess) {
        try { await startBackend(); } catch (err) {
          console.error('[Main] Failed to restart backend on activate:', err);
        }
      }
      createWindow();
    }
  });
});

// Deep-link handling (macOS)
app.on('open-url', (event, url) => {
  event.preventDefault();
  console.log('[Main] Deep link opened:', url);
  if (win && !win.isDestroyed()) {
    win.show();
    win.focus();
    const match = url.match(/scheduler-ai:\/\/appointment\/(\d+)/);
    if (match) {
      win.webContents.send('appointment:open', { id: parseInt(match[1], 10) });
    } else {
      win.webContents.send('navigate', { path: '/' });
    }
  }
});

app.on('window-all-closed', () => {
  stopBackend();
  if (process.platform !== 'darwin') app.quit();
});

app.on('will-quit', () => {
  stopBackend();
});
