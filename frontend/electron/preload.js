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

  // Native macOS integrations
  syncCalendar: () => ipcRenderer.send('sync:calendar'),
  indexSpotlight: () => ipcRenderer.send('index:spotlight'),
  onNativeSyncResult(cb) {
    const handler = (_e, result) => cb?.(result);
    ipcRenderer.on('native:sync-result', handler);
    return () => ipcRenderer.removeListener('native:sync-result', handler);
  },

  // Print to PDF
  printToPDF: () => ipcRenderer.invoke('print:to-pdf'),
  onPrintResult(cb) {
    const handler = (_e, result) => cb?.(result);
    ipcRenderer.on('print:result', handler);
    return () => ipcRenderer.removeListener('print:result', handler);
  },

  // Backup / restore
  exportBackup: () => ipcRenderer.invoke('backup:export'),
  importBackup: () => ipcRenderer.invoke('backup:import'),

  // Menu events
  onMenuNewAppointment(cb) {
    const handler = () => cb?.();
    ipcRenderer.on('menu:new-appointment', handler);
    return () => ipcRenderer.removeListener('menu:new-appointment', handler);
  },
  onMenuExportBackup(cb) {
    const handler = () => cb?.();
    ipcRenderer.on('menu:export-backup', handler);
    return () => ipcRenderer.removeListener('menu:export-backup', handler);
  },
  onMenuImportBackup(cb) {
    const handler = () => cb?.();
    ipcRenderer.on('menu:import-backup', handler);
    return () => ipcRenderer.removeListener('menu:import-backup', handler);
  },
  onMenuPrintPDF(cb) {
    const handler = () => cb?.();
    ipcRenderer.on('menu:print-pdf', handler);
    return () => ipcRenderer.removeListener('menu:print-pdf', handler);
  },
};

contextBridge.exposeInMainWorld('electronAPI', api);
