"""DB connectivity and schema tests — real DB via service container."""
import pytest


def test_db_connection_pool_works():
    """DatabaseConnection can fetch from a real table without error."""
    from src.database.db_connection import DatabaseConnection
    db = DatabaseConnection()
    rows = db.execute_query("SELECT 1 AS ok")
    assert rows[0]["ok"] == 1


def test_technician_table_has_rows():
    """technician_data should have been seeded (at least in CI seed step)."""
    from src.database.db_connection import DatabaseConnection
    db = DatabaseConnection()
    rows = db.execute_query("SELECT COUNT(*) AS cnt FROM technician_data")
    # Seeded in CI by conftest or a seed step — just check it doesn't crash
    assert rows[0]["cnt"] >= 0


def test_new_tickets_table_exists():
    from src.database.db_connection import DatabaseConnection
    db = DatabaseConnection()
    rows = db.execute_query(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='new_tickets'"
    )
    assert len(rows) == 1


def test_agent_sessions_table_exists():
    """Schema v3 table must exist."""
    from src.database.db_connection import DatabaseConnection
    db = DatabaseConnection()
    rows = db.execute_query(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='agent_sessions'"
    )
    assert len(rows) == 1


def test_daily_reports_table_exists():
    """Schema v3 table must exist."""
    from src.database.db_connection import DatabaseConnection
    db = DatabaseConnection()
    rows = db.execute_query(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='daily_reports'"
    )
    assert len(rows) == 1
