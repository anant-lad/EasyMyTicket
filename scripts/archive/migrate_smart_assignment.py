#!/usr/bin/env python3
"""
Database migration script for smart ticket assignment
Adds status column and creates ticket_assignments table
"""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from src.config import Config

def migrate_database():
    """Apply database migrations for smart assignment feature"""
    
    print("Starting database migration for smart ticket assignment...")
    
    try:
        conn = psycopg2.connect(**Config.get_db_config())
        cur = conn.cursor()
        print("✓ Connected to database")
    except Exception as e:
        print(f"✗ Error connecting to database: {e}")
        sys.exit(1)

    try:
        # Migration 1: Add status column to technician_data
        print("\n1. Adding 'status' column to technician_data...")
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='technician_data' AND column_name='status';
        """)
        
        if cur.fetchone():
            print("   ℹ 'status' column already exists, skipping...")
        else:
            cur.execute("""
                ALTER TABLE technician_data 
                ADD COLUMN status VARCHAR(50) DEFAULT 'available';
            """)
            print("   ✓ Added 'status' column")
        
        # Migration 2: Add assigned_tech_id to new_tickets
        print("\n2. Adding 'assigned_tech_id' column to new_tickets...")
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='new_tickets' AND column_name='assigned_tech_id';
        """)
        
        if cur.fetchone():
            print("   ℹ 'assigned_tech_id' column already exists, skipping...")
        else:
            cur.execute("""
                ALTER TABLE new_tickets 
                ADD COLUMN assigned_tech_id VARCHAR(100);
            """)
            print("   ✓ Added 'assigned_tech_id' column")
        
        # Migration 3: Create ticket_assignments table
        print("\n3. Creating 'ticket_assignments' table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_assignments (
                id SERIAL PRIMARY KEY,
                ticket_number VARCHAR(100) NOT NULL,
                tech_id VARCHAR(100) NOT NULL,
                assigned_at TIMESTAMP DEFAULT NOW(),
                unassigned_at TIMESTAMP,
                assignment_status VARCHAR(50) DEFAULT 'assigned',
                assignment_reason TEXT,
                skill_match_score INTEGER,
                FOREIGN KEY (tech_id) REFERENCES technician_data(tech_id)
            );
        """)
        print("   ✓ Created 'ticket_assignments' table")
        
        # Migration 4: Create index on ticket_number for faster lookups
        print("\n4. Creating indexes...")
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ticket_assignments_ticket_number 
            ON ticket_assignments(ticket_number);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ticket_assignments_tech_id 
            ON ticket_assignments(tech_id);
        """)
        print("   ✓ Created indexes")
        
        conn.commit()
        print("\n✓ All migrations completed successfully!")
        
        # Verify migrations
        print("\nVerifying migrations...")
        cur.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name='technician_data' 
            ORDER BY ordinal_position;
        """)
        print(f"   technician_data columns: {[row[0] for row in cur.fetchall()]}")
        
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_name='ticket_assignments';
        """)
        if cur.fetchone():
            print("   ✓ ticket_assignments table exists")
        
    except Exception as e:
        conn.rollback()
        print(f"\n✗ Error during migration: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    migrate_database()
