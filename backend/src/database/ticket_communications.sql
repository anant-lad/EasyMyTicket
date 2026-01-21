-- ============================================================================
-- Ticket Communications Table
-- ============================================================================
-- Stores real-time communication between users and technicians for tickets
-- Preserves chat history even after ticket closure
-- ============================================================================

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

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_ticket_communications_ticket ON ticket_communications(ticket_number);
CREATE INDEX IF NOT EXISTS idx_ticket_communications_created ON ticket_communications(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ticket_communications_sender ON ticket_communications(sender_id);

-- Comments for documentation
COMMENT ON TABLE ticket_communications IS 'Real-time communication between users and technicians for ticket discussions';
COMMENT ON COLUMN ticket_communications.sender_type IS 'Type of sender: user, technician, or system';
COMMENT ON COLUMN ticket_communications.message_type IS 'Type of message: text (regular message), system (automated), or status_update';
COMMENT ON COLUMN ticket_communications.is_read IS 'Whether the message has been read by the recipient';
