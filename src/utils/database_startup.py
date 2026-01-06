"""
Database startup utility
Automatically starts the PostgreSQL database container if not running
"""
import subprocess
import time
import os
from typing import Tuple, Optional
from src.config import Config


def check_docker_available() -> bool:
    """Check if Docker is available"""
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def check_container_exists(container_name: str = "Autotask") -> bool:
    """Check if the Docker container exists"""
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return container_name in result.stdout
    except (subprocess.TimeoutExpired, Exception):
        return False


def check_container_running(container_name: str = "Autotask") -> bool:
    """Check if the Docker container is running"""
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return container_name in result.stdout
    except (subprocess.TimeoutExpired, Exception):
        return False


def start_container(container_name: str = "Autotask") -> Tuple[bool, str]:
    """Start an existing Docker container"""
    try:
        print(f"🔄 Starting container {container_name}...")
        result = subprocess.run(
            ["docker", "start", container_name],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            # Wait a bit for PostgreSQL to be ready
            time.sleep(3)
            return True, "Container started successfully"
        else:
            return False, result.stderr or "Unknown error starting container"
    except subprocess.TimeoutExpired:
        return False, "Timeout starting container"
    except Exception as e:
        return False, str(e)


def create_container(container_name: str = "Autotask") -> Tuple[bool, str]:
    """Create and start a new Docker container"""
    try:
        # Use Config class to get database password (consistent with connection code)
        db_password = Config.DB_PASSWORD
        db_user = Config.DB_USER
        db_name = Config.DB_NAME
        db_port = Config.DB_PORT
        
        if not db_password:
            return False, "DB_PASSWORD not found in .env file. Please set it before creating the container."
        
        print(f"🔄 Creating container {container_name}...")
        print(f"   Using database user: {db_user}")
        print(f"   Using database name: {db_name}")
        print(f"   Using port: {db_port}")
        
        # Get absolute path to postgres config directory
        script_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        postgres_conf_dir = os.path.join(script_dir, "postgres")
        postgresql_conf_path = os.path.join(postgres_conf_dir, "postgresql.conf")
        pg_hba_conf_path = os.path.join(postgres_conf_dir, "pg_hba.conf")
        
        # Build docker run command
        docker_cmd = [
            "docker", "run", "--name", container_name,
            "-e", f"POSTGRES_USER={db_user}",
            "-e", f"POSTGRES_PASSWORD={db_password}",
            "-e", f"POSTGRES_DB={db_name}",
            "-p", f"{db_port}:5432",
            "-v", "postgres-new-data:/var/lib/postgresql/data",
        ]
        
        # Add config file mounts if they exist
        if os.path.exists(postgresql_conf_path) and os.path.exists(pg_hba_conf_path):
            docker_cmd.extend([
                "-v", f"{postgresql_conf_path}:/etc/postgresql/postgresql.conf:ro",
                "-v", f"{pg_hba_conf_path}:/tmp/pg_hba.conf:ro",
            ])
            print(f"   ✓ Using custom PostgreSQL configuration for public access")
        else:
            print(f"   ⚠ PostgreSQL config files not found - container will only accept localhost connections")
            print(f"   Config files expected at: {postgres_conf_dir}")
        
        docker_cmd.extend([
            "-d", "postgres:18"
        ])
        
        # Add config file parameter if custom config exists
        if os.path.exists(postgresql_conf_path):
            docker_cmd.append("-c")
            docker_cmd.append("config_file=/etc/postgresql/postgresql.conf")
        
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            # Wait for PostgreSQL to initialize
            print("⏳ Waiting for PostgreSQL to initialize...")
            time.sleep(3)
            
            # Copy pg_hba.conf to the data directory if config files exist
            if os.path.exists(pg_hba_conf_path):
                print("   Copying pg_hba.conf to container...")
                copy_result = subprocess.run(
                    ["docker", "cp", pg_hba_conf_path, f"{container_name}:/var/lib/postgresql/data/pg_hba.conf"],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if copy_result.returncode == 0:
                    # Restart PostgreSQL to apply pg_hba.conf changes
                    print("   Restarting PostgreSQL to apply configuration...")
                    subprocess.run(
                        ["docker", "exec", container_name, "pg_ctl", "restart", "-D", "/var/lib/postgresql/data", "-m", "fast"],
                        capture_output=True,
                        timeout=30
                    )
                    time.sleep(2)
            
            # Wait for PostgreSQL to be ready
            print("⏳ Waiting for PostgreSQL to be ready...")
            time.sleep(5)
            return True, "Container created and started successfully"
        else:
            return False, result.stderr or "Unknown error creating container"
    except subprocess.TimeoutExpired:
        return False, "Timeout creating container"
    except Exception as e:
        return False, str(e)


def verify_database_credentials() -> Tuple[bool, str]:
    """
    Verify that the database credentials in .env match the container
    Returns (success, message)
    """
    import psycopg2
    
    if not Config.DB_PASSWORD:
        return False, "DB_PASSWORD is not set in .env file"
    
    db_config = Config.get_db_config()
    
    try:
        conn = psycopg2.connect(**db_config)
        conn.close()
        return True, "Database credentials are valid"
    except psycopg2.OperationalError as e:
        error_msg = str(e)
        if "password authentication failed" in error_msg.lower():
            return False, (
                "Password authentication failed. The DB_PASSWORD in your .env file "
                "does not match the password used when the container was created.\n"
                "Options:\n"
                "1. Update your .env file to match the container's password, OR\n"
                "2. Recreate the container (this will delete existing data):\n"
                "   docker stop Autotask && docker rm Autotask\n"
                "   Then restart the backend to auto-create with the correct password."
            )
        return False, f"Database connection error: {error_msg}"
    except Exception as e:
        return False, f"Error verifying credentials: {str(e)}"


def ensure_database_running(container_name: str = "Autotask") -> Tuple[bool, str]:
    """
    Ensure the database container is running
    Returns (success, message)
    """
    # Check if Docker is available
    if not check_docker_available():
        return False, "Docker is not available. Please install Docker and ensure it's running."
    
    # Check if container exists
    if not check_container_exists(container_name):
        # Container doesn't exist, create it
        print(f"📦 Container {container_name} does not exist. Creating it...")
        success, message = create_container(container_name)
        if success:
            return True, f"✓ {message}"
        else:
            return False, f"Failed to create container: {message}"
    
    # Container exists, check if it's running
    if not check_container_running(container_name):
        # Container exists but is not running, start it
        success, message = start_container(container_name)
        if success:
            return True, f"✓ {message}"
        else:
            return False, f"Failed to start container: {message}"
    
    # Container is already running - verify credentials match
    print("🔐 Verifying database credentials...")
    cred_success, cred_message = verify_database_credentials()
    if not cred_success:
        return False, cred_message
    
    # Container is already running and credentials are valid
    return True, f"✓ Container {container_name} is already running"


def wait_for_database_ready(host: str = None, port: int = None, max_retries: int = 10) -> bool:
    """
    Wait for the database to be ready by attempting a connection
    Returns True if database is ready, False otherwise
    """
    import psycopg2
    
    # Use Config to get database settings (consistent with connection code)
    db_config = Config.get_db_config()
    
    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(**db_config)
            conn.close()
            return True
        except psycopg2.OperationalError as e:
            # If it's a password/auth error, don't retry - it's a configuration issue
            if "password authentication failed" in str(e).lower() or "authentication failed" in str(e).lower():
                print(f"⚠ Authentication error: {e}")
                print(f"⚠ Please check that DB_PASSWORD in .env matches the container's POSTGRES_PASSWORD")
                return False
            # For other errors (connection refused, etc.), retry
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                return False
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                return False
    
    return False

