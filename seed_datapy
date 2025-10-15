# seed_data.py

from models import Appointment, init_db, SessionLocal
from datetime import date, time, timedelta

# Make sure the tables exist
init_db()

db = SessionLocal()

start_date = date.today()
end_date = date(2025, 8, 15)

appointments = []
current = start_date
while current <= end_date:
    # Example appointments — feel free to tweak descriptions/times
    appointments.append(
        Appointment(date=current, start_time=time(9, 0),   end_time=time(10, 0),  description="Morning stand-up")
    )
    appointments.append(
        Appointment(date=current, start_time=time(13, 0),  end_time=time(14, 0),  description="Lunch break")
    )
    appointments.append(
        Appointment(date=current, start_time=time(16, 0),  end_time=time(17, 0),  description="Wrap-up / Review")
    )
    current += timedelta(days=1)

db.add_all(appointments)
db.commit()
db.close()

print(f"Seeded {len(appointments)} appointments from {start_date} to {end_date}.")
