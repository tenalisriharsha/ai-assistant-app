// VanillaCalendar.jsx
import React, { useEffect } from 'react';

const VanillaCalendar = () => {
  useEffect(() => {
    // Dynamically inject stylesheet from public folder
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/calendar/index.css'; // Make sure it's placed in public/calendar/
    document.head.appendChild(link);

    // Dynamically load calendar JS script
    const script = document.createElement('script');
    script.src = '/calendar/scripts/index.js'; // Also in public folder
    script.type = 'module';
    script.onload = () => console.log('Calendar script loaded');
    document.body.appendChild(script);
  }, []);

  // JSX replacement for the <body> from the provided HTML
  return (
    <div className="app">
      <header className="header">
        <h1>Vanilla Calendar</h1>
      </header>
      <main className="main-content">
        <section className="calendar-section">
          <div className="calendar-container">
            <div className="calendar" data-calendar></div>
          </div>
        </section>
        <section className="calendar-controls">
          <form className="calendar-form">
            <label htmlFor="date-input" className="calendar-label">
              Select date:
            </label>
            <input
              type="date"
              id="date-input"
              name="date"
              className="calendar-date-input"
            />
            <button type="submit" className="calendar-submit-button">
              Go
            </button>
          </form>
        </section>
        <section className="calendar-info">
          <div className="calendar-info-content">
            <p>
              Welcome to the Vanilla Calendar! Use the calendar above to pick a date, or enter one manually.
            </p>
          </div>
        </section>
        {/* Example dialog/template conversion */}
        <div className="calendar-dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title" style={{ display: "none" }}>
          <div className="calendar-dialog-content">
            <h2 id="dialog-title">Dialog Title</h2>
            <p>This is a dialog example, converted from &lt;dialog&gt; or &lt;template&gt;.</p>
            <button className="calendar-dialog-close">Close</button>
          </div>
        </div>
      </main>
      <footer className="footer">
        <p>
          &copy; {new Date().getFullYear()} Vanilla Calendar Demo
        </p>
      </footer>
    </div>
  );
};

export default VanillaCalendar;
