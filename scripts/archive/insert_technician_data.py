#!/usr/bin/env python3
"""
Script to populate technician_data table with verified IT skills
"""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from src.config import Config

def populate_technicians():
    technicians = [
        {
            "tech_id": "T001",
            "tech_name": "Anant",
            "tech_mail": "anantlad66@gmail.com",
            "tech_password": "T@001",
            "skills": "Cloud Workspace Administration, Email Configuration, Email Security, Password Management, Office 365, OneDrive, SharePoint"
        },
        {
            "tech_id": "T002",
            "tech_name": "Raj",
            "tech_mail": "anantlad0628@gmail.com",
            "tech_password": "T@002",
            "skills": "Network Configuration, Hardware Setup, Software Installation, VPN & Remote Access, Assessment & Site Survey, Printer Setup"
        },
        {
            "tech_id": "T003",
            "tech_name": "Vidhi",
            "tech_mail": "adityapawar9767@gmail.com",
            "tech_password": "T@003",
            "skills": "Backup Management (DATTO, Azure), Server Administration, Active Directory, Cybersecurity, File Permissions, Access Control"
        }
    ]

    print("Connecting to database...")
    try:
        conn = psycopg2.connect(**Config.get_db_config())
        cur = conn.cursor()
        print("✓ Connected to database")
    except Exception as e:
        print(f"✗ Error connecting to database: {e}")
        sys.exit(1)

    try:
        print("Inserting technician data...")
        for tech in technicians:
            cur.execute("""
                INSERT INTO technician_data (tech_id, tech_name, tech_mail, tech_password, skills)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (tech_id) DO UPDATE SET
                    tech_name = EXCLUDED.tech_name,
                    tech_mail = EXCLUDED.tech_mail,
                    tech_password = EXCLUDED.tech_password,
                    skills = EXCLUDED.skills;
            """, (tech["tech_id"], tech["tech_name"], tech["tech_mail"], tech["tech_password"], tech["skills"]))
        
        conn.commit()
        print(f"✓ Successfully inserted/updated {len(technicians)} technicians")
        
        # Verify
        cur.execute("SELECT tech_id, tech_name FROM technician_data")
        rows = cur.fetchall()
        print("\nCurrent technicians in database:")
        for row in rows:
            print(f"  - {row[0]}: {row[1]}")

    except Exception as e:
        conn.rollback()
        print(f"✗ Error populating technician data: {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    populate_technicians()
