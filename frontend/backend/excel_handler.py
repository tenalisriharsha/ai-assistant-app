import pandas as pd

def get_appointments_between(date_str, start_time_str, end_time_str):
    df = pd.read_excel("appointments.xlsx")
    df['Date'] = pd.to_datetime(df['Date']).dt.date
    df['StartTime'] = pd.to_datetime(df['StartTime']).dt.time
    df['EndTime'] = pd.to_datetime(df['EndTime']).dt.time

    from datetime import datetime, time
    query_date = pd.to_datetime(date_str).date()
    start = datetime.strptime(start_time_str, '%I:%M %p').time()
    end = datetime.strptime(end_time_str, '%I:%M %p').time()

    result = df[(df['Date'] == query_date) &
                (df['StartTime'] >= start) & (df['EndTime'] <= end)]

    return [
        {
            "Date": str(row["Date"]),
            "StartTime": row["StartTime"].strftime('%H:%M'),
            "EndTime": row["EndTime"].strftime('%H:%M'),
            "Description": row["Description"]
        }
        for _, row in result.iterrows()
    ]