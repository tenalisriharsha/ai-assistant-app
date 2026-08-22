import axios from 'axios';

// Dev (browser or electron:dev): '' — relative, goes through the CRA proxy.
// Packaged Electron app: loads via file://, so it needs an absolute URL to
// reach the local backend — REACT_APP_ELECTRON is set at build time only
// for that build (see package.json's electron:build script).
// Plain web deployment (e.g. Fly.io): '' — relative/same-origin, since
// this same Flask app serves both the API and the built frontend.
const API_BASE = process.env.REACT_APP_API_URL || (
  process.env.NODE_ENV === 'development'
    ? ''
    : (process.env.REACT_APP_ELECTRON === 'true' ? 'http://127.0.0.1:5001' : '')
);

// A stable id per browser tab (cleared when the tab closes), so the backend
// can tell apart two tabs/users behind the same IP instead of sharing one
// in-progress conversational flow.
function getSessionId() {
  const KEY = 'scheduler_ai_session_id';
  try {
    let id = window.sessionStorage.getItem(KEY);
    if (!id) {
      id = (window.crypto && window.crypto.randomUUID)
        ? window.crypto.randomUUID()
        : `sess-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      window.sessionStorage.setItem(KEY, id);
    }
    return id;
  } catch {
    return `sess-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
}

const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true, // send/receive the auth session cookie when APP_PASSWORD is set
  headers: {
    'Content-Type': 'application/json',
    'X-Session-Id': getSessionId(),
  },
});

export default api;

export async function fetchAppointments({ action, ...params }) {
  const res = await api.post('/query', { action, ...params });
  if (res.status !== 200) throw new Error(res.data?.error || res.statusText);
  return res.data;
}
