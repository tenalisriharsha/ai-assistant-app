import React, { useEffect, useState } from 'react';
import api from '../api';

// Gates the app behind a password when the backend has APP_PASSWORD set
// (the hosted deployment). Local/desktop use never sees this — /session
// reports auth_required: false there, so children render immediately.
export default function LoginGate({ children }) {
  const [status, setStatus] = useState('checking'); // checking | locked | open
  const [authRequired, setAuthRequired] = useState(false);
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.get('/session')
      .then(({ data }) => {
        if (cancelled) return;
        setAuthRequired(!!data.auth_required);
        setStatus(data.auth_required && !data.authenticated ? 'locked' : 'open');
      })
      .catch(() => {
        // If the check itself fails, don't lock the user out silently —
        // fall through to the app, which will surface real errors itself.
        if (!cancelled) setStatus('open');
      });
    return () => { cancelled = true; };
  }, []);

  const handleLogout = async () => {
    try {
      await api.post('/logout');
    } catch {
      // ignore — worst case the session cookie just expires naturally
    }
    setStatus('locked');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!password.trim() || submitting) return;
    setSubmitting(true);
    setError('');
    try {
      const { data } = await api.post('/login', { password });
      if (data.ok) {
        setStatus('open');
      } else {
        setError(data.error || 'Incorrect password.');
      }
    } catch (err) {
      setError(err.response?.data?.error || 'Incorrect password.');
    } finally {
      setSubmitting(false);
      setPassword('');
    }
  };

  if (status === 'checking') {
    return <div style={styles.shell} />;
  }

  if (status === 'locked') {
    return (
      <div style={styles.shell}>
        <form onSubmit={handleSubmit} style={styles.card}>
          <div style={styles.title}>Scheduler AI</div>
          <div style={styles.subtitle}>Enter the password to continue</div>
          <input
            type="password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            style={styles.input}
          />
          {error && <div style={styles.error}>{error}</div>}
          <button type="submit" disabled={submitting} style={styles.button}>
            {submitting ? 'Checking…' : 'Unlock'}
          </button>
        </form>
      </div>
    );
  }

  return (
    <>
      {children}
      {authRequired && (
        <button onClick={handleLogout} style={styles.logoutBtn} title="Log out">
          Log out
        </button>
      )}
    </>
  );
}

const styles = {
  shell: {
    minHeight: '100vh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'linear-gradient(180deg, #E9D5FF 0%, #FBCFE8 100%)',
  },
  card: {
    background: 'white',
    borderRadius: 16,
    padding: '32px 28px',
    width: 320,
    boxShadow: '0 10px 30px rgba(0,0,0,0.12)',
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  title: { fontSize: 20, fontWeight: 700, color: '#111827', textAlign: 'center' },
  subtitle: { fontSize: 13, color: '#6b7280', textAlign: 'center', marginBottom: 8 },
  input: {
    padding: '10px 12px',
    borderRadius: 10,
    border: '1px solid #e5e7eb',
    fontSize: 14,
    outline: 'none',
  },
  error: { fontSize: 12, color: '#ef4444' },
  button: {
    padding: '10px 14px',
    borderRadius: 10,
    border: 'none',
    background: '#3b82f6',
    color: 'white',
    fontWeight: 600,
    cursor: 'pointer',
  },
  logoutBtn: {
    position: 'fixed',
    bottom: 14,
    right: 14,
    padding: '6px 12px',
    borderRadius: 8,
    border: '1px solid #e5e7eb',
    background: 'white',
    color: '#374151',
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
    boxShadow: '0 2px 8px rgba(0,0,0,0.08)',
    zIndex: 1000,
  },
};
