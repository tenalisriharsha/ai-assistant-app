// src/api.js
export async function fetchAppointments({ action, ...params }) {
  const res = await fetch('/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, ...params }),
  });
  if (!res.ok) throw new Error((await res.json()).error || res.statusText);
  return res.json();
}
