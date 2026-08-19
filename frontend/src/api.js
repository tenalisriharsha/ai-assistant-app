import axios from 'axios';

const API_BASE = process.env.REACT_APP_API_URL || (process.env.NODE_ENV === 'development' ? '' : 'http://127.0.0.1:5001');

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
