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
    
    docker run --name Autotask \
      -e POSTGRES_USER=admin \
      -e POSTGRES_PASSWORD="$DB_PASSWORD" \
      -e POSTGRES_DB=tickets_db \
      -p 5433:5432 \
      -v postgres-new-data:/var/lib/postgresql \
      -d postgres:18
fi

echo "Waiting for PostgreSQL to be ready..."
sleep 5

if docker exec Autotask pg_isready -U admin > /dev/null 2>&1; then
    echo "✓ PostgreSQL is ready!"
    echo "Database connection details:"
    echo "  Host: localhost"
    echo "  Port: 5433"
    echo "  Database: tickets_db"
    echo "  User: admin"
    echo "  Password: [Set in .env file as DB_PASSWORD]"
else
    echo "⚠ PostgreSQL is starting up. Please wait a few more seconds."
    echo "Check status with: docker logs Autotask"
fi