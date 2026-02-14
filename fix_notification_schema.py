import psycopg2
from src.config import Config

def fix_schema():
    print("Checking notifications table schema...")
    try:
        conn = psycopg2.connect(**Config.get_db_config())
        conn.autocommit = True
        cur = conn.cursor()

        # Check existing columns
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'notifications'")
        columns = [row[0] for row in cur.fetchall()]
        print(f"Existing columns: {columns}")

        # specific checks
        has_recipient_id = 'recipient_id' in columns
        has_user_id = 'user_id' in columns
        has_read = 'read' in columns
        has_is_read = 'is_read' in columns

        print(f"Has user_id: {has_user_id}, Has recipient_id: {has_recipient_id}")
        print(f"Has read: {has_read}, Has is_read: {has_is_read}")

        # Add missing columns for Entity linking
        if 'related_entity_id' not in columns:
            print("Adding related_entity_id column...")
            cur.execute("ALTER TABLE notifications ADD COLUMN related_entity_id VARCHAR(100)")
        
        if 'related_entity_type' not in columns:
             print("Adding related_entity_type column...")
             cur.execute("ALTER TABLE notifications ADD COLUMN related_entity_type VARCHAR(100)")

        # Handle column aliasing/renaming if needed?
        # Decide: Do we rename 'user_id' to 'recipient_id' or just adapt code?
        # Adapting code is safer. But for now we just ensuring we have the entity columns.

        print("Schema fix complete.")
        cur.close()
        conn.close()

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fix_schema()
