"""
Database restart utility
Restarts the database container and optionally updates the password to match .env
"""
import subprocess
import time
from typing import Tuple
from src.config import Config


def restart_database_container(container_name: str = "Autotask") -> Tuple[bool, str]:
    """
    Restart the database container without deleting it
    Returns (success, message)
    """
    try:
        print(f"🔄 Restarting container {container_name}...")
        
        # Stop the container
        stop_result = subprocess.run(
            ["docker", "stop", container_name],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if stop_result.returncode != 0 and "No such container" not in stop_result.stderr:
            return False, f"Failed to stop container: {stop_result.stderr}"
        
        # Wait a moment
        time.sleep(2)
        
        # Start the container
        start_result = subprocess.run(
            ["docker", "start", container_name],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if start_result.returncode != 0:
            return False, f"Failed to start container: {start_result.stderr}"
        
        # Wait for PostgreSQL to be ready
        print("⏳ Waiting for PostgreSQL to be ready...")
        time.sleep(5)
        
        return True, f"✓ Container {container_name} restarted successfully"
        
    except subprocess.TimeoutExpired:
        return False, "Timeout restarting container"
    except Exception as e:
        return False, str(e)


def update_postgres_password(container_name: str = "Autotask") -> Tuple[bool, str]:
    """
    Update PostgreSQL password in the running container to match .env file
    This requires connecting with the old password first, so it may not always work
    """
    import psycopg2
    
    if not Config.DB_PASSWORD:
        return False, "DB_PASSWORD not set in .env file"
    
    try:
        # Try to connect with the new password first (maybe it already matches)
        db_config = Config.get_db_config()
        try:
            conn = psycopg2.connect(**db_config)
            conn.close()
            return True, "Password already matches - no update needed"
        except psycopg2.OperationalError:
            # Password doesn't match, we need to update it
            pass
        
        # We can't update the password without knowing the old one
        # So we'll use docker exec to update it directly in PostgreSQL
        print("🔐 Attempting to update PostgreSQL password...")
        
        # Use ALTER USER command via docker exec
        update_cmd = f"ALTER USER {Config.DB_USER} WITH PASSWORD '{Config.DB_PASSWORD}';"
        
        result = subprocess.run(
            [
                "docker", "exec", "-i", container_name,
                "psql", "-U", "postgres", "-d", "postgres",
                "-c", update_cmd
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            return True, "✓ PostgreSQL password updated successfully"
        else:
            # If that didn't work, try with the admin user
            result2 = subprocess.run(
                [
                    "docker", "exec", "-i", container_name,
                    "psql", "-U", Config.DB_USER, "-d", "postgres",
                    "-c", update_cmd
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result2.returncode == 0:
                return True, "✓ PostgreSQL password updated successfully"
            else:
                return False, (
                    f"Could not update password automatically. "
                    f"Error: {result2.stderr}\n"
                    f"You may need to manually update the password or recreate the container."
                )
                
    except Exception as e:
        return False, f"Error updating password: {str(e)}"


def restart_and_fix_database(container_name: str = "Autotask") -> Tuple[bool, str]:
    """
    Restart the database and attempt to fix password if needed
    Returns (success, message)
    """
    # First, restart the container
    success, message = restart_database_container(container_name)
    if not success:
        return False, message
    
    # Wait a bit more for PostgreSQL to fully start
    time.sleep(3)
    
    # Check if password matches
    import psycopg2
    db_config = Config.get_db_config()
    
    try:
        conn = psycopg2.connect(**db_config)
        conn.close()
        return True, f"{message}\n✓ Database credentials are valid"
    except psycopg2.OperationalError as e:
        if "password authentication failed" in str(e).lower():
            # Try to update the password
            print("⚠️  Password mismatch detected. Attempting to update...")
            update_success, update_message = update_postgres_password(container_name)
            if update_success:
                return True, f"{message}\n{update_message}"
            else:
                return False, (
                    f"{message}\n"
                    f"❌ Password mismatch and could not auto-update.\n"
                    f"{update_message}\n\n"
                    f"To fix manually:\n"
                    f"1. Connect to the container: docker exec -it {container_name} psql -U postgres\n"
                    f"2. Run: ALTER USER {Config.DB_USER} WITH PASSWORD '{Config.DB_PASSWORD}';\n"
                    f"3. Or update your .env file to match the container's current password"
                )
        else:
            return False, f"{message}\n❌ Database connection error: {str(e)}"
    except Exception as e:
        return False, f"{message}\n❌ Error: {str(e)}"

