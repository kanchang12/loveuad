# reset_alarms.py
import psycopg2
import os

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute("UPDATE medication_reminders SET active = true, last_called = NULL")
conn.commit()
print(f"✅ Reset {cur.rowcount} alarms")
conn.close()
