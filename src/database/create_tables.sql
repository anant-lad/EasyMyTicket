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
    available BOOLEAN DEFAULT TRUE
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

