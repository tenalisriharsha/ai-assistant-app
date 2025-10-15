// src/App.js
import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import MicButton from './components/MicButton';

function App() {
  const [query, setQuery] = useState('');
  const [appointments, setAppointments] = useState([]);
  const [createdAppts, setCreatedAppts] = useState([]);
  const [freeSlots, setFreeSlots] = useState([]);
  const [proposals, setProposals] = useState([]);
  const [count, setCount] = useState(null);
  const [conflicts, setConflicts] = useState([]);
  const [reminders, setReminders] = useState([]);
  const [toasts, setToasts] = useState([]);
  const [messages, setMessages] = useState([
    { from: 'bot', text: "Hello! I'm Scheduler AI. Ask me about today, this week, free time, schedule something new, counts, conflicts… 😊" },
  ]);
  const [isPreview, setIsPreview] = useState(false);
  const [skippedConflicts, setSkippedConflicts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [errorText, setErrorText] = useState('');
  const scrollerRef = useRef(null);

  // ---- helpers --------------------------------------------------------------

  // Auto-scroll chat
  useEffect(() => {
    if (scrollerRef.current) {
      scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
    }
  }, [messages, appointments, freeSlots, conflicts, count, proposals, createdAppts, reminders]);

  const weekdayName = (isoDate) => {
    if (!isoDate) return '';
    const parts = String(isoDate).split('-');
    if (parts.length !== 3) return '';
    const dt = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    return dt.toLocaleDateString(undefined, { weekday: 'short' });
  };

  // Parse "14:00", "14:00:30", or "2:00 pm" -> minutes since midnight
  const timeToMinutes = (t) => {
    if (!t) return null;
    const s = String(t).trim().toLowerCase();
    const m = s.match(/^(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?\s*(am|pm)?$/);
    if (!m) return null;
    let hh = parseInt(m[1], 10);
    const mm = parseInt(m[2] || '0', 10);
    const ss = parseInt(m[3] || '0', 10);
    const ampm = m[4];
    if (ampm === 'pm' && hh !== 12) hh += 12;
    if (ampm === 'am' && hh === 12) hh = 0;
    return Math.floor((hh * 3600 + mm * 60 + ss) / 60);
  };

  const durationFromAppt = (a) => {
    const s = timeToMinutes(a.start_time || a.start);
    const e = timeToMinutes(a.end_time || a.end);
    if (s == null || e == null) return 60; // safe default
    const d = e - s;
    return d > 0 ? d : 60;
  };

  // Format minutes to human readable "2h 30m" / "45m"
  const formatDuration = (mins) => {
    if (mins == null) return '';
    const m = Math.max(0, Math.round(mins));
    const h = Math.floor(m / 60);
    const mm = m % 60;
    if (h && mm) return `${h}h ${mm}m`;
    if (h) return `${h}h`;
    return `${mm}m`;
  };

  // Lookup an appointment by id from current UI state
  const getApptById = (id) => {
    if (!id) return null;
    const fromCreated = createdAppts.find((a) => a && a.id === id);
    if (fromCreated) return fromCreated;
    const fromAppts = appointments.find((a) => a && a.id === id);
    if (fromAppts) return fromAppts;
    return null;
  };

  // Enrich reminder object with appointment title/duration when available
  const enrichReminderWithAppt = (r) => {
    if (!r) return r;
    const appt = getApptById(r.appointment_id);
    const apptTitle = appt ? (appt.title || appt.description) : (r.appt_title || null);
    const apptDur = r.appt_duration_minutes ?? (appt ? durationFromAppt(appt) : null);
    return { ...r, appt_title: apptTitle || r.title || r.description, appt_duration_minutes: apptDur };
  };

  // Keep UI in sync after update/delete
  const updateLocalAppointment = (updated) => {
    const key = (x) => x?.id ?? `${x.date}-${(x.start_time || x.start)}-${(x.end_time || x.end)}`;
    const mergeOne = (list) =>
      list.map((x) =>
        (updated.id && x.id === updated.id) || (!updated.id && key(x) === key(updated))
          ? { ...x, ...updated }
          : x
      );
    setAppointments((lst) => mergeOne(lst));
    setCreatedAppts((lst) => mergeOne(lst));
  };

  const removeLocalById = (id) => {
    if (!id) return;
    setAppointments((lst) => lst.filter((x) => x.id !== id));
    setCreatedAppts((lst) => lst.filter((x) => x.id !== id));
  };

  // Reminders helpers
  const addOrUpdateReminder = (r) => {
    if (!r) return;
    const enriched = enrichReminderWithAppt(r);
    setReminders((lst) => {
      const idx = lst.findIndex((x) => x.id === enriched.id);
      const next = [...lst];
      if (idx >= 0) {
        next[idx] = enrichReminderWithAppt({ ...next[idx], ...enriched });
      } else {
        next.push(enriched);
      }
      next.sort((a, b) => {
        const ad = new Date(`${a.date}T${(a.time || '00:00')}`);
        const bd = new Date(`${b.date}T${(b.time || '00:00')}`);
        return ad - bd;
      });
      return next;
    });
  };

  const removeReminderById = (id) => {
    if (!id) return;
    setReminders((lst) => lst.filter((x) => x.id !== id));
  };

  const showReminderToast = (r) => {
    if (!r) return;
    const rr = enrichReminderWithAppt(r);
    const when = rr.date && rr.time ? `${rr.date} ${rr.time}` : '';
    const displayTitle = rr.appt_title || rr.title || rr.description || 'Reminder';
    const durText = rr.appt_duration_minutes != null ? ` • ⏱ ${formatDuration(rr.appt_duration_minutes)}` : '';

    setMessages((m) => [
      ...m,
      { from: 'bot', text: `🔔 Reminder: ${displayTitle}${when ? ` — ${when}` : ''}${durText}` },
    ]);

    // Push a visual toast with clear preview; dismissing it marks delivered.
    pushToast({
      title: displayTitle,
      subtitle: `${when}${durText}`,
      reminder: rr, // pass through enriched reminder
    });
  };

  // helper already added earlier; include if missing
  async function markReminderDelivered(id) {
    await fetch('http://127.0.0.1:5000/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'reminder_mark_delivered', id }),
    });
  }

  // Register once on app start (avoid duplicate listeners in dev/hot-reload)
  useEffect(() => {
    if (!window?.electronAPI || typeof window.electronAPI.onReminderDismissed !== 'function') return;

    const handler = (id) => {
      if (!id) return;
      if (typeof window.electronAPI.stopAlarm === 'function') {
        window.electronAPI.stopAlarm(id);
      }
      markReminderDelivered(id).catch(console.error);
    };

    // onReminderDismissed now returns an unsubscribe function from preload
    const unsubscribe = window.electronAPI.onReminderDismissed(handler);

    return () => {
      if (typeof unsubscribe === 'function') unsubscribe();
    };
  }, []);

  const pushToast = (t) => {
    setToasts((arr) => [
      ...arr,
      { ...t, key: t.key || `${Date.now()}-${Math.random().toString(36).slice(2)}` },
    ]);
  };

  const dismissToast = async (t) => {
    setToasts((arr) => arr.filter((x) => x.key !== t.key));
    const rid = t?.reminder?.id || t?.reminderId;
    if (rid) {
      if (window.electronAPI && typeof window.electronAPI.stopAlarm === 'function') {
        window.electronAPI.stopAlarm(rid);
      }
      await markReminderDelivered(rid);
    }
  };

  // Consolidated handler for all server response shapes
  const applyPayload = (data) => {
    if (!data || typeof data !== 'object') return;

    // Preview mode payload: the real data is nested under `preview`
    if (data.preview && typeof data.preview === 'object') {
      setIsPreview(true);
      setMessages((m) => [...m, { from: 'bot', text: 'Preview only — no changes applied.' }]);
      applyPayload(data.preview);
      return;
    }

    // Lists
    if (Array.isArray(data.appointments)) setAppointments(data.appointments);
    if (data.appointment && typeof data.appointment === 'object') setAppointments([data.appointment]);
    if (Array.isArray(data.free)) setFreeSlots(data.free);

    // Proposals / suggestions (duration-aware availability)
    const proposalsArr = Array.isArray(data.proposals)
      ? data.proposals
      : (Array.isArray(data.suggestions) ? data.suggestions : null);
    if (proposalsArr) {
      setProposals(proposalsArr);
      setMessages((m) => [...m, { from: 'bot', text: `I found ${proposalsArr.length} possible slot(s). Pick one to book or move.` }]);
    }

    // Counts
    if (typeof data.count === 'number') {
      setCount(data.count);
      setMessages((m) => [...m, { from: 'bot', text: `You have ${data.count} appointments in that period.` }]);
    }

    // Conflicts
    if (Array.isArray(data.conflicts)) {
      setConflicts(data.conflicts);
      setMessages((m) => [...m, { from: 'bot', text: `Found ${data.conflicts.length} overlapping appointment pair(s).` }]);
    }

    // Bulk operations may report items skipped due to conflicts
    if (Array.isArray(data.skipped_conflicts)) {
      const sc = data.skipped_conflicts;
      // If it looks like an array of conflict pairs, append them to the conflicts list
      const looksLikePairs = sc.every(
        (x) => Array.isArray(x) && x.length >= 2 && x[0] && (x[0].date || x[0].start_time || x[0].start)
      );
      if (looksLikePairs) {
        setConflicts((prev) => [...prev, ...sc]);
      }
      setSkippedConflicts((prev) => [...prev, ...sc]);
      setMessages((m) => [...m, { from: 'bot', text: `Skipped ${sc.length} item(s) due to conflicts.` }]);
    }

    // Creations
    if (data.created && typeof data.created === 'object') {
      setCreatedAppts((c) => [...c, data.created]);
      setAppointments([data.created]);
    }
    if (Array.isArray(data.created_many) && data.created_many.length > 0) {
      setCreatedAppts((c) => [...c, ...data.created_many]);
      setMessages((m) => [...m, { from: 'bot', text: `Created ${data.created_many.length} appointment(s).` }]);
    }

    // Updates / reschedules
    if (data.updated && typeof data.updated === 'object') {
      updateLocalAppointment(data.updated);
      setAppointments([data.updated]);
      setMessages((m) => [...m, { from: 'bot', text: 'Updated successfully.' }]);
    }
    if (data.rescheduled && typeof data.rescheduled === 'object') {
      updateLocalAppointment(data.rescheduled);
      setAppointments([data.rescheduled]);
      setMessages((m) => [...m, { from: 'bot', text: 'Rescheduled successfully.' }]);
    }
    if (typeof data.updated_count === 'number') {
      setMessages((m) => [...m, { from: 'bot', text: `Updated ${data.updated_count} item(s).` }]);
    }

    // Bulk results
    if (Array.isArray(data.updated_many) && data.updated_many.length > 0) {
      data.updated_many.forEach((u) => updateLocalAppointment(u));
      setAppointments(data.updated_many);
      setMessages((m) => [...m, { from: 'bot', text: `Updated ${data.updated_many.length} item(s).` }]);
    }
    if (Array.isArray(data.rescheduled_many) && data.rescheduled_many.length > 0) {
      data.rescheduled_many.forEach((u) => updateLocalAppointment(u));
      setAppointments(data.rescheduled_many);
      setMessages((m) => [...m, { from: 'bot', text: `Rescheduled ${data.rescheduled_many.length} item(s).` }]);
    }
    if (typeof data.moved_count === 'number') {
      setMessages((m) => [...m, { from: 'bot', text: `Moved ${data.moved_count} item(s).` }]);
    }

    // Deletes
    if (typeof data.deleted_count === 'number') {
      setMessages((m) => [...m, { from: 'bot', text: `Deleted ${data.deleted_count} item(s).` }]);
    }
    if (data.deleted === true && data.id) {
      removeLocalById(data.id);
      removeReminderById(data.id);
      setMessages((m) => [...m, { from: 'bot', text: 'Deleted successfully.' }]);
    }

    // Reminders
    if (data.reminder && typeof data.reminder === 'object') {
      addOrUpdateReminder(data.reminder);
    }
    if (Array.isArray(data.reminders)) {
      setReminders(data.reminders.map(enrichReminderWithAppt));
    }
    if (Array.isArray(data.due_reminders)) {
      data.due_reminders.forEach((r) => {
        addOrUpdateReminder(r);
        // existing in-app toast
        showReminderToast(r);
        // native macOS notification via Electron (when available)
        if (window.electronAPI && typeof window.electronAPI.notifyReminder === 'function') {
          window.electronAPI.notifyReminder(r);
        }
      });
    }

    // Generic message
    if (data.message && !data.created) {
      setMessages((m) => [...m, { from: 'bot', text: String(data.message) }]);
    }
  };
  // ---- reminders polling (in-app notifications) ----------------------------
  useEffect(() => {
    const poll = async () => {
      try {
        const { data } = await axios.post('http://127.0.0.1:5000/query', { action: 'reminders_due' }, {
          headers: { 'Content-Type': 'application/json' },
        });
        applyPayload(data);
      } catch (e) {
        // silent
      }
    };
    // initial and interval
    poll();
    const id = setInterval(poll, 60000);
    return () => clearInterval(id);
  }, []);

  // ---- voice transcript handler (uses same /query flow) ---------------------
  const handleVoiceTranscript = async (text) => {
    const trimmed = (text || '').trim();
    if (!trimmed) return;

    setMessages((m) => [...m, { from: 'user', text: `🎙️ ${trimmed}` }]);
    setLoading(true);
    setErrorText('');

    try {
      const { data } = await axios.post('http://127.0.0.1:5000/query', { query: trimmed }, {
        headers: { 'Content-Type': 'application/json' },
      });

      // reset result panels (keep Created)
      setAppointments([]);
      setFreeSlots([]);
      setConflicts([]);
      setCount(null);
      setProposals([]);
      setSkippedConflicts([]);
      setIsPreview(false);

      setMessages((m) => [...m, { from: 'bot', text: 'Here are your results:' }]);

      applyPayload(data);
    } catch (err) {
      const data = err?.response?.data;
      const msg = data?.error || err.message || 'Something went wrong.';
      setErrorText(msg);
      setMessages((m) => [...m, { from: 'bot', text: `Oops — ${msg}` }]);

      if (data) applyPayload(data);
    } finally {
      setLoading(false);
    }
  };

  // ---- chat submit ----------------------------------------------------------

  const handleQuery = async () => {
    const trimmed = query.trim();
    if (!trimmed) return;

    setMessages((m) => [...m, { from: 'user', text: trimmed }]);
    setLoading(true);
    setErrorText('');

    const lower = trimmed.toLowerCase();
    const isCreateLike = /(schedule|create|add|book|hold|block|reserve|set up|set-up|set\s+up)/i.test(lower);
    const isModifyLike = /(move|reschedule|change|edit|update|shift|rename|retitle)/i.test(lower);
    const isCancelLike = /(cancel|delete|remove|clear)/i.test(lower);
    const wantsFree = /(free|available|availability|open|slot|free time)/i.test(lower);
    const mentionsBetween = /\bbetween\b/i.test(lower);

    let payload = { query: trimmed };
    if (!isCreateLike && !isModifyLike && !isCancelLike && !wantsFree && !mentionsBetween) {
      if (/\bthis week\b/i.test(lower)) {
        payload = { action: 'this_week' };
      } else if (/\btoday\b/i.test(lower)) {
        payload = { action: 'today' };
      }
    }

    try {
      const { data } = await axios.post('http://127.0.0.1:5000/query', payload, {
        headers: { 'Content-Type': 'application/json' },
      });

      // reset result panels (keep Created)
      setAppointments([]);
      setFreeSlots([]);
      setConflicts([]);
      setCount(null);
      setProposals([]);
      setSkippedConflicts([]);
      setIsPreview(false);

      setMessages((m) => [...m, { from: 'bot', text: 'Here are your results:' }]);

      applyPayload(data);
    } catch (err) {
      const data = err?.response?.data;
      const msg = data?.error || err.message || 'Something went wrong.';
      setErrorText(msg);
      setMessages((m) => [...m, { from: 'bot', text: `Oops — ${msg}` }]);

      // If the server sent structured info (e.g., proposals on 409), apply it
      if (data) {
        applyPayload(data);
      }
    } finally {
      setLoading(false);
      setQuery('');
    }
  };

  // ---- booking & moving -----------------------------------------------------

  // Book a proposed slot (action: create) — DRY to applyPayload
  const bookSlot = async (slot) => {
    const payload = {
      action: 'create',
      date: slot.date,
      start_time: slot.start_time || slot.start,
      end_time: slot.end_time || slot.end,
      title: slot.title || 'New event',
      description: slot.description || slot.title || 'Scheduled via AI',
    };

    setLoading(true);
    setMessages((m) => [...m, { from: 'user', text: `Book: ${payload.title} on ${payload.date} ${payload.start_time}–${payload.end_time}` }]);
    try {
      const { data } = await axios.post('http://127.0.0.1:5000/query', payload, {
        headers: { 'Content-Type': 'application/json' },
      });

      setProposals([]);
      applyPayload(data);
      setIsPreview(false);
      setSkippedConflicts([]);

      // Fallback confirmation if server returned minimal payload
      if (
        !data ||
        (!data.created && !data.created_many && !data.appointment && !data.message && !data.proposals && !data.suggestions)
      ) {
        setMessages((m) => [...m, { from: 'bot', text: 'Booked.' }]);
      }
    } catch (err) {
      const data = err?.response?.data;
      const msg = data?.error || err.message || 'Could not book that slot.';
      setMessages((m) => [...m, { from: 'bot', text: `Booking failed — ${msg}` }]);

      // Apply any structured payload from the server (e.g., proposals on conflict)
      if (data) applyPayload(data);
    } finally {
      setLoading(false);
    }
  };

  // Move (reschedule) an existing appointment into a proposed slot — DRY to applyPayload
  const moveSlot = async (slot) => {
    const selector = slot.selector || (slot.source_id ? { id: slot.source_id } : null);
    if (!selector) {
      setMessages((m) => [...m, { from: 'bot', text: 'I need the original appointment id (source_id) or selector to move it.' }]);
      return;
    }

    const payload = {
      action: 'reschedule',
      selector,
      new_date: slot.date,
      new_start_time: slot.start_time || slot.start,
    };
    if (slot.end_time || slot.end) {
      payload.new_end_time = slot.end_time || slot.end;
    } else if (slot.duration_minutes) {
      payload.duration_minutes = slot.duration_minutes;
    }

    setLoading(true);
    setMessages((m) => [
      ...m,
      { from: 'user', text: `Move to: ${payload.new_date} ${payload.new_start_time}${payload.new_end_time ? `–${payload.new_end_time}` : ''}` },
    ]);

    try {
      const { data } = await axios.post('http://127.0.0.1:5000/query', payload, {
        headers: { 'Content-Type': 'application/json' },
      });

      setProposals([]);
      applyPayload(data);
      setIsPreview(false);
      setSkippedConflicts([]);

      // Fallback confirmation if server returned minimal payload
      if (
        !data ||
        (!data.updated && !data.rescheduled && !data.appointment && typeof data.updated_count !== 'number' && !data.message)
      ) {
        setMessages((m) => [...m, { from: 'bot', text: 'Rescheduled.' }]);
      }
    } catch (err) {
      const data = err?.response?.data;
      const msg = data?.error || err.message || 'Could not reschedule.';
      setMessages((m) => [...m, { from: 'bot', text: `Reschedule failed — ${msg}` }]);

      // Apply any structured payload from the server (e.g., proposals on conflict)
      if (data) applyPayload(data);
    } finally {
      setLoading(false);
    }
  };

  // ---- inline actions: rename / reschedule / cancel -------------------------

  const renameAppointment = async (a) => {
    const newTitle = window.prompt('New title', a.title || a.description || '');
    if (!newTitle) return;
    setLoading(true);
    try {
      const res = await axios.post(
        'http://127.0.0.1:5000/query',
        {
          action: 'update',
          selector: { id: a.id }, // use hard id; no fuzzy needed
          fields: { title: newTitle, description: newTitle }
        },
        { headers: { 'Content-Type': 'application/json' } }
      );
      const updated = res.data.updated || res.data.appointment;
      if (updated) {
        updateLocalAppointment(updated);
        setMessages((m) => [...m, { from: 'bot', text: 'Updated title.' }]);
      } else {
        setMessages((m) => [...m, { from: 'bot', text: 'Update requested, but the server did not confirm.' }]);
      }
    } catch (err) {
      const msg = err.response?.data?.error || err.message || 'Could not update.';
      setMessages((m) => [...m, { from: 'bot', text: `Update failed — ${msg}` }]);
    } finally {
      setLoading(false);
    }
  };

  const rescheduleAppointment = async (a) => {
    const newDate = window.prompt('New date (YYYY-MM-DD)', a.date);
    if (!newDate) return;
    const newStart = window.prompt('New start time (e.g., 14:00 or 2:00 pm)', a.start_time || a.start);
    if (!newStart) return;
    // End time optional – if blank, we’ll send duration_minutes from the original appt
    const newEnd = window.prompt('New end time (optional — leave blank to keep same duration)', a.end_time || a.end);

    const payload = {
      action: 'reschedule',
      selector: {
        id: a.id,
        date: a.date,
        start_time: a.start_time || a.start,
        end_time: a.end_time || a.end,
      },
      new_date: newDate,
      new_start_time: newStart,
    };
    if (newEnd && String(newEnd).trim()) {
      payload.new_end_time = newEnd;
    } else {
      payload.duration_minutes = durationFromAppt(a);
    }

    setLoading(true);
    try {
      const res = await axios.post('http://127.0.0.1:5000/query', payload, {
        headers: { 'Content-Type': 'application/json' },
      });

      if (res.data.updated && typeof res.data.updated === 'object') {
        updateLocalAppointment(res.data.updated);
        setAppointments([res.data.updated]);
        setMessages((m) => [...m, { from: 'bot', text: 'Rescheduled.' }]);
      } else if (res.data.rescheduled && typeof res.data.rescheduled === 'object') {
        updateLocalAppointment(res.data.rescheduled);
        setAppointments([res.data.rescheduled]);
        setMessages((m) => [...m, { from: 'bot', text: 'Rescheduled.' }]);
      } else if (res.data.appointment) {
        updateLocalAppointment(res.data.appointment);
        setAppointments([res.data.appointment]);
        setMessages((m) => [...m, { from: 'bot', text: 'Rescheduled.' }]);
      } else {
        setMessages((m) => [...m, { from: 'bot', text: 'Reschedule requested, but the server did not confirm.' }]);
      }
    } catch (err) {
      const msg = err.response?.data?.error || err.message || 'Could not reschedule.';
      setMessages((m) => [...m, { from: 'bot', text: `Reschedule failed — ${msg}` }]);
      const proposals409 = err.response?.data?.proposals;
      if (Array.isArray(proposals409)) {
        setProposals(proposals409);
        setMessages((m) => [...m, { from: 'bot', text: `Here are some available options for ${newDate}.` }]);
      }
    } finally {
      setLoading(false);
    }
  };


  const cancelAppointment = async (a) => {
    if (!window.confirm('Delete this appointment?')) return;
    setLoading(true);
    try {
      const res = await axios.post(
        'http://127.0.0.1:5000/query',
        {
          action: 'delete',
          selector: {
            id: a.id,
            date: a.date,
            start_time: a.start_time || a.start,
            end_time: a.end_time || a.end,
          },
        },
        { headers: { 'Content-Type': 'application/json' } }
      );
      const deletedOk =
        (typeof res.data.deleted_count === 'number' && res.data.deleted_count > 0) ||
        res.data.deleted === true;
      if (deletedOk) {
        if (a.id) removeLocalById(a.id);
        setMessages((m) => [...m, { from: 'bot', text: 'Deleted.' }]);
      } else {
        setMessages((m) => [...m, { from: 'bot', text: 'Delete requested, but the server did not confirm.' }]);
      }
    } catch (err) {
      const msg = err.response?.data?.error || err.message || 'Could not delete.';
      setMessages((m) => [...m, { from: 'bot', text: `Delete failed — ${msg}` }]);
    } finally {
      setLoading(false);
    }
  };

  // ---- reminder actions -----------------------------------------------------

  const snoozeReminder = async (r, minutes = 10) => {
    setLoading(true);
    try {
      const { data } = await axios.post('http://127.0.0.1:5000/query',
        { action: 'reminder_snooze', id: r.id, minutes },
        { headers: { 'Content-Type': 'application/json' } }
      );
      applyPayload(data);
      setMessages((m) => [...m, { from: 'bot', text: `Snoozed for ${minutes} min.` }]);
    } catch (err) {
      const msg = err?.response?.data?.error || err.message || 'Could not snooze.';
      setMessages((m) => [...m, { from: 'bot', text: `Snooze failed — ${msg}` }]);
    } finally {
      setLoading(false);
    }
  };

  const toggleReminder = async (r) => {
    setLoading(true);
    try {
      const { data } = await axios.post('http://127.0.0.1:5000/query',
        { action: 'reminder_toggle', id: r.id, active: !r.active },
        { headers: { 'Content-Type': 'application/json' } }
      );
      applyPayload(data);
    } catch (err) {
      const msg = err?.response?.data?.error || err.message || 'Could not toggle reminder.';
      setMessages((m) => [...m, { from: 'bot', text: `Toggle failed — ${msg}` }]);
    } finally {
      setLoading(false);
    }
  };

  const deleteReminder = async (r) => {
    if (!window.confirm('Delete this reminder?')) return;
    setLoading(true);
    try {
      const { data } = await axios.post('http://127.0.0.1:5000/query',
        { action: 'reminder_delete', id: r.id },
        { headers: { 'Content-Type': 'application/json' } }
      );
      applyPayload(data);
      if (data?.deleted) setMessages((m) => [...m, { from: 'bot', text: 'Reminder deleted.' }]);
    } catch (err) {
      const msg = err?.response?.data?.error || err.message || 'Could not delete reminder.';
      setMessages((m) => [...m, { from: 'bot', text: `Delete failed — ${msg}` }]);
    } finally {
      setLoading(false);
    }
  };

  // ---- UI -------------------------------------------------------------------

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleQuery();
    }
  };

  return (
    <div style={styles.shell}>
      <div style={styles.bgA} />
      <div style={styles.bgB} />
      <div style={styles.noise} />

      <div style={styles.page}>
        {/* Toasts (in-app notifications) */}
        <div style={styles.toastStack}>
          {toasts.map((t) => (
            <div key={t.key} style={styles.toast}>
              <div style={{ fontWeight: 700 }}>{t.title}</div>
              {t.subtitle && (
                <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>{t.subtitle}</div>
              )}
              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <button onClick={() => dismissToast(t)} style={styles.toastBtn}>Dismiss</button>
                {t.reminder && (
                  <button onClick={() => snoozeReminder(t.reminder, 10)} style={styles.toastBtn}>Snooze 10m</button>
                )}
              </div>
            </div>
          ))}
        </div>
        <header style={styles.header}>
          <div style={styles.brandRow}>
            <img
              src="/robot.svg"
              alt="Robot avatar"
              style={styles.avatar}
              onError={(e) => {
                e.currentTarget.src =
                  'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><rect width="64" height="64" rx="12" fill="%237C3AED"/><circle cx="32" cy="30" r="14" fill="white"/><circle cx="27" cy="28" r="3" fill="%237C3AED"/><circle cx="37" cy="28" r="3" fill="%237C3AED"/><rect x="24" y="36" width="16" height="3" rx="1.5" fill="%237C3AED"/></svg>';
              }}
            />
            <div>
              <div style={styles.brand}>Scheduler AI</div>
              <div style={styles.subtitle}>Your intelligent scheduling assistant</div>
            </div>
          </div>
        </header>

        <div style={styles.body}>
          {/* Chat */}
          <section style={styles.chatCard}>
            <div style={styles.chatHeader}>Chat</div>
            <div style={styles.chatScroll} ref={scrollerRef}>
              {messages.map((m, i) => (
                <div
                  key={i}
                  style={{
                    display: 'flex',
                    marginBottom: 12,
                    justifyContent: m.from === 'bot' ? 'flex-start' : 'flex-end',
                  }}
                >
                  <div
                    style={{
                      ...styles.bubble,
                      background: m.from === 'bot' ? 'white' : '#3b82f6',
                      color: m.from === 'bot' ? '#111827' : 'white',
                      border: m.from === 'bot' ? '1px solid #eef2ff' : 'none',
                      boxShadow: m.from === 'bot' ? '0 1px 1px rgba(0,0,0,.02)' : '0 2px 10px rgba(59,130,246,.35)',
                    }}
                  >
                    {m.text}
                  </div>
                </div>
              ))}
              {loading && <div style={styles.loading}>Thinking…</div>}
            </div>

            <div style={styles.inputRow}>
              <input
                type="text"
                placeholder='Ask anything: “Schedule deep work tomorrow 2–4”, “free next week 1–5 PM?”, “meetings this week?”'
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onKeyDown}
                style={styles.input}
              />
              <MicButton onTranscript={handleVoiceTranscript} />
              <button onClick={handleQuery} style={styles.sendBtn}>Send</button>
            </div>

            {errorText && <div style={styles.error}>{errorText}</div>}
          </section>

          {/* Results */}
          <section style={styles.resultsCol}>
            {/* Reminders */}
            <div style={styles.panel}>
              <div style={styles.panelTitle}>Reminders</div>
              {reminders.length === 0 ? (
                <div style={styles.empty}>No reminders yet.</div>
              ) : (
                <ul style={styles.list}>
                  {reminders.map((r) => {
                    const rr = enrichReminderWithAppt(r);
                    const displayTitle = rr.appt_title || rr.title || rr.description || '—';
                    const durText = rr.appt_duration_minutes != null ? `• ⏱ ${formatDuration(rr.appt_duration_minutes)}` : '';
                    return (
                      <li key={rr.id ?? `${rr.date}-${rr.time}-${displayTitle || ''}`} style={styles.listItem}>
                        <div style={styles.row}>
                          <span style={styles.date}>
                            <span style={styles.weekday}>{weekdayName(rr.date)}</span>
                            {rr.date}
                          </span>
                          <span style={styles.time}>{rr.time || '—:—'}</span>
                        </div>
                        <div style={{ ...styles.desc, fontWeight: 600 }}>{displayTitle}</div>
                        <div style={{ marginTop: 4, fontSize: 12, color: '#6b7280' }}>
                          {rr.channel ? `🔔 ${rr.channel}` : ''} {rr.lead_minutes ? `• lead ${rr.lead_minutes}m` : ''} {durText} {rr.active ? '• active' : '• paused'} {rr.delivered ? '• delivered' : ''}
                        </div>
                        <div style={styles.actionRow}>
                          <button onClick={() => snoozeReminder(rr, 10)} style={styles.smallBtn}>Snooze 10m</button>
                          <button onClick={() => toggleReminder(rr)} style={styles.smallBtn}>{rr.active ? 'Pause' : 'Activate'}</button>
                          <button onClick={() => deleteReminder(rr)} style={{ ...styles.smallBtn, background: '#ef4444' }}>Delete</button>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
            {/* Appointments */}
            <div style={styles.panel}>
              <div style={styles.panelTitle}>Appointments</div>
              {appointments.length === 0 ? (
                <div style={styles.empty}>No appointments to display.</div>
              ) : (
                <ul style={styles.list}>
                  {appointments.map((a) => (
                    <li key={a.id ?? `${a.date}-${a.start_time}-${a.end_time}`} style={styles.listItem}>
                      <div style={styles.row}>
                        <span style={styles.date}>
                          <span style={styles.weekday}>{weekdayName(a.date)}</span>
                          {a.date}
                        </span>
                        <span style={styles.time}>
                          {(a.start_time || a.start) ?? '??'} – {(a.end_time || a.end) ?? '??'}
                        </span>
                      </div>
                      <div style={styles.desc}>{a.title || a.description || '—'}</div>
                      {(a.location || a.modality || a.label) && (
                        <div style={{ marginTop: 4, fontSize: 12, color: '#6b7280' }}>
                          {a.location ? `📍 ${a.location} ` : ''}
                          {a.modality ? `• ${a.modality} ` : ''}
                          {a.label ? `• ${a.label}` : ''}
                        </div>
                      )}
                      <div style={styles.actionRow}>
                        <button onClick={() => renameAppointment(a)} style={styles.smallBtn}>Rename</button>
                        <button onClick={() => rescheduleAppointment(a)} style={styles.smallBtn}>Reschedule</button>
                        <button onClick={() => cancelAppointment(a)} style={{ ...styles.smallBtn, background: '#ef4444' }}>
                          Cancel
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Created */}
            <div style={styles.panel}>
              <div style={styles.panelTitle}>Created</div>
              {createdAppts.length === 0 ? (
                <div style={styles.empty}>No newly created appointments.</div>
              ) : (
                <ul style={styles.list}>
                  {createdAppts.map((a) => (
                    <li key={a.id ?? `${a.date}-${a.start_time}-${a.end_time}-created`} style={styles.listItem}>
                      <div style={styles.row}>
                        <span style={styles.date}>
                          <span style={styles.weekday}>{weekdayName(a.date)}</span>
                          {a.date}
                        </span>
                        <span style={styles.time}>
                          {(a.start_time || a.start) ?? '??'} – {(a.end_time || a.end) ?? '??'}
                        </span>
                      </div>
                      <div style={styles.desc}>{a.title || a.description || '—'}</div>
                      {(a.location || a.modality || a.label) && (
                        <div style={{ marginTop: 4, fontSize: 12, color: '#6b7280' }}>
                          {a.location ? `📍 ${a.location} ` : ''}
                          {a.modality ? `• ${a.modality} ` : ''}
                          {a.label ? `• ${a.label}` : ''}
                        </div>
                      )}
                      <div style={styles.actionRow}>
                        <button onClick={() => renameAppointment(a)} style={styles.smallBtn}>Rename</button>
                        <button onClick={() => rescheduleAppointment(a)} style={styles.smallBtn}>Reschedule</button>
                        <button onClick={() => cancelAppointment(a)} style={{ ...styles.smallBtn, background: '#ef4444' }}>
                          Cancel
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Free slots */}
            <div style={styles.panel}>
              <div style={styles.panelTitle}>Free Slots</div>
              {freeSlots.length === 0 ? (
                <div style={styles.empty}>No free slots to display.</div>
              ) : (
                <ul style={styles.list}>
                  {freeSlots.map((slot, i) => (
                    <li key={i} style={styles.listItem}>
                      <div style={styles.row}>
                        <span style={styles.time}>{(slot.start_time || slot.start)} – {(slot.end_time || slot.end)}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Proposed slots */}
            <div style={styles.panel}>
              <div style={styles.panelTitle}>{isPreview ? 'Proposed Slots (Preview)' : 'Proposed Slots'}</div>
              {isPreview && proposals.length > 0 && (
                <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 8 }}>
                  This is a preview — nothing has been created yet.
                </div>
              )}
              {proposals.length === 0 ? (
                <div style={styles.empty}>No proposals yet.</div>
              ) : (
                <>
                  <ul style={styles.list}>
                    {proposals.map((p, i) => (
                      <li key={i} style={styles.listItem}>
                        <div style={styles.row}>
                          <span style={styles.date}>
                            <span style={styles.weekday}>{weekdayName(p.date)}</span>
                            {p.date}
                          </span>
                          <span className="time" style={styles.time}>
                            {(p.start_time || p.start)} – {(p.end_time || p.end)}
                          </span>
                        </div>
                        <div style={styles.desc}>{p.title || p.description || 'Proposed booking'}</div>
                        <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
                          <button
                            onClick={() => (p.source_id || p.selector ? moveSlot(p) : bookSlot(p))}
                            style={{
                              padding: '8px 12px',
                              borderRadius: 10,
                              border: 'none',
                              background: (p.source_id || p.selector) ? '#f59e0b' : '#10b981',
                              color: 'white',
                              cursor: 'pointer',
                              fontWeight: 600,
                            }}
                          >
                            {(p.source_id || p.selector) ? 'Move here' : 'Book this'}
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                  {isPreview && (
                    <div style={{ marginTop: 8 }}>
                      <button
                        onClick={() => { setIsPreview(false); setProposals([]); }}
                        style={styles.smallBtn}
                      >
                        Exit preview
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
            {/* Skipped due to Conflicts */}
            <div style={styles.panel}>
              <div style={styles.panelTitle}>Skipped (Conflicts)</div>
              {skippedConflicts.length === 0 ? (
                <div style={styles.empty}>No skipped items.</div>
              ) : (
                <ul style={styles.list}>
                  {skippedConflicts.map((item, i) => (
                    <li key={i} style={styles.listItem}>
                      {Array.isArray(item) ? (
                        item.map((a, idx) => (
                          <div key={idx} style={{ marginBottom: 6 }}>
                            <div style={styles.row}>
                              <span style={styles.date}>{a.date}</span>
                              <span style={styles.time}>
                                {(a.start_time || a.start)} – {(a.end_time || a.end)}
                              </span>
                            </div>
                            <div style={styles.desc}>{a.title || a.description || '—'}</div>
                          </div>
                        ))
                      ) : (
                        <div>
                          <div style={styles.row}>
                            <span style={styles.date}>{item.date || '—'}</span>
                            <span style={styles.time}>
                              {(item.start_time || item.start) ? `${item.start_time || item.start}${(item.end_time || item.end) ? ' – ' + (item.end_time || item.end) : ''}` : ''}
                            </span>
                          </div>
                          <div style={styles.desc}>{item.title || item.description || '—'}</div>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {skippedConflicts.length > 0 && (
                <div style={{ marginTop: 8 }}>
                  <button onClick={() => setSkippedConflicts([])} style={styles.smallBtn}>Clear</button>
                </div>
              )}
            </div>

            {/* Count */}
            <div style={styles.panel}>
              <div style={styles.panelTitle}>This Month</div>
              <div style={styles.bigNumber}>{count ?? '—'}</div>
            </div>

            {/* Conflicts */}
            <div style={styles.panel}>
              <div style={styles.panelTitle}>Conflicts</div>
              {conflicts.length === 0 ? (
                <div style={styles.empty}>No conflicts found.</div>
              ) : (
                <ul style={styles.list}>
                  {conflicts.map((pair, i) => (
                    <li key={i} style={styles.listItem}>
                      {pair.map((a, idx) => (
                        <div key={idx} style={{ marginBottom: 6 }}>
                          <div style={styles.row}>
                            <span style={styles.date}>{a.date}</span>
                            <span style={styles.time}>
                              {(a.start_time || a.start)} – {(a.end_time || a.end)}
                            </span>
                          </div>
                          <div style={styles.desc}>{a.title || a.description || '—'}</div>
                        </div>
                      ))}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

// ---- styles -----------------------------------------------------------------
const styles = {
  shell: { position: 'relative', minHeight: '100vh', overflow: 'hidden', background: 'linear-gradient(180deg, #E9D5FF 0%, #FBCFE8 100%)' },
  bgA: {
    position: 'absolute', inset: 0,
    background: 'radial-gradient(800px 400px at 10% 0%, rgba(124,58,237,0.15) 0%, rgba(124,58,237,0) 60%), radial-gradient(800px 400px at 90% 10%, rgba(219,39,119,0.12) 0%, rgba(219,39,119,0) 60%)',
    pointerEvents: 'none',
  },
  bgB: { position: 'absolute', inset: 0, background: 'radial-gradient(500px 300px at 50% 100%, rgba(59,130,246,0.12) 0%, rgba(59,130,246,0) 60%)', pointerEvents: 'none' },
  noise: {
    position: 'absolute', inset: 0,
    backgroundImage:
      'url("data:image/svg+xml;utf8,<svg xmlns=\\"http://www.w3.org/2000/svg\\" width=\\"160\\" height=\\"160\\"><filter id=\\"n\\"><feTurbulence type=\\"fractalNoise\\" baseFrequency=\\"0.9\\" numOctaves=\\"2\\" stitchTiles=\\"stitch\\"/></filter><rect width=\\"100%\\" height=\\"100%\\" filter=\\"url(%23n)\\" opacity=\\"0.04\\"/></svg>")',
    backgroundSize: '160px 160px',
    pointerEvents: 'none',
  },
  page: { position: 'relative', display: 'flex', flexDirection: 'column', minHeight: '100vh' },
  header: { padding: '16px 24px', background: 'rgba(255,255,255,0.7)', backdropFilter: 'blur(6px)', borderBottom: '1px solid #e5e7eb' },
  brandRow: { display: 'flex', alignItems: 'center', gap: 12 },
  avatar: { width: 40, height: 40, borderRadius: '50%', background: '#fff', border: '1px solid #ede9fe', boxShadow: '0 2px 8px rgba(124,58,237,.2)', objectFit: 'cover' },
  brand: { fontWeight: 700, color: '#111827', fontSize: 18, letterSpacing: 0.2 },
  subtitle: { fontSize: 12, color: '#6b7280' },
  body: { display: 'grid', gridTemplateColumns: 'minmax(420px, 1.2fr) 1fr', gap: 16, padding: 16, flex: 1 },
  chatCard: { background: 'rgba(255,255,255,0.9)', border: '1px solid #e5e7eb', borderRadius: 16, display: 'flex', flexDirection: 'column', minHeight: 0, boxShadow: '0 10px 30px rgba(17,24,39,.08)' },
  chatHeader: { padding: '12px 16px', borderBottom: '1px solid #e5e7eb', fontWeight: 600, color: '#374151' },
  chatScroll: { padding: 16, overflowY: 'auto', flex: 1 },
  bubble: { maxWidth: 560, padding: '12px 14px', borderRadius: 12, fontSize: 14, lineHeight: 1.45 },
  loading: { fontSize: 12, color: '#6b7280', padding: '0 12px 12px' },
  inputRow: { display: 'flex', gap: 10, padding: 12, borderTop: '1px solid #e5e7eb' },
  input: { flex: 1, padding: '12px 14px', borderRadius: 999, border: '1px solid #d1d5db', outline: 'none', background: 'white', boxShadow: 'inset 0 1px 2px rgba(0,0,0,.03)' },
  sendBtn: {
    padding: '12px 20px', borderRadius: 999, border: 'none',
    background: 'linear-gradient(90deg, #7c3aed, #3b82f6)', color: 'white', cursor: 'pointer', fontWeight: 600,
    boxShadow: '0 6px 16px rgba(124,58,237,.35)', transition: 'transform .06s ease',
  },
  resultsCol: { display: 'grid', gap: 12, alignContent: 'start' },
  panel: { background: 'rgba(255,255,255,0.9)', border: '1px solid #e5e7eb', borderRadius: 16, padding: 14, boxShadow: '0 10px 30px rgba(17,24,39,.06)' },
  panelTitle: { fontWeight: 700, color: '#374151', marginBottom: 10 },
  list: { listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 8 },
  listItem: { background: 'white', border: '1px solid #f3f4f6', borderRadius: 10, padding: 12 },
  row: { display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 6 },
  date: { fontWeight: 700, color: '#111827' },
  weekday: { color: '#6b7280', marginRight: 6, fontWeight: 600 },
  time: { color: '#6b7280' },
  desc: { color: '#374151' },
  bigNumber: { fontSize: 32, fontWeight: 800, color: '#111827' },
  actionRow: { marginTop: 8, display: 'flex', gap: 8 },
  smallBtn: { padding: '8px 12px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', cursor: 'pointer', fontWeight: 600 },
  toastStack: { position: 'fixed', top: 16, right: 16, display: 'grid', gap: 8, zIndex: 1000 },
  toast: { background: 'white', border: '1px solid #e5e7eb', borderRadius: 10, padding: 12, boxShadow: '0 8px 20px rgba(0,0,0,.08)', minWidth: 260, maxWidth: 360 },
  toastBtn: { padding: '6px 10px', borderRadius: 8, border: 'none', background: '#111827', color: 'white', cursor: 'pointer', fontWeight: 600 },
  empty: { color: '#6b7280', fontSize: 14 },
  error: { color: '#b91c1c', fontSize: 12, padding: '0 12px 12px' },
};

export default App;