# Utility Scripts

This directory contains utility scripts for database management and data import.

## Available Scripts

### `init_database.py`
Initializes the database by creating all required tables.

```bash
python scripts/init_database.py
```

### `import_closed_tickets.py`
Imports all tickets from `ticket_data_updated.csv` into the `closed_tickets` table.

```bash
python scripts/import_closed_tickets.py
```

### `import_resolved_tickets.py`
Legacy script for importing tickets into resolved_tickets table (not used anymore).

### `add_user_id_column.py`
One-time migration script to add user_id column to new_tickets table (already applied).

## Notes

- All scripts use environment variables from `.env` file
- Make sure the database container is running before executing scripts
- Scripts can be run multiple times safely (use `ON CONFLICT` for duplicates)

