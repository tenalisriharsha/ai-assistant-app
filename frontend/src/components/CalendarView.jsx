import React, { useEffect, useState } from 'react';
import { fetchAppointments } from '../api';

function CalendarView() {
  const [appointments, setAppointments] = useState([]);

  const handleToday = async () => {
    try {
      const { appointments: appts } = await fetchAppointments({ action: 'today' });
      setAppointments(appts);
    } catch (err) {
      console.error(err);
    }
  };

  const handleThisWeek = async () => {
    try {
      const { appointments: appts } = await fetchAppointments({ action: 'this_week' });
      setAppointments(appts);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    // Dynamically load the calendar script
    const script = document.createElement("script");
    script.src = "/calendar/scripts/index.js";
    script.type = "module";
    script.onload = () => {
      console.log("Calendar script loaded");
    };
    document.body.appendChild(script);

    // Load today's appointments on startup
    handleToday();
  }, []);

  return (
    <>
      {/* Load CSS from public folder */}
      <link rel="stylesheet" href="/calendar/index.css" />

      <div className="controls" style={{ padding: '10px' }}>
        <button onClick={handleToday}>Today</button>
        <button onClick={handleThisWeek}>This Week</button>
      </div>

      <div id="calendar-wrapper">
        <div className="app">
          <main className="main">
            {/* Calendar gets injected into this div by the script */}
            <div className="calendar" data-calendar></div>
          </main>

          {/* Appointments List (Optional) */}
          {appointments && appointments.length > 0 && (
            <div style={{ padding: '20px' }}>
              <h2>Matching Appointments</h2>
              <ul>
                {appointments.map((appt, index) => (
                  <li key={index}>
                    <strong>{appt.date}</strong> — {appt.start_time} to {appt.end_time}: {appt.description}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

export default CalendarView;