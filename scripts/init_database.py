#!/usr/bin/env python3
"""
Database initialization script
Creates all required tables in the PostgreSQL database
"""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from src.config import Config

def init_database():
    """Initialize database by creating all required tables"""
    
    db_config = Config.get_db_config()
    
    print("Connecting to database...")
    try:
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()
        print("✓ Connected to database")
    except Exception as e:
        print(f"✗ Error connecting to database: {e}")
        sys.exit(1)
    
    # Read SQL file
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sql_file = os.path.join(project_root, 'src', 'database', 'create_tables.sql')
    
    if not os.path.exists(sql_file):
        print(f"✗ SQL file not found: {sql_file}")
        sys.exit(1)
    
    print(f"Reading SQL file: {sql_file}")
    with open(sql_file, 'r') as f:
        sql_script = f.read()
    
    # Execute SQL script
    print("Creating tables...")
    try:
        cur.execute(sql_script)
        conn.commit()
        print("✓ Tables created successfully!")
    except Exception as e:
        conn.rollback()
        print(f"✗ Error creating tables: {e}")
        sys.exit(1)
    
    # Verify tables were created
    print("\nVerifying tables...")
    cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_type = 'BASE TABLE'
        ORDER BY table_name;
    """)
    
    tables = cur.fetchall()
    print(f"✓ Found {len(tables)} tables:")
    for table in tables:
        print(f"  - {table[0]}")
    
    # Check if resolved_tickets has data
    cur.execute("SELECT COUNT(*) FROM resolved_tickets;")
    count = cur.fetchone()[0]
    print(f"\n✓ resolved_tickets table has {count} records")
    
    cur.close()
    conn.close()
    print("\n✓ Database initialization completed successfully!")

if __name__ == '__main__':
    init_database()

