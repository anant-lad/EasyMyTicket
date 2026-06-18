"""
Idempotent startup migrations.
Each statement uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS so it's safe to re-run.
Called once at FastAPI startup — no separate Job needed.
"""
import logging
log = logging.getLogger(__name__)

_MIGRATIONS = [
    # E1: device tracking on tickets
    "ALTER TABLE new_tickets ADD COLUMN IF NOT EXISTS device_id TEXT",
    "CREATE INDEX IF NOT EXISTS idx_tickets_device ON new_tickets(device_id) WHERE device_id IS NOT NULL",

    # E5: feedback loop
    (
        "CREATE TABLE IF NOT EXISTS ticket_feedback ("
        "id BIGSERIAL PRIMARY KEY, "
        "ticket_number TEXT NOT NULL REFERENCES new_tickets(ticketnumber), "
        "tech_id TEXT, "
        "rating SMALLINT CHECK (rating BETWEEN 1 AND 5), "
        "classification_correct BOOLEAN, "
        "resolution_helpful BOOLEAN, "
        "actual_issue_type TEXT, "
        "notes TEXT, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
    ),
    "CREATE INDEX IF NOT EXISTS idx_feedback_ticket ON ticket_feedback(ticket_number)",

    # E4: chat tables
    (
        "CREATE TABLE IF NOT EXISTS chat_sessions ("
        "session_id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text, "
        "user_id TEXT NOT NULL, "
        "ticket_number TEXT, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
        "last_message TIMESTAMPTZ)"
    ),
    (
        "CREATE TABLE IF NOT EXISTS chat_messages ("
        "id BIGSERIAL PRIMARY KEY, "
        "session_id TEXT NOT NULL REFERENCES chat_sessions(session_id), "
        "role TEXT NOT NULL CHECK (role IN ('user','assistant','system')), "
        "content TEXT NOT NULL, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
    ),
    "CREATE INDEX IF NOT EXISTS idx_chat_msg_session ON chat_messages(session_id, created_at)",

    # E3: approval state column on agent_sessions
    "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS approval_command TEXT",
    "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS approval_reasoning TEXT",
]


def run_migrations():
    """Apply all pending migrations. Safe to call on every startup."""
    try:
        from src.database.db_connection import DatabaseConnection
        db = DatabaseConnection()
        for stmt in _MIGRATIONS:
            try:
                db.execute_query(stmt, fetch=False)
            except Exception as e:
                log.warning("Migration skipped (%s): %s", stmt[:60], e)
        log.info("Startup migrations complete (%d statements)", len(_MIGRATIONS))
    except Exception as e:
        log.error("Startup migrations failed: %s", e)
