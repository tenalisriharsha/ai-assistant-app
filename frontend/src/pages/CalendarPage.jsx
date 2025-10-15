// src/pages/CalendarPage.jsx
import React from 'react';

const CalendarPage = () => {
  return (
    <div style={{ height: '100vh', width: '100vw', overflow: 'hidden' }}>
      <iframe
        src="/calendar/index.html"
        title="Calendar"
        style={{
          width: '100%',
          height: '100%',
          border: 'none'
        }}
      />
    </div>
  );
};

export default CalendarPage;