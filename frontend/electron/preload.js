// electron/preload.js
const { contextBridge, ipcRenderer } = require('electron');

// Avoid MaxListeners warnings during hot reloads in development
try {
  ipcRenderer.setMaxListeners(0);
} catch (_) {}

const api = {
  // Ask main to show a native notification (and optionally play alarm)
  notifyReminder: (reminder) => ipcRenderer.send('notify:reminder', reminder),

  // Listen for notification/toast dismissal from main
  // Returns an unsubscribe function so HMR or components can clean up.
  onReminderDismissed(cb) {
    const handler = (_e, id) => cb?.(id);
    ipcRenderer.on('reminder:dismissed', handler);
    return () => ipcRenderer.removeListener('reminder:dismissed', handler);
  },
  // Optional direct remover if you kept a reference to the same callback
  removeOnReminderDismissed: (cb) =>
    ipcRenderer.removeListener('reminder:dismissed', cb),

  // Stop any currently playing alarm in main
  stopAlarm: (id) => ipcRenderer.send('alarm:stop', id),

  // When main wants the renderer to open a specific appointment
  onAppointmentOpen(cb) {
    const handler = (_e, payload) => cb?.(payload);
    ipcRenderer.on('appointment:open', handler);
    return () => ipcRenderer.removeListener('appointment:open', handler);
  },

  // Generic navigation signal from main → renderer
  onNavigate(cb) {
    const handler = (_e, dest) => cb?.(dest);
    ipcRenderer.on('navigate', handler);
    return () => ipcRenderer.removeListener('navigate', handler);
  },
};

contextBridge.exposeInMainWorld('electronAPI', api);