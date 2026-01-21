
"""
Update database schema to include companyid in user_data and technician_data
"""
import sys
import os

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.db_connection import DatabaseConnection

def update_schema():
    print("Updating database schema...")
    
    try:
        db_conn = DatabaseConnection()
        
        # 1. Add companyid to technician_data
        print("\nChecking/Updating technician_data table...")
        query_tech = """
        ALTER TABLE technician_data 
        ADD COLUMN IF NOT EXISTS companyid VARCHAR(100);
        """
        db_conn.execute_query(query_tech, fetch=False)
        print("✓ Added companyid column to technician_data")
        
        # 2. Add companyid to user_data
        print("\nChecking/Updating user_data table...")
        query_user = """
        ALTER TABLE user_data 
        ADD COLUMN IF NOT EXISTS companyid VARCHAR(100);
        """
        db_conn.execute_query(query_user, fetch=False)
        print("✓ Added companyid column to user_data")
        
        # 3. Update existing records with a default companyid if null
        # We'll use '0001' as default for existing records
        print("\nUpdating existing records with default companyid '0001'...")
        
        update_tech = "UPDATE technician_data SET companyid = '0001' WHERE companyid IS NULL"
        db_conn.execute_query(update_tech, fetch=False)
        print("✓ Updated existing technicians")
        
        update_user = "UPDATE user_data SET companyid = '0001' WHERE companyid IS NULL"
        db_conn.execute_query(update_user, fetch=False)
        print("✓ Updated existing users")
        
        print("\nSchema update completed successfully!")
        return True
        
    except Exception as e:
        print(f"\n❌ Error updating schema: {e}")
        return False

if __name__ == "__main__":
    update_schema()
