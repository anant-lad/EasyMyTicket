#!/usr/bin/env python3
"""
Script to add user_id column to existing new_tickets table
(One-time migration script - already applied)
"""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from src.config import Config

def add_user_id_column():
    """Add user_id column to new_tickets table if it doesn't exist"""
    db_config = Config.get_db_config()
    
    print("Connecting to database...")
    try:
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()
        print("✓ Connected to database")
    except Exception as e:
        print(f"✗ Error connecting to database: {e}")
        return
    
    # Check if column exists
    cur.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='new_tickets' AND column_name='user_id';
    """)
    
    if cur.fetchone():
        print("✓ Column 'user_id' already exists in new_tickets table")
    else:
        print("Adding 'user_id' column to new_tickets table...")
        try:
            cur.execute("ALTER TABLE new_tickets ADD COLUMN user_id VARCHAR(100);")
            conn.commit()
            print("✓ Column 'user_id' added successfully!")
        except Exception as e:
            conn.rollback()
            print(f"✗ Error adding column: {e}")
    
    cur.close()
    conn.close()

if __name__ == '__main__':
    add_user_id_column()

