-- Email Checkpoints Table
-- Tracks processed emails to prevent duplicates and manage email threads

CREATE TABLE IF NOT EXISTS email_checkpoints (
    id SERIAL PRIMARY KEY,
    message_id VARCHAR(500) UNIQUE NOT NULL,  -- Email Message-ID header (unique identifier)
    thread_id VARCHAR(500),                    -- Thread identifier (first Message-ID in thread)
    sender_email VARCHAR(255) NOT NULL,
    subject VARCHAR(500),
    ticket_number VARCHAR(100),                -- Associated ticket (NULL if reply to existing)
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    email_type VARCHAR(20) DEFAULT 'new',      -- 'new' = new ticket, 'reply' = thread reply
    references_ids TEXT,                       -- Comma-separated list of referenced Message-IDs
    in_reply_to VARCHAR(500),                  -- In-Reply-To header value
    action_taken VARCHAR(50) DEFAULT 'ticket_created'  -- 'ticket_created', 'ticket_updated', 'skipped'
);

-- Indexes for efficient lookups
CREATE INDEX IF NOT EXISTS idx_email_checkpoint_message_id ON email_checkpoints(message_id);
CREATE INDEX IF NOT EXISTS idx_email_checkpoint_thread_id ON email_checkpoints(thread_id);
CREATE INDEX IF NOT EXISTS idx_email_checkpoint_ticket ON email_checkpoints(ticket_number);
CREATE INDEX IF NOT EXISTS idx_email_checkpoint_sender ON email_checkpoints(sender_email);
CREATE INDEX IF NOT EXISTS idx_email_checkpoint_processed ON email_checkpoints(processed_at DESC);
