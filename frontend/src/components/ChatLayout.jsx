// src/components/ChatLayout.jsx
import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import { PaperAirplaneIcon, ClockIcon } from '@heroicons/react/24/outline';

export default function ChatLayout() {
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState([
    { from: 'bot', text: "Hello! I'm Scheduler AI, your intelligent scheduling assistant ✨ Ask about today, this week, free time, weekends, counts, conflicts…" }
  ]);

  const [appointments, setAppointments] = useState([]);
  const [freeSlots, setFreeSlots] = useState([]);
  const [count, setCount] = useState(null);
  const [conflicts, setConflicts] = useState([]);
  const [nextAppt, setNextAppt] = useState(null);
  const [loading, setLoading] = useState(false);

  const scrollRef = useRef(null);
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, appointments, freeSlots, count, conflicts, nextAppt]);

  const sendQuery = async () => {
    const trimmed = query.trim();
    if (!trimmed) return;

    setMessages(msgs => [...msgs, { from: 'user', text: trimmed }]);
    setLoading(true);

    // structured shortcuts same as App.js
    const lower = trimmed.toLowerCase();
    let payload;
    if (lower.includes('today')) payload = { action: 'today' };
    else if (lower.includes('this week')) payload = { action: 'this_week' };
    else payload = { query: trimmed };

    try {
      const res = await axios.post('http://127.0.0.1:5000/query', payload, {
        headers: { 'Content-Type': 'application/json' }
      });

      // clear previous panels
      setAppointments([]);
      setFreeSlots([]);
      setCount(null);
      setConflicts([]);
      setNextAppt(null);

      setMessages(msgs => [...msgs, { from: 'bot', text: 'Here are your results:' }]);

      if (Array.isArray(res.data.appointments)) setAppointments(res.data.appointments);
      if (Array.isArray(res.data.free)) setFreeSlots(res.data.free);
      if (typeof res.data.count === 'number') setCount(res.data.count);
      if (res.data.appointment) setNextAppt(res.data.appointment);
      if (Array.isArray(res.data.conflicts)) setConflicts(res.data.conflicts);
    } catch (e) {
      const msg = e.response?.data?.error || 'Oops, something went wrong.';
      setMessages(msgs => [...msgs, { from: 'bot', text: msg }]);
    } finally {
      setLoading(false);
      setQuery('');
    }
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendQuery();
    }
  };

  return (
    <div className="h-screen flex flex-col bg-gradient-to-b from-purple-200 to-pink-200">
      {/* Header */}
      <header className="flex items-center justify-between p-4 bg-white bg-opacity-70 backdrop-blur-md border-b border-gray-200">
        <div className="flex items-center space-x-2">
          <ClockIcon className="h-6 w-6 text-purple-600" />
          <h1 className="text-xl font-semibold text-gray-800">Scheduler AI</h1>
        </div>
        <p className="text-sm text-gray-600">Your intelligent scheduling assistant</p>
      </header>

      {/* Body */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-2 gap-3 p-3">
        {/* Chat */}
        <section className="bg-white/85 border border-gray-200 rounded-xl flex flex-col min-h-0">
          <div className="px-4 py-3 border-b border-gray-200 font-semibold text-gray-700">
            Chat
          </div>
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.from === 'bot' ? 'justify-start' : 'justify-end'}`}>
                <div
                  className={`max-w-[520px] px-3 py-2 rounded-xl text-sm leading-relaxed
                    ${m.from === 'bot'
                      ? 'bg-white border border-gray-200 text-gray-900'
                      : 'bg-blue-500 text-white'}`}
                >
                  {m.text}
                </div>
              </div>
            ))}
            {loading && <div className="text-xs text-gray-500 px-1">Thinking…</div>}
          </div>

          <div className="p-3 border-t border-gray-200 flex items-center space-x-2">
            <input
              className="flex-1 p-3 rounded-full border border-gray-300 focus:outline-none focus:ring-2 focus:ring-purple-400"
              placeholder='Ask: “today”, “this week”, “free time tomorrow”, “how many this month”, “conflicts on Aug 5”…'
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={onKeyDown}
            />
            <button
              onClick={sendQuery}
              className="p-3 bg-purple-600 rounded-full hover:bg-purple-700 focus:outline-none"
              aria-label="Send"
            >
              <PaperAirplaneIcon className="h-5 w-5 text-white rotate-90" />
            </button>
          </div>
        </section>

        {/* Results column */}
        <section className="grid gap-3 content-start">
          {/* Next upcoming */}
          <div className="bg-white/90 border border-gray-200 rounded-xl p-3">
            <div className="font-semibold text-gray-700 mb-2">Next Appointment</div>
            {!nextAppt ? (
              <div className="text-gray-500 text-sm">—</div>
            ) : (
              <div className="bg-white border border-gray-100 rounded-md p-2">
                <div className="flex justify-between text-sm mb-1">
                  <span className="font-semibold text-gray-900">{nextAppt.date}</span>
                  <span className="text-gray-600">{nextAppt.start_time} – {nextAppt.end_time}</span>
                </div>
                <div className="text-gray-700 text-sm">{nextAppt.description || '—'}</div>
              </div>
            )}
          </div>

          {/* Appointments */}
          <div className="bg-white/90 border border-gray-200 rounded-xl p-3">
            <div className="font-semibold text-gray-700 mb-2">Appointments</div>
            {appointments.length === 0 ? (
              <div className="text-gray-500 text-sm">No appointments to display.</div>
            ) : (
              <ul className="space-y-2">
                {appointments.map(a => (
                  <li key={a.id ?? `${a.date}-${a.start_time}-${a.end_time}`} className="bg-white border border-gray-100 rounded-md p-2">
                    <div className="flex justify-between text-sm mb-1">
                      <span className="font-semibold text-gray-900">{a.date}</span>
                      <span className="text-gray-600">{a.start_time} – {a.end_time}</span>
                    </div>
                    <div className="text-gray-700 text-sm">{a.description || '—'}</div>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Free slots */}
          <div className="bg-white/90 border border-gray-200 rounded-xl p-3">
            <div className="font-semibold text-gray-700 mb-2">Free Slots</div>
            {freeSlots.length === 0 ? (
              <div className="text-gray-500 text-sm">No free slots to display.</div>
            ) : (
              <ul className="space-y-2">
                {freeSlots.map((s, i) => (
                  <li key={i} className="bg-white border border-gray-100 rounded-md p-2 text-sm text-gray-700">
                    {s.start} – {s.end}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Count */}
          <div className="bg-white/90 border border-gray-200 rounded-xl p-3">
            <div className="font-semibold text-gray-700 mb-2">This Month</div>
            <div className="text-2xl font-bold text-gray-900">{count ?? '—'}</div>
          </div>

          {/* Conflicts */}
          <div className="bg-white/90 border border-gray-200 rounded-xl p-3">
            <div className="font-semibold text-gray-700 mb-2">Conflicts</div>
            {conflicts.length === 0 ? (
              <div className="text-gray-500 text-sm">No conflicts found.</div>
            ) : (
              <ul className="space-y-2">
                {conflicts.map((pair, i) => (
                  <li key={i} className="bg-white border border-gray-100 rounded-md p-2">
                    {pair.map((a, idx) => (
                      <div key={idx} className="mb-2 last:mb-0">
                        <div className="flex justify-between text-sm mb-0.5">
                          <span className="font-semibold text-gray-900">{a.date}</span>
                          <span className="text-gray-600">{a.start_time} – {a.end_time}</span>
                        </div>
                        <div className="text-gray-700 text-sm">{a.description || '—'}</div>
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
  );
}