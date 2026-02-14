import psycopg2
import os
import sys

# Add src to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.config import Config

try:
    conn = psycopg2.connect(**Config.get_db_config())
    cur = conn.cursor()
    cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'notifications');")
    exists = cur.fetchone()[0]
    print(f"Notifications table exists: {exists}")
    
    if exists:
        cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'notifications';")
        cols = cur.fetchall()
        print("Columns:", cols)
    
    conn.close()
except Exception as e:
    print(f"Error: {e}")
