#!/usr/bin/env python3
"""
Import all tickets from ticket_data_updated.csv into closed_tickets table
"""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from src.config import Config

def import_closed_tickets():
    """Import all tickets from CSV into closed_tickets table"""
    # Get project root directory
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    excel_file = os.path.join(project_root, 'dataset', 'ticket_data_updated.csv')
    print(f"Reading Excel file: {excel_file}")
    df = pd.read_excel(excel_file)
    
    # Convert column names to lowercase to match database
    df.columns = df.columns.str.lower()
    
    # Handle datetime columns - convert to datetime, then to string for PostgreSQL
    datetime_columns = ['completeddate', 'createdate', 'duedatetime', 'firstresponsedatetime', 
                       'lastactivitydate', 'resolutionplandatetime', 'resolveddatetime']
    
    for col in datetime_columns:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
            df[col] = df[col].replace('NaT', None)
    
    # Replace NaN with None for proper NULL handling
    df = df.where(pd.notnull(df), None)
    
    # Connect to database
    print("Connecting to database...")
    conn = psycopg2.connect(**Config.get_db_config())
    cur = conn.cursor()
    
    # Create closed_tickets table if it doesn't exist
    print("Ensuring closed_tickets table exists...")
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS closed_tickets (
        id SERIAL PRIMARY KEY,
        companyid VARCHAR(100),
        completeddate TIMESTAMP,
        createdate TIMESTAMP,
        description TEXT,
        duedatetime TIMESTAMP,
        estimatedhours NUMERIC(10, 2),
        firstresponsedatetime TIMESTAMP,
        issuetype VARCHAR(100),
        lastactivitydate TIMESTAMP,
        priority VARCHAR(50),
        queueid VARCHAR(100),
        resolution TEXT,
        resolutionplandatetime TIMESTAMP,
        resolveddatetime TIMESTAMP,
        status VARCHAR(50),
        subissuetype VARCHAR(100),
        ticketcategory VARCHAR(100),
        ticketnumber VARCHAR(100) UNIQUE,
        tickettype VARCHAR(100),
        title TEXT
    );
    """
    cur.execute(create_table_sql)
    conn.commit()
    print("✓ closed_tickets table ready")
    
    # Prepare data for insertion
    columns = ['companyid', 'completeddate', 'createdate', 'description', 'duedatetime',
               'estimatedhours', 'firstresponsedatetime', 'issuetype', 'lastactivitydate',
               'priority', 'queueid', 'resolution', 'resolutionplandatetime', 'resolveddatetime',
               'status', 'subissuetype', 'ticketcategory', 'ticketnumber', 'tickettype', 'title']
    
    # Filter columns that exist in dataframe
    available_columns = [col for col in columns if col in df.columns]
    df_filtered = df[available_columns]
    
    print(f"Total tickets to import: {len(df_filtered)}")
    print(f"Columns to import: {available_columns}")
    
    # Insert ALL tickets into closed_tickets table
    if len(df_filtered) > 0:
        print("Inserting all tickets into closed_tickets table...")
        ticket_values = [tuple(row) for row in df_filtered.values]
        insert_query = f"""
            INSERT INTO closed_tickets ({', '.join(available_columns)})
            VALUES %s
            ON CONFLICT (ticketnumber) DO NOTHING
        """
        execute_values(cur, insert_query, ticket_values)
        print(f"✅ Inserted {cur.rowcount} tickets into closed_tickets table")
    else:
        print("⚠️  No tickets to import")
    
    # Verify the import
    cur.execute("SELECT COUNT(*) FROM closed_tickets;")
    count = cur.fetchone()[0]
    print(f"✅ Total tickets in closed_tickets table: {count}")
    
    # Commit and close
    conn.commit()
    cur.close()
    conn.close()
    print("✅ Data import completed successfully!")

if __name__ == '__main__':
    import_closed_tickets()

