-- ============================================================
-- EasyMyTicket v2 Schema — for RDS PostgreSQL 16
-- Fixes vs v1:
--   - technician_data: added status VARCHAR, dropped available BOOL
--   - new_tickets: added assigned_tech_id, source, agent_task_id
--   - ticket_assignments: was in code but MISSING from v1 SQL
--   - historical_tickets: NEW — merged dataset (73K records)
--   - agent_tasks: NEW — desktop remediation agent tasks
--   - 12 performance indexes added
--   - CHECK constraints on enum-like fields
-- ============================================================

-- ── Extensions ───────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- trigram index for fuzzy title search

-- ── 1. new_tickets ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS new_tickets (
    id                      SERIAL PRIMARY KEY,
    companyid               VARCHAR(100),
    completeddate           TIMESTAMP,
    createdate              TIMESTAMP DEFAULT NOW(),
    description             TEXT,
    duedatetime             TIMESTAMP,
    estimatedhours          NUMERIC(10, 2),
    firstresponsedatetime   TIMESTAMP,
    issuetype               VARCHAR(100),
    lastactivitydate        TIMESTAMP,
    priority                VARCHAR(50),
    queueid                 VARCHAR(100),
    resolution              TEXT,
    resolutionplandatetime  TIMESTAMP,
    resolveddatetime        TIMESTAMP,
    status                  VARCHAR(50) DEFAULT 'Open' CHECK (status IN (
                              'Open','In Progress','Pending','Resolved','Closed',
                              'On Hold','Escalated','Cancelled','Awaiting User','Reopened'
                            )),
    subissuetype            VARCHAR(100),
    ticketcategory          VARCHAR(100),
    ticketnumber            VARCHAR(100) UNIQUE NOT NULL,
    tickettype              VARCHAR(100),
    title                   TEXT NOT NULL,
    user_id                 VARCHAR(100),
    assigned_tech_id        VARCHAR(100),
    source                  VARCHAR(50) DEFAULT 'portal' CHECK (source IN ('email','portal','agent','api')),
    agent_task_id           UUID
);

-- ── 2. resolved_tickets ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS resolved_tickets (
    id                      SERIAL PRIMARY KEY,
    companyid               VARCHAR(100),
    completeddate           TIMESTAMP,
    createdate              TIMESTAMP,
    description             TEXT,
    duedatetime             TIMESTAMP,
    estimatedhours          NUMERIC(10, 2),
    firstresponsedatetime   TIMESTAMP,
    issuetype               VARCHAR(100),
    lastactivitydate        TIMESTAMP,
    priority                VARCHAR(50),
    queueid                 VARCHAR(100),
    resolution              TEXT,
    resolutionplandatetime  TIMESTAMP,
    resolveddatetime        TIMESTAMP,
    status                  VARCHAR(50),
    subissuetype            VARCHAR(100),
    ticketcategory          VARCHAR(100),
    ticketnumber            VARCHAR(100) UNIQUE NOT NULL,
    tickettype              VARCHAR(100),
    title                   TEXT,
    assigned_tech_id        VARCHAR(100)
);

-- ── 3. historical_tickets (NEW) ───────────────────────────────────────────────
-- Merged from: cleaned_ticket_data_enhanced.xlsx (62,971) + ticket_data_updated.csv (10,000)
-- Used for: semantic similarity search, LLM context, fine-tuning dataset
CREATE TABLE IF NOT EXISTS historical_tickets (
    id                      SERIAL PRIMARY KEY,
    companyid               VARCHAR(100),
    companylocationid       VARCHAR(100),
    completedbyresourceid   VARCHAR(100),
    completeddate           TIMESTAMP,
    contactid               VARCHAR(100),
    createdate              TIMESTAMP,
    createdbycontactid      VARCHAR(100),
    description             TEXT,
    duedatetime             TIMESTAMP,
    external_id             VARCHAR(100),   -- original ID from source system
    issuetype               VARCHAR(100),
    priority                VARCHAR(50),
    queueid                 VARCHAR(100),
    resolution              TEXT,
    resolveddatetime        TIMESTAMP,
    resolvedduedatetime     TIMESTAMP,
    status                  VARCHAR(100),
    subissuetype            VARCHAR(100),
    ticketcategory          VARCHAR(100),
    ticketnumber            VARCHAR(100) UNIQUE NOT NULL,
    tickettype              VARCHAR(100),
    title                   TEXT,
    source_dataset          VARCHAR(50) DEFAULT 'enhanced'  -- 'enhanced' | 'legacy'
);

