import pandas as pd

data = {
    'Date': ['2025-08-05', '2025-08-05', '2025-08-06', '2025-08-07'],
    'StartTime': ['03:00 PM', '01:00 PM', '10:00 AM', '04:00 PM'],
    'EndTime': ['04:00 PM', '02:00 PM', '11:00 AM', '05:00 PM'],
    'Description': [
        'Doctor appointment',
        'Project status meeting',
        'Gym session',
        'Call with client'
    ]
}

df = pd.DataFrame(data)
df.to_excel('appointments.xlsx', index=False)
print("appointments.xlsx created successfully.")
