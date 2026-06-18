-- ============================================================
-- EasyMyTicket — Schema v3 patch
-- Adds: daily_reports, agent_sessions, session_steps
-- Apply with: psql $DATABASE_URL -f scripts/db_schema_v3_patch.sql
-- ============================================================

-- ── Daily monitoring reports sent by desktop agents ───────────────────────────
CREATE TABLE IF NOT EXISTS daily_reports (
    id              BIGSERIAL PRIMARY KEY,
    device_id       TEXT        NOT NULL,
    user_id         TEXT        NOT NULL,
    os              TEXT,
    hostname        TEXT,
    scan_time       TIMESTAMPTZ NOT NULL,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    report          JSONB       NOT NULL,     -- full raw scan payload
    analysis        TEXT,                     -- LLM analysis summary
    tickets_created TEXT[]      DEFAULT '{}', -- ticket numbers auto-created
    digest_sent     BOOLEAN     NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_daily_reports_device   ON daily_reports(device_id);
CREATE INDEX IF NOT EXISTS idx_daily_reports_received ON daily_reports(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_daily_reports_user     ON daily_reports(user_id);

-- ── Agentic remediation sessions (Part 2) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id      TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    ticket_number   TEXT        NOT NULL REFERENCES new_tickets(ticketnumber),
    device_id       TEXT        NOT NULL,
    user_id         TEXT,
    status          TEXT        NOT NULL DEFAULT 'open',
    -- open | running | resolved | failed | escalated | awaiting_user
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    resolution      TEXT,           -- final plain-English explanation to user
    escalation_reason TEXT,         -- why it was escalated to human
    step_count      INT         NOT NULL DEFAULT 0,
    max_steps       INT         NOT NULL DEFAULT 20
);
CREATE INDEX IF NOT EXISTS idx_sessions_ticket ON agent_sessions(ticket_number);
CREATE INDEX IF NOT EXISTS idx_sessions_device ON agent_sessions(device_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON agent_sessions(status);

-- ── Individual steps within an agentic session ───────────────────────────────
CREATE TABLE IF NOT EXISTS session_steps (
    id              BIGSERIAL   PRIMARY KEY,
    session_id      TEXT        NOT NULL REFERENCES agent_sessions(session_id),
    step_number     INT         NOT NULL,
    step_type       TEXT        NOT NULL, -- 'reasoning' | 'command' | 'result' | 'user_message'
    command         TEXT,
    args            JSONB,
    output          TEXT,
    stderr          TEXT,
    exit_code       INT,
    llm_reasoning   TEXT,        -- LLM's thought before this step
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_steps_session ON session_steps(session_id, step_number);

-- ── device_id on new_tickets (for Pending-Agent ticket pickup) ───────────────
ALTER TABLE new_tickets ADD COLUMN IF NOT EXISTS device_id TEXT;
CREATE INDEX IF NOT EXISTS idx_tickets_device ON new_tickets(device_id) WHERE device_id IS NOT NULL;

-- ── ticket_feedback (E5 feedback loop) ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS ticket_feedback (
    id              BIGSERIAL   PRIMARY KEY,
    ticket_number   TEXT        NOT NULL REFERENCES new_tickets(ticketnumber),
    tech_id         TEXT,
    rating          SMALLINT    CHECK (rating BETWEEN 1 AND 5),
    classification_correct BOOLEAN,
    resolution_helpful     BOOLEAN,
    actual_issue_type TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_feedback_ticket ON ticket_feedback(ticket_number);

-- ── chat_sessions and chat_messages (E4) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id   TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id      TEXT        NOT NULL,
    ticket_number TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_message TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id           BIGSERIAL   PRIMARY KEY,
    session_id   TEXT        NOT NULL REFERENCES chat_sessions(session_id),
    role         TEXT        NOT NULL CHECK (role IN ('user','assistant','system')),
    content      TEXT        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chat_msg_session ON chat_messages(session_id, created_at);

-- ── Extend status constraint to include agent-managed statuses ────────────────
ALTER TABLE new_tickets
  DROP CONSTRAINT IF EXISTS new_tickets_status_check,
  ADD CONSTRAINT new_tickets_status_check CHECK (status IN (
    'Open','In Progress','Pending','Pending Agent','Resolved','Closed',
    'On Hold','Escalated','Cancelled','Awaiting User','Reopened'
  ));
