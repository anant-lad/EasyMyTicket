
import os
import sys

# Add src to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_connection import DatabaseConnection

print("Initializing DatabaseConnection to trigger migrations...")
try:
    db = DatabaseConnection()
    print("Migration check complete.")
except Exception as e:
    print(f"Error: {e}")
