-- Table 1: new_tickets
CREATE TABLE IF NOT EXISTS new_tickets (
    id SERIAL PRIMARY KEY,
    companyid VARCHAR(100),
    completeddate TIMESTAMP,
    createdate TIMESTAMP,
    description TEXT,
    duedatetime TIMESTAMP,
    estimatedhours NUMERIC(10, 2),
    firstresponsedatetime TIMESTAMP,
    issuetype VARCHAR(100),
    lastactivitydate TIMESTAMP,
    priority VARCHAR(50),
    queueid VARCHAR(100),
    resolution TEXT,
    resolutionplandatetime TIMESTAMP,
    resolveddatetime TIMESTAMP,
    status VARCHAR(50),
    subissuetype VARCHAR(100),
    ticketcategory VARCHAR(100),
    ticketnumber VARCHAR(100) UNIQUE,
    tickettype VARCHAR(100),
    title TEXT,
    user_id VARCHAR(100)
);

-- Table 2: resolved_tickets
CREATE TABLE IF NOT EXISTS resolved_tickets (
    id SERIAL PRIMARY KEY,
    companyid VARCHAR(100),
    completeddate TIMESTAMP,
    createdate TIMESTAMP,
    description TEXT,
    duedatetime TIMESTAMP,
    estimatedhours NUMERIC(10, 2),
    firstresponsedatetime TIMESTAMP,
    issuetype VARCHAR(100),
    lastactivitydate TIMESTAMP,
    priority VARCHAR(50),
    queueid VARCHAR(100),
    resolution TEXT,
    resolutionplandatetime TIMESTAMP,
    resolveddatetime TIMESTAMP,
    status VARCHAR(50),
    subissuetype VARCHAR(100),
    ticketcategory VARCHAR(100),
    ticketnumber VARCHAR(100) UNIQUE,
    tickettype VARCHAR(100),
    title TEXT
);

-- Table 3: technician_data
CREATE TABLE IF NOT EXISTS technician_data (
    tech_id VARCHAR(100) PRIMARY KEY,
    tech_name VARCHAR(255) NOT NULL,
    tech_mail VARCHAR(255) UNIQUE NOT NULL,
    tech_password VARCHAR(255),
    skills TEXT,
    no_tickets_assigned INTEGER DEFAULT 0,
    solved_tickets INTEGER DEFAULT 0,
    current_workload INTEGER DEFAULT 0,
    available BOOLEAN DEFAULT TRUE,
    availability VARCHAR(50) DEFAULT 'available'
);

-- Table 4: user_data
CREATE TABLE IF NOT EXISTS user_data (
    user_id VARCHAR(100) PRIMARY KEY,
    user_name VARCHAR(255) NOT NULL,
    user_mail VARCHAR(255) UNIQUE NOT NULL,
    user_password VARCHAR(255),
    no_tickets_raised INTEGER DEFAULT 0,
    current_raised_ticket VARCHAR(100),
    available BOOLEAN DEFAULT TRUE
);

-- Table 5: closed_tickets (for historical ticket data and similarity search)
CREATE TABLE IF NOT EXISTS closed_tickets (
    id SERIAL PRIMARY KEY,
    companyid VARCHAR(100),
    completeddate TIMESTAMP,
    createdate TIMESTAMP,
    description TEXT,
    duedatetime TIMESTAMP,
    estimatedhours NUMERIC(10, 2),
    firstresponsedatetime TIMESTAMP,
    issuetype VARCHAR(100),
    lastactivitydate TIMESTAMP,
    priority VARCHAR(50),
    queueid VARCHAR(100),
    resolution TEXT,
    resolutionplandatetime TIMESTAMP,
    resolveddatetime TIMESTAMP,
    status VARCHAR(50),
    subissuetype VARCHAR(100),
    ticketcategory VARCHAR(100),
    ticketnumber VARCHAR(100) UNIQUE,
    tickettype VARCHAR(100),
    title TEXT
);


-- Table 6: chat_sessions
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_number VARCHAR(100) REFERENCES new_tickets(ticketnumber) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table 7: chat_messages
CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL, -- 'user' or 'assistant'
    content TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table 8: organizations (master table for company/organization data)
-- Tickets reference this via existing companyid field
CREATE TABLE IF NOT EXISTS organizations (
    id SERIAL PRIMARY KEY,
    companyid VARCHAR(10) UNIQUE NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    company_email VARCHAR(255),
    contact_phone VARCHAR(50),
    address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table 9: ticket_assignments (for tracking ticket assignment history)
CREATE TABLE IF NOT EXISTS ticket_assignments (
    id SERIAL PRIMARY KEY,
    ticket_number VARCHAR(100) REFERENCES new_tickets(ticketnumber) ON DELETE CASCADE,
    tech_id VARCHAR(100) REFERENCES technician_data(tech_id),
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    unassigned_at TIMESTAMP,
    assignment_status VARCHAR(50) DEFAULT 'assigned'
);

-- Add assigned_tech_id column to new_tickets if not exists
ALTER TABLE new_tickets ADD COLUMN IF NOT EXISTS assigned_tech_id VARCHAR(100);

-- Table 10: ticket_communications (for real-time user-technician messaging)
CREATE TABLE IF NOT EXISTS ticket_communications (
    message_id SERIAL PRIMARY KEY,
    ticket_number VARCHAR(100) NOT NULL,
    sender_type VARCHAR(20) NOT NULL CHECK (sender_type IN ('user', 'technician', 'system')),
    sender_id VARCHAR(100) NOT NULL,
    message_text TEXT NOT NULL,
    message_type VARCHAR(20) DEFAULT 'text' CHECK (message_type IN ('text', 'system', 'status_update')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    read_at TIMESTAMP,
    is_read BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_ticket_communications_ticket ON ticket_communications(ticket_number);
CREATE INDEX IF NOT EXISTS idx_ticket_communications_created ON ticket_communications(created_at DESC);

-- Table 11: ticket_user_feedback (for user feedback and ticket reopening)
CREATE TABLE IF NOT EXISTS ticket_user_feedback (
    feedback_id SERIAL PRIMARY KEY,
    ticket_number VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    feedback_text TEXT,
    is_resolved BOOLEAN NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reopened BOOLEAN DEFAULT FALSE,
    reopen_reason TEXT,
    previous_tech_id VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_ticket_feedback_ticket ON ticket_user_feedback(ticket_number);
CREATE INDEX IF NOT EXISTS idx_ticket_feedback_reopened ON ticket_user_feedback(reopened);
