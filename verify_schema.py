
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DB_HOST = "localhost"
DB_PORT = 5433
DB_NAME = "tickets_db"
DB_USER = "admin"
DB_PASSWORD = os.getenv("DB_PASSWORD")

try:
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )
    cur = conn.cursor()
    
    print("Checking user_data columns:")
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'user_data'")
    columns = {row[0]: row[1] for row in cur.fetchall()}
    print(columns)
    
    required = ['companyid', 'role', 'password_hash']
    missing = [col for col in required if col not in columns]
    
    if missing:
        print(f"MISSING: {missing}")
    else:
        print("ALL COLUMNS PRESENT")

except Exception as e:
    print(f"Error: {e}")
