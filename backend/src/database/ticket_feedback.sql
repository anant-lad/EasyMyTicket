-- ============================================================================
-- Ticket User Feedback Table
-- ============================================================================
-- Stores user feedback on resolved/closed tickets
-- Supports ticket reopening when users mark tickets as "not resolved"
-- ============================================================================

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

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_ticket_feedback_ticket ON ticket_user_feedback(ticket_number);
CREATE INDEX IF NOT EXISTS idx_ticket_feedback_reopened ON ticket_user_feedback(reopened);
CREATE INDEX IF NOT EXISTS idx_ticket_feedback_user ON ticket_user_feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_ticket_feedback_created ON ticket_user_feedback(created_at DESC);

-- Comments for documentation
COMMENT ON TABLE ticket_user_feedback IS 'User feedback on resolved/closed tickets with reopening capability';
COMMENT ON COLUMN ticket_user_feedback.is_resolved IS 'true = user is satisfied, false = ticket needs to be reopened';
COMMENT ON COLUMN ticket_user_feedback.reopened IS 'Whether this feedback resulted in ticket being reopened';
COMMENT ON COLUMN ticket_user_feedback.previous_tech_id IS 'Technician who previously handled the ticket (for reassignment on reopen)';
