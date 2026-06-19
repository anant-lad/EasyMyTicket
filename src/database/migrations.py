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

    # Fix: chat_messages/chat_sessions may have been created by an older script without these columns
    "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS user_id TEXT",
    "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS ticket_number TEXT",
    "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS last_message TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS idx_chat_msg_session ON chat_messages(session_id, created_at)",

    # E7: auth — is_admin flag on technicians
    "ALTER TABLE technician_data ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE",

    # E6: persistent device registry
    (
        "CREATE TABLE IF NOT EXISTS devices ("
        "device_id TEXT PRIMARY KEY, "
        "hostname TEXT, "
        "os_type TEXT, "
        "os_version TEXT, "
        "ip_address TEXT, "
        "first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
        "last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW())"
    ),
    "CREATE INDEX IF NOT EXISTS idx_devices_last_seen ON devices(last_seen)",
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
        _seed_auth_credentials(db)
    except Exception as e:
        log.error("Startup migrations failed: %s", e)


def _seed_auth_credentials(db):
    """
    One-time seed: set real emails + bcrypt passwords for technicians and create initial users.
    Only runs if tech_password IS NULL (idempotent — never overwrites existing passwords).
    """
    try:
        from src.auth.password import hash_password

        tech_seeds = [
            ("TECH001", "anantlad66@gmail.com",   "EasyMT@Tech66",    False),
            ("TECH002", "anantlad0628@gmail.com",  "EasyMT@Admin2024", True),
            ("TECH003", "carol.davis@company.com", "EasyMT@Tech123",   False),
            ("TECH004", "david.kim@company.com",   "EasyMT@Tech123",   False),
            ("TECH005", "emma.wilson@company.com", "EasyMT@Tech123",   False),
            ("TECH006", "frank.lee@company.com",   "EasyMT@Tech123",   False),
            ("TECH007", "grace.patel@company.com", "EasyMT@Tech123",   False),
            ("TECH008", "henry.chen@company.com",  "EasyMT@Tech123",   False),
        ]
        for tech_id, email, pwd, is_admin in tech_seeds:
            rows = db.execute_query(
                "SELECT tech_password FROM technician_data WHERE tech_id=%s LIMIT 1", (tech_id,)
            )
            if rows and rows[0]["tech_password"] is None:
                db.execute_query(
                    "UPDATE technician_data SET tech_mail=%s, tech_password=%s, is_admin=%s WHERE tech_id=%s",
                    (email, hash_password(pwd), is_admin, tech_id), fetch=False,
                )
                log.info("Auth seed: set password for %s (%s)", tech_id, email)

        user_seeds = [
            ("USR001", "Anant SRTTC", "anant.221269@srttc.ai.in", "EasyMT@User221"),
            ("USR002", "Anant Lad",   "ladanant09@gmail.com",      "EasyMT@User09"),
        ]
        for user_id, name, email, pwd in user_seeds:
            existing = db.execute_query(
                "SELECT user_id FROM user_data WHERE user_id=%s LIMIT 1", (user_id,)
            )
            if not existing:
                db.execute_query(
                    "INSERT INTO user_data (user_id, user_name, user_mail, user_password, no_tickets_raised, available)"
                    " VALUES (%s,%s,%s,%s,0,TRUE)",
                    (user_id, name, email, hash_password(pwd)), fetch=False,
                )
                log.info("Auth seed: created user %s (%s)", user_id, email)
    except Exception as e:
        log.warning("Auth credential seed skipped: %s", e)
