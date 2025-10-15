// electron/main.js (CommonJS)
const { app, BrowserWindow, ipcMain, Notification } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;
const DEV_PORT = process.env.ELECTRON_DEV_PORT || '3001';

// If you run the backend separately, set BACKEND_URL (default below)
const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:5000';
const POLL_MS = 60_000; // poll backend for due reminders every 60s (main process)

// Track alarms that are currently ringing (id -> timer)
const ringing = new Map();
// Track reminders already notified (to avoid duplicate popups across polls)
const notified = new Set();

let win;

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

app.whenReady().then(() => {
  createWindow();

  // Renderer asks to show a notification (we still support this path)
  ipcMain.on('notify:reminder', (_evt, r) => {
    showNativeReminder(r);
  });

  // Allow renderer to explicitly stop alarm (optional)
  ipcMain.on('alarm:stop', (_evt, id) => stopAlarm(id));

  // Start backend polling so alarms fire even if you’re using port 3000 in a browser
  setInterval(pollDueReminders, POLL_MS);
  // Prime immediately on launch
  pollDueReminders().catch(() => {});

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  // Keep app alive on macOS if you want background alarms even with no window
  if (process.platform !== 'darwin') app.quit();
});