-- ── 4. closed_tickets (kept for semantic search compatibility) ────────────────
CREATE TABLE IF NOT EXISTS closed_tickets (
    id                      SERIAL PRIMARY KEY,
    companyid               VARCHAR(100),
    completeddate           TIMESTAMP,
    createdate              TIMESTAMP,
    description             TEXT,
    duedatetime             TIMESTAMP,
    estimatedhours          NUMERIC(10, 2),
    firstresponsedatetime   TIMESTAMP,
    issuetype               VARCHAR(100),
    lastactivitydate        TIMESTAMP,
    priority                VARCHAR(50),
    queueid                 VARCHAR(100),
    resolution              TEXT,
    resolutionplandatetime  TIMESTAMP,
    resolveddatetime        TIMESTAMP,
    status                  VARCHAR(50),
    subissuetype            VARCHAR(100),
    ticketcategory          VARCHAR(100),
    ticketnumber            VARCHAR(100) UNIQUE NOT NULL,
    tickettype              VARCHAR(100),
    title                   TEXT
);

-- ── 5. technician_data ────────────────────────────────────────────────────────
-- FIXED: replaced available BOOL with status VARCHAR
CREATE TABLE IF NOT EXISTS technician_data (
    tech_id             VARCHAR(100) PRIMARY KEY,
    tech_name           VARCHAR(255) NOT NULL,
    tech_mail           VARCHAR(255) UNIQUE NOT NULL,
    tech_password       VARCHAR(255),
    skills              TEXT,
    status              VARCHAR(50) DEFAULT 'available' CHECK (status IN (
                          'available','wfh','on_leave','half_day','offline',
                          'out_of_office','away','busy'
                        )),
    no_tickets_assigned INTEGER DEFAULT 0,
    solved_tickets      INTEGER DEFAULT 0,
    current_workload    INTEGER DEFAULT 0
);

-- ── 6. user_data ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_data (
    user_id                 VARCHAR(100) PRIMARY KEY,
    user_name               VARCHAR(255) NOT NULL,
    user_mail               VARCHAR(255) UNIQUE NOT NULL,
    user_password           VARCHAR(255),
    no_tickets_raised       INTEGER DEFAULT 0,
    current_raised_ticket   VARCHAR(100),
    available               BOOLEAN DEFAULT TRUE
);

-- ── 7. ticket_assignments ─────────────────────────────────────────────────────
-- FIXED: was in code but MISSING from v1 create_tables.sql
CREATE TABLE IF NOT EXISTS ticket_assignments (
    id                  SERIAL PRIMARY KEY,
    ticket_number       VARCHAR(100) REFERENCES new_tickets(ticketnumber) ON DELETE CASCADE,
    tech_id             VARCHAR(100) REFERENCES technician_data(tech_id),
    assigned_at         TIMESTAMP DEFAULT NOW(),
    unassigned_at       TIMESTAMP,
    assignment_status   VARCHAR(50) DEFAULT 'active' CHECK (assignment_status IN ('active','completed','reassigned','cancelled')),
    assignment_reason   TEXT,
    skill_match_score   INTEGER
);

-- ── 8. chat_sessions ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticket_number VARCHAR(100) REFERENCES new_tickets(ticketnumber) ON DELETE CASCADE,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- ── 9. chat_messages ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chat_messages (
    id          SERIAL PRIMARY KEY,
    session_id  UUID REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    role        VARCHAR(20) NOT NULL CHECK (role IN ('user','assistant','system')),
    content     TEXT NOT NULL,
    timestamp   TIMESTAMP DEFAULT NOW()
);

