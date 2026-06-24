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

    # E8: organizations
    (
        "CREATE TABLE IF NOT EXISTS organizations ("
        "org_id TEXT PRIMARY KEY, "
        "org_name TEXT NOT NULL, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
    ),
    "ALTER TABLE user_data ADD COLUMN IF NOT EXISTS org_id TEXT",
    "ALTER TABLE technician_data ADD COLUMN IF NOT EXISTS org_id TEXT",
    "ALTER TABLE technician_data ADD COLUMN IF NOT EXISTS tech_role TEXT NOT NULL DEFAULT 'tech'",

    # E9: ticket comments (user-tech dialogue per ticket)
    (
        "CREATE TABLE IF NOT EXISTS ticket_comments ("
        "id BIGSERIAL PRIMARY KEY, "
        "ticket_number TEXT NOT NULL REFERENCES new_tickets(ticketnumber), "
        "author_id TEXT NOT NULL, "
        "author_type TEXT NOT NULL CHECK (author_type IN ('user','tech','system')), "
        "author_name TEXT, "
        "content TEXT NOT NULL, "
        "is_internal BOOLEAN NOT NULL DEFAULT FALSE, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
    ),
    "CREATE INDEX IF NOT EXISTS idx_comments_ticket ON ticket_comments(ticket_number, created_at)",

    # E10: ticket lifecycle fields
    "ALTER TABLE new_tickets ADD COLUMN IF NOT EXISTS parent_ticket TEXT",
    "ALTER TABLE new_tickets ADD COLUMN IF NOT EXISTS reraise_reason TEXT",
    "ALTER TABLE new_tickets ADD COLUMN IF NOT EXISTS feedback_required BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE new_tickets ADD COLUMN IF NOT EXISTS feedback_submitted BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE new_tickets ADD COLUMN IF NOT EXISTS resolved_by_agent BOOLEAN NOT NULL DEFAULT FALSE",

    # E11: direct tech-user chat sessions
    "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS chat_type TEXT DEFAULT 'bot'",
    "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS tech_id TEXT",

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

    # E7: per-user agent API key
    "ALTER TABLE user_data ADD COLUMN IF NOT EXISTS agent_api_key TEXT UNIQUE",
    "ALTER TABLE technician_data ADD COLUMN IF NOT EXISTS agent_api_key TEXT UNIQUE",

    # E12: ticket file attachments (stored in S3 exports bucket)
    (
        "CREATE TABLE IF NOT EXISTS ticket_attachments ("
        "id BIGSERIAL PRIMARY KEY, "
        "ticket_number TEXT NOT NULL REFERENCES new_tickets(ticketnumber), "
        "comment_id BIGINT REFERENCES ticket_comments(id) ON DELETE SET NULL, "
        "uploader_id TEXT NOT NULL, "
        "uploader_type TEXT NOT NULL CHECK (uploader_type IN ('user','tech','agent')), "
        "filename TEXT NOT NULL, "
        "s3_key TEXT NOT NULL UNIQUE, "
        "file_size INTEGER, "
        "mime_type TEXT, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
    ),
    "CREATE INDEX IF NOT EXISTS idx_attachments_ticket ON ticket_attachments(ticket_number)",

    # E13: agent session report (markdown doc uploaded to S3 on session completion)
    "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS report_s3_key TEXT",
    "ALTER TABLE session_steps ADD COLUMN IF NOT EXISTS step_type_detail TEXT",

    # E14: oversight technician assigned to agent sessions for human-in-the-loop monitoring
    "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS oversight_tech_id TEXT",
    "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS oversight_tech_name TEXT",
    "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS oversight_notified_at TIMESTAMPTZ",

    # E15: technician attendance / availability log
    (
        "CREATE TABLE IF NOT EXISTS technician_attendance ("
        "id BIGSERIAL PRIMARY KEY, "
        "tech_id TEXT NOT NULL REFERENCES technician_data(tech_id), "
        "date DATE NOT NULL DEFAULT CURRENT_DATE, "
        "punch_in TIMESTAMPTZ, "
        "punch_out TIMESTAMPTZ, "
        "status TEXT NOT NULL DEFAULT 'available' CHECK (status IN ("
        "  'available','wfh','on_leave','half_day','offline','out_of_office','away','busy')), "
        "notes TEXT, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
    ),
    "CREATE INDEX IF NOT EXISTS idx_attendance_tech_date ON technician_attendance(tech_id, date DESC)",

    # E16: Linux troubleshooting knowledge base (Agentic RAG)
    (
        "CREATE TABLE IF NOT EXISTS linux_troubleshooting_kb ("
        "id         SERIAL PRIMARY KEY, "
        "title      TEXT NOT NULL, "
        "category   TEXT NOT NULL, "
        "os_type    TEXT NOT NULL DEFAULT 'Linux', "
        "symptoms   TEXT, "
        "diagnostics TEXT, "
        "root_causes TEXT, "
        "fix_steps  TEXT, "
        "verification TEXT, "
        "source     TEXT NOT NULL DEFAULT 'manual', "
        "embedding  REAL[], "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_kb_fts ON linux_troubleshooting_kb "
        "USING GIN(to_tsvector('english', "
        "title || ' ' || COALESCE(symptoms,'') || ' ' || COALESCE(fix_steps,'')))"
    ),
    "CREATE INDEX IF NOT EXISTS idx_kb_category ON linux_troubleshooting_kb(category)",

    # E17: cross-pod tool call relay (PostgreSQL message queue for 2-replica WebSocket dispatch)
    (
        "CREATE TABLE IF NOT EXISTS pending_tool_calls ("
        "id          SERIAL PRIMARY KEY, "
        "device_id   TEXT NOT NULL, "
        "session_id  TEXT NOT NULL, "
        "tool_name   TEXT NOT NULL, "
        "tool_input  JSONB NOT NULL DEFAULT '{}', "
        "created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW())"
    ),
    (
        "CREATE TABLE IF NOT EXISTS tool_call_results ("
        "id              SERIAL PRIMARY KEY, "
        "pending_call_id INT NOT NULL REFERENCES pending_tool_calls(id), "
        "output          TEXT, "
        "error           TEXT, "
        "completed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW())"
    ),
    "CREATE INDEX IF NOT EXISTS idx_ptc_device ON pending_tool_calls(device_id)",
    "CREATE INDEX IF NOT EXISTS idx_tcr_call ON tool_call_results(pending_call_id)",
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

        # Backfill agent_api_key for existing users/techs
        db.execute_query("UPDATE user_data SET agent_api_key = 'emt_' || replace(gen_random_uuid()::text, '-', '') WHERE agent_api_key IS NULL", ())
        db.execute_query("UPDATE technician_data SET agent_api_key = 'emt_' || replace(gen_random_uuid()::text, '-', '') WHERE agent_api_key IS NULL", ())

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

        # Ensure Blackshift Technologies org exists
        db.execute_query(
            "INSERT INTO organizations (org_id, org_name) VALUES ('ORG001','Blackshift Technologies LLP')"
            " ON CONFLICT (org_id) DO NOTHING",
            fetch=False,
        )

        # tech_id, email, pwd, is_admin, tech_role
        tech_seeds = [
            ("TECH001", "anantlad66@gmail.com",      "EasyMT@Tech66",    False, "tech"),
            ("TECH002", "anantlad0628@gmail.com",     "EasyMT@Admin2024", True,  "tech"),
            ("TECH003", "carol.davis@company.com",    "EasyMT@Tech123",   False, "tech"),
            ("TECH004", "david.kim@company.com",      "EasyMT@Tech123",   False, "tech"),
            ("TECH005", "emma.wilson@company.com",    "EasyMT@Tech123",   False, "tech"),
            ("TECH006", "frank.lee@company.com",      "EasyMT@Tech123",   False, "tech"),
            ("TECH007", "grace.patel@company.com",    "EasyMT@Tech123",   False, "tech"),
            ("TECH008", "henry.chen@company.com",     "EasyMT@Tech123",   False, "tech"),
        ]
        for tech_id, email, pwd, is_admin, tech_role in tech_seeds:
            rows = db.execute_query(
                "SELECT tech_password FROM technician_data WHERE tech_id=%s LIMIT 1", (tech_id,)
            )
            if rows and rows[0]["tech_password"] is None:
                db.execute_query(
                    "UPDATE technician_data SET tech_mail=%s, tech_password=%s, is_admin=%s, tech_role=%s, org_id='ORG001' WHERE tech_id=%s",
                    (email, hash_password(pwd), is_admin, tech_role, tech_id), fetch=False,
                )
                log.info("Auth seed: set password for %s (%s)", tech_id, email)
            else:
                # Ensure org is linked even if password was already set
                db.execute_query(
                    "UPDATE technician_data SET org_id='ORG001' WHERE tech_id=%s AND org_id IS NULL",
                    (tech_id,), fetch=False,
                )

        # Seed tech lead: ladanant023@gmail.com
        tl_exists = db.execute_query(
            "SELECT tech_id FROM technician_data WHERE tech_id='TECH009' LIMIT 1"
        )
        if not tl_exists:
            db.execute_query(
                "INSERT INTO technician_data (tech_id, tech_name, tech_mail, tech_password, tech_role, is_admin, org_id,"
                " no_tickets_assigned, solved_tickets, current_workload)"
                " VALUES ('TECH009','Anant Lad (Lead)','ladanant023@gmail.com',%s,'tech_lead',FALSE,'ORG001',0,0,0)"
                " ON CONFLICT (tech_id) DO NOTHING",
                (hash_password("EasyMT@Lead2024"),), fetch=False,
            )
            log.info("Auth seed: created tech lead TECH009 ladanant023@gmail.com")

        user_seeds = [
            ("USR001", "Anant Lad",   "ladanant418@gmail.com",    "EasyMT@User221"),
            ("USR002", "Anant Lad",   "ladanant09@gmail.com",      "EasyMT@User09"),
        ]
        for user_id, name, email, pwd in user_seeds:
            existing = db.execute_query(
                "SELECT user_id FROM user_data WHERE user_id=%s LIMIT 1", (user_id,)
            )
            if not existing:
                db.execute_query(
                    "INSERT INTO user_data (user_id, user_name, user_mail, user_password, no_tickets_raised, available, org_id)"
                    " VALUES (%s,%s,%s,%s,0,TRUE,'ORG001')",
                    (user_id, name, email, hash_password(pwd)), fetch=False,
                )
                log.info("Auth seed: created user %s (%s)", user_id, email)
            else:
                db.execute_query(
                    "UPDATE user_data SET user_mail=%s, user_name=%s, org_id='ORG001' WHERE user_id=%s",
                    (email, name, user_id), fetch=False,
                )
    except Exception as e:
        log.warning("Auth credential seed skipped: %s", e)
