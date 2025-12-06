#!/usr/bin/env python3
"""
Legacy script for importing tickets into resolved_tickets table
Note: This script is kept for reference but is not actively used.
Use import_closed_tickets.py instead.
"""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from src.config import Config

def import_tickets():
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
    
    # Prepare data for insertion
    columns = ['companyid', 'completeddate', 'createdate', 'description', 'duedatetime',
               'estimatedhours', 'firstresponsedatetime', 'issuetype', 'lastactivitydate',
               'priority', 'queueid', 'resolution', 'resolutionplandatetime', 'resolveddatetime',
               'status', 'subissuetype', 'ticketcategory', 'ticketnumber', 'tickettype', 'title']
    
    # Filter columns that exist in dataframe
    available_columns = [col for col in columns if col in df.columns]
    df_filtered = df[available_columns]
    
    # Split into resolved and new tickets based on resolveddatetime
    # Tickets with resolveddatetime are considered resolved
    has_resolved_datetime = df_filtered['resolveddatetime'].notna()
    resolved_df = df_filtered[has_resolved_datetime]
    new_df = df_filtered[~has_resolved_datetime]
    
    print(f"Total tickets: {len(df_filtered)}")
    print(f"Resolved tickets (with resolveddatetime): {len(resolved_df)}")
    print(f"New tickets (without resolveddatetime): {len(new_df)}")
    
    # Insert into resolved_tickets
    if len(resolved_df) > 0:
        print("Inserting resolved tickets...")
        resolved_values = [tuple(row) for row in resolved_df.values]
        insert_query = f"""
            INSERT INTO resolved_tickets ({', '.join(available_columns)})
            VALUES %s
            ON CONFLICT (ticketnumber) DO NOTHING
        """
        execute_values(cur, insert_query, resolved_values)
        print(f"Inserted {cur.rowcount} resolved tickets")
    
    # Insert into new_tickets
    if len(new_df) > 0:
        print("Inserting new tickets...")
        new_values = [tuple(row) for row in new_df.values]
        insert_query = f"""
            INSERT INTO new_tickets ({', '.join(available_columns)})
            VALUES %s
            ON CONFLICT (ticketnumber) DO NOTHING
        """
        execute_values(cur, insert_query, new_values)
        print(f"Inserted {cur.rowcount} new tickets")
    
    # Commit and close
    conn.commit()
    cur.close()
    conn.close()
    print("Data import completed successfully!")

if __name__ == '__main__':
    import_tickets()

