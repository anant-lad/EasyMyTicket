# Switch to Local Docker PostgreSQL Plan

This document outlines the steps to switch your application from using a remote database to a local PostgreSQL instance running in Docker on your machine.

## Prerequisites
-   **Docker Desktop** (or Docker Engine) must be installed and running on your machine.
-   **Terminal Access** to run shell scripts.

## Step 1: Update Configuration
We need to point the backend to look for the database on `localhost` instead of the remote IP.

### `backend/.env`
Change the `DB_HOST` variable:
```diff
- DB_HOST=10.10.1.10
+ DB_HOST=localhost
```
*Ensure `DB_USER` (defaults to 'admin') and `DB_PASSWORD` matches what `start_database.sh` uses (it uses the `DB_PASSWORD` from your .env).*

## Step 2: Start Local Database
The project includes a helper script `start_database.sh` that sets up the local container for you.

1.  Open your terminal.
2.  Navigate to the backend directory:
    ```bash
    cd /Users/aditya/Documents/EMT/EasyMyTicket/backend
    ```
3.  Make the script executable (if it isn't already):
    ```bash
    chmod +x start_database.sh
    ```
4.  Run the script:
    ```bash
    ./start_database.sh
    ```

**What this script does:**
-   Checks if a container named `Autotask` exists.
-   If not, it creates a new PostgreSQL 18 container.
-   Maps local port **5433** to container port **5432** (matching your `.env` `DB_PORT`).
-   Creates a persistent volume `postgres-new-data` so your data survives restarts.
-   Creates the `tickets_db` database.

## Step 3: Restart Backend
For the configuration changes to take effect, you must restart your backend server.

1.  Stop the currently running uvicorn process (Ctrl+C).
2.  Start it again:
    ```bash
    uvicorn main:app --reload
    ```
3.  The startup logs should show:
    ```
    checking database status...
    ✓ Using local database (or similar success message)
    ```

## Step 4: Verification
1.  **Check Container Status**:
    ```bash
    docker ps
    ```
    You should see `Autotask` running on port 0.0.0.0:5433->5432/tcp.

2.  **Check Application Health**:
    -   Go to `http://localhost:5000/api/health` (or your configured port).
    -   It should return `{"status": "healthy", "database": "connected"}`.

## Note on Data
**This process creates a FRESH, EMPTY database.**
Your existing data on the remote machine (`10.10.1.10`) will **NOT** be automatically copied.
If you need that data, you must manually export it from the remote DB and import it into your local DB:
```bash
# Example Export (run on machine with access to remote DB)
pg_dump -h 10.10.1.10 -p 5433 -U admin tickets_db > backup.sql

# Example Import (run locally)
docker exec -i Autotask psql -U admin -d tickets_db < backup.sql
```
