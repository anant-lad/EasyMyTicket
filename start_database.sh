#!/bin/bash
# Script to start PostgreSQL database container

# Try to use system Docker socket if Docker Desktop socket is not available
if [ ! -S /home/green/.docker/desktop/docker.sock ]; then
    if [ -S /var/run/docker.sock ]; then
        echo "Using system Docker socket..."
        export DOCKER_HOST=unix:///var/run/docker.sock
    else
        echo "Error: No Docker socket found!"
        echo "Please ensure Docker is running."
        echo "If using Docker Desktop, please start it."
        echo "If using system Docker, ensure you have permissions to access /var/run/docker.sock"
        exit 1
    fi
fi

echo "Checking if Autotask container exists..."
if docker ps -a 2>/dev/null | grep -q Autotask; then
    echo "Container exists. Checking status..."
    if docker ps 2>/dev/null | grep -q Autotask; then
        echo "✓ Container is already running!"
    else
        echo "Starting container..."
        docker start Autotask
    fi
else
    echo "Container does not exist. Creating it..."
    
    # Load database password from environment or .env file
    if [ -f .env ]; then
        export $(grep -v '^#' .env | xargs)
    fi
    
    if [ -z "$DB_PASSWORD" ]; then
        echo "❌ ERROR: DB_PASSWORD is not set!"
        echo "Please create a .env file in the project root with:"
        echo "  DB_PASSWORD=your_password_here"
        exit 1
    fi
    
    # Get the absolute path to the postgres config directory
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    POSTGRES_CONF_DIR="$SCRIPT_DIR/postgres"
    
    # Check if config files exist
    if [ ! -f "$POSTGRES_CONF_DIR/postgresql.conf" ] || [ ! -f "$POSTGRES_CONF_DIR/pg_hba.conf" ]; then
        echo "⚠ WARNING: PostgreSQL config files not found in $POSTGRES_CONF_DIR"
        echo "   Creating container without custom config (will only accept localhost connections)"
    fi
    
    docker run --name Autotask \
      -e POSTGRES_USER=admin \
      -e POSTGRES_PASSWORD="$DB_PASSWORD" \
      -e POSTGRES_DB=tickets_db \
      -p 5433:5432 \
      -v postgres-new-data:/var/lib/postgresql/data \
      -v "$POSTGRES_CONF_DIR/postgresql.conf:/etc/postgresql/postgresql.conf:ro" \
      -v "$POSTGRES_CONF_DIR/pg_hba.conf:/tmp/pg_hba.conf:ro" \
      -d postgres:18 \
      -c config_file=/etc/postgresql/postgresql.conf
    
    # Wait for PostgreSQL to initialize
    echo "Waiting for PostgreSQL to initialize..."
    sleep 3
    
    # Copy pg_hba.conf to the data directory if config files exist
    if [ -f "$POSTGRES_CONF_DIR/pg_hba.conf" ]; then
        echo "Copying pg_hba.conf to container..."
        docker cp "$POSTGRES_CONF_DIR/pg_hba.conf" Autotask:/var/lib/postgresql/data/pg_hba.conf
        # Restart PostgreSQL to apply pg_hba.conf changes
        docker exec Autotask pg_ctl restart -D /var/lib/postgresql/data -m fast || true
        sleep 2
    fi
fi

echo "Waiting for PostgreSQL to be ready..."
sleep 5

if docker exec Autotask pg_isready -U admin > /dev/null 2>&1; then
    echo "✓ PostgreSQL is ready!"
    echo ""
    echo "Database connection details:"
    echo "  Host: localhost (for local connections)"
    echo "  Port: 5433"
    echo "  Database: tickets_db"
    echo "  User: admin"
    echo "  Password: [Set in .env file as DB_PASSWORD]"
    echo ""
    echo "✓ Database is configured for public access (remote connections enabled)"
    echo "  See DATABASE_ACCESS.md for instructions on connecting remotely"
else
    echo "⚠ PostgreSQL is starting up. Please wait a few more seconds."
    echo "Check status with: docker logs Autotask"
fi