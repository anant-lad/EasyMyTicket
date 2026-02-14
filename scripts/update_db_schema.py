
import sys
import os

# Add the project root to the python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.db_connection import DatabaseConnection

def update_schema():
    print("🔄 Starting schema update...")
    db = DatabaseConnection()
    conn = db.get_connection()
    
        with conn.cursor() as cur:
            # Check availability
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='technician_data' AND column_name='availability';
            """)
            if cur.fetchone():
                print("   ✓ 'availability' column already exists")
            else:
                print("   ➕ Adding 'availability' column...")
                cur.execute("ALTER TABLE technician_data ADD COLUMN availability VARCHAR(50) DEFAULT 'available';")
                cur.execute("UPDATE technician_data SET availability = 'available' WHERE availability IS NULL;")

            # Optionally drop 'status' if it exists to clean up
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='technician_data' AND column_name='status';
            """)
            if cur.fetchone():
                print("   🗑️  Cleaning up old 'status' column...")
                cur.execute("ALTER TABLE technician_data DROP COLUMN status;")

            conn.commit()
            print("✅ Schema update completed successfully!")

    except Exception as e:
        conn.rollback()
        print(f"❌ Error updating schema: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    update_schema()