-- ── 10. agent_tasks (NEW) ─────────────────────────────────────────────────────
-- Desktop remediation agent task queue
CREATE TABLE IF NOT EXISTS agent_tasks (
    task_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticket_number   VARCHAR(100) REFERENCES new_tickets(ticketnumber) ON DELETE SET NULL,
    device_id       VARCHAR(255) NOT NULL,
    device_os       VARCHAR(50),
    command_type    VARCHAR(100) NOT NULL,   -- 'diagnostic' | 'restart_service' | 'run_script' | 'clear_temp'
    command_payload JSONB,                   -- structured command args
    status          VARCHAR(50) DEFAULT 'pending' CHECK (status IN ('pending','sent','running','completed','failed','timeout')),
    result_output   TEXT,
    result_exit_code INTEGER,
    created_at      TIMESTAMP DEFAULT NOW(),
    sent_at         TIMESTAMP,
    completed_at    TIMESTAMP
);

-- ── Indexes ───────────────────────────────────────────────────────────────────

-- new_tickets: heavy query targets
CREATE INDEX IF NOT EXISTS idx_nt_status        ON new_tickets(status);
CREATE INDEX IF NOT EXISTS idx_nt_priority      ON new_tickets(priority);
CREATE INDEX IF NOT EXISTS idx_nt_issuetype     ON new_tickets(issuetype);
CREATE INDEX IF NOT EXISTS idx_nt_createdate    ON new_tickets(createdate DESC);
CREATE INDEX IF NOT EXISTS idx_nt_user_id       ON new_tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_nt_assigned_tech ON new_tickets(assigned_tech_id);

-- historical_tickets: semantic search + filtering
CREATE INDEX IF NOT EXISTS idx_ht_issuetype  ON historical_tickets(issuetype);
CREATE INDEX IF NOT EXISTS idx_ht_priority   ON historical_tickets(priority);
CREATE INDEX IF NOT EXISTS idx_ht_createdate ON historical_tickets(createdate DESC);
-- Full-text search index for similarity fallback
CREATE INDEX IF NOT EXISTS idx_ht_fts
    ON historical_tickets
    USING GIN(to_tsvector('english', COALESCE(title,'') || ' ' || COALESCE(description,'')));

-- closed_tickets: similarity search
CREATE INDEX IF NOT EXISTS idx_ct_issuetype ON closed_tickets(issuetype);

-- ticket_assignments
CREATE INDEX IF NOT EXISTS idx_ta_ticket   ON ticket_assignments(ticket_number);
CREATE INDEX IF NOT EXISTS idx_ta_tech     ON ticket_assignments(tech_id);

-- agent_tasks
CREATE INDEX IF NOT EXISTS idx_at_device   ON agent_tasks(device_id);
CREATE INDEX IF NOT EXISTS idx_at_status   ON agent_tasks(status);
CREATE INDEX IF NOT EXISTS idx_at_ticket   ON agent_tasks(ticket_number);

-- ── LLM Observability Traces ─────────────────────────────────────────────────
-- Stores every LLM call made through the LangGraph pipeline.
-- Used by the custom observability dashboard (/api/traces).

CREATE TABLE IF NOT EXISTS llm_traces (
    id              SERIAL PRIMARY KEY,
    trace_id        UUID        NOT NULL DEFAULT uuid_generate_v4(),
    ticket_number   VARCHAR(50),                           -- linked ticket (if any)
    node_name       VARCHAR(100),                          -- LangGraph node (e.g. classify, gen_resolution)
    model           VARCHAR(100),                          -- e.g. llama-3.3-70b-versatile
    provider        VARCHAR(50),                           -- groq | openrouter
    prompt_preview  TEXT,                                  -- first 500 chars of prompt
    response_preview TEXT,                                 -- first 500 chars of response
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    latency_ms      INTEGER,
    status          VARCHAR(20) DEFAULT 'success' CHECK (status IN ('success','error','fallback')),
    error_message   TEXT,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lt_trace_id      ON llm_traces(trace_id);
CREATE INDEX IF NOT EXISTS idx_lt_ticket        ON llm_traces(ticket_number);
CREATE INDEX IF NOT EXISTS idx_lt_created       ON llm_traces(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lt_node          ON llm_traces(node_name);
CREATE INDEX IF NOT EXISTS idx_lt_provider      ON llm_traces(provider);
