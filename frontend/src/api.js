import axios from 'axios';

const API_BASE = process.env.REACT_APP_API_URL || (process.env.NODE_ENV === 'development' ? '' : 'http://127.0.0.1:5001');

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
});

export default api;

export async function fetchAppointments({ action, ...params }) {
  const res = await api.post('/query', { action, ...params });
  if (res.status !== 200) throw new Error(res.data?.error || res.statusText);
  return res.data;
}
