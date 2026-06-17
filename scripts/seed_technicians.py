"""
Seed initial technician data into the new RDS database.

Usage:
    DB_HOST=<rds-endpoint> DB_PASSWORD=<password> python scripts/seed_technicians.py
"""

import os
import sys
import psycopg2
from psycopg2.extras import execute_values

DB_CONFIG = {
    "host":     os.environ.get("DB_HOST", "localhost"),
    "port":     int(os.environ.get("DB_PORT", 5432)),
    "dbname":   os.environ.get("DB_NAME", "tickets_db"),
    "user":     os.environ.get("DB_USER", "ticketing_admin"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "sslmode":  "require",
}

# Technicians — extend this list with real data before running
TECHNICIANS = [
    {
        "tech_id":   "TECH001",
        "tech_name": "Alice Johnson",
        "tech_mail": "alice.johnson@company.com",
        "skills":    "Network, VPN, Remote Access, Firewall, TCP/IP",
        "status":    "available",
    },
    {
        "tech_id":   "TECH002",
        "tech_name": "Bob Smith",
        "tech_mail": "bob.smith@company.com",
        "skills":    "Cloud, Email, Office 365, OneDrive, SharePoint, Cloud Workspace",
        "status":    "available",
    },
    {
        "tech_id":   "TECH003",
        "tech_name": "Carol Davis",
        "tech_mail": "carol.davis@company.com",
        "skills":    "Hardware, Assessment, Printer, Printing",
        "status":    "available",
    },
    {
        "tech_id":   "TECH004",
        "tech_name": "David Kim",
        "tech_mail": "david.kim@company.com",
        "skills":    "Active Directory, File Permissions, Access Control, LDAP",
        "status":    "available",
    },
    {
        "tech_id":   "TECH005",
        "tech_name": "Emma Wilson",
        "tech_mail": "emma.wilson@company.com",
        "skills":    "Server, Administration, Database, Linux, Windows Server",
        "status":    "available",
    },
    {
        "tech_id":   "TECH006",
        "tech_name": "Frank Lee",
        "tech_mail": "frank.lee@company.com",
        "skills":    "Software, Installation, SaaS, Application Support",
        "status":    "available",
    },
    {
        "tech_id":   "TECH007",
        "tech_name": "Grace Patel",
        "tech_mail": "grace.patel@company.com",
        "skills":    "Cybersecurity, Intrusion, Security, Password, Email Security",
        "status":    "available",
    },
    {
        "tech_id":   "TECH008",
        "tech_name": "Henry Chen",
        "tech_mail": "henry.chen@company.com",
        "skills":    "Backup, DATTO, Azure, Backup Management, Disaster Recovery",
        "status":    "wfh",
    },
]

SQL = """
    INSERT INTO technician_data (tech_id, tech_name, tech_mail, skills, status)
    VALUES %s
    ON CONFLICT (tech_id) DO UPDATE SET
        tech_name = EXCLUDED.tech_name,
        tech_mail = EXCLUDED.tech_mail,
        skills    = EXCLUDED.skills,
        status    = EXCLUDED.status
"""

def main():
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        rows = [(t["tech_id"], t["tech_name"], t["tech_mail"], t["skills"], t["status"])
                for t in TECHNICIANS]
        with conn.cursor() as cur:
            execute_values(cur, SQL, rows)
        conn.commit()
        print(f"✅ Seeded {len(rows)} technicians")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
