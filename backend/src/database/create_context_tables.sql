-- ============================================================================
-- Context-Enhanced Ticket System - Additional Tables
-- ============================================================================
-- This migration adds support for:
-- 1. Rich ticket context storage (file analysis, entity extraction)
-- 2. File attachment tracking
-- 3. Human feedback collection for RLHF
-- 4. Model training history
-- ============================================================================

-- Table 1: tickets_context
-- Stores enriched context for each ticket including file analysis and entity extraction
CREATE TABLE IF NOT EXISTS tickets_context (
    context_id SERIAL PRIMARY KEY,
    id INTEGER NOT NULL REFERENCES new_tickets(id) ON DELETE CASCADE,
    ticket_number VARCHAR(100) REFERENCES new_tickets(ticketnumber) ON DELETE CASCADE,
    title TEXT,
    description TEXT,
    extracted_text TEXT,  -- All text extracted from uploaded files
    image_analysis JSONB,  -- OCR results, detected objects, tables from images
    table_data_parsed JSONB,  -- Structured data from CSV/XLSX files
    entities JSONB,  -- Extracted entities: product names, versions, error codes, systems
    context_summary TEXT,  -- LLM-generated summary for efficient reuse
    file_metadata JSONB,  -- List of attached files with metadata
    resolved_at TIMESTAMP,
    resolution_category VARCHAR(255),
    assigned_technician_id VARCHAR(100),
    human_feedback JSONB,  -- Ratings, corrections, and feedback
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast ticket lookups
CREATE INDEX IF NOT EXISTS idx_tickets_context_id ON tickets_context(id);
CREATE INDEX IF NOT EXISTS idx_tickets_context_ticket_number ON tickets_context(ticket_number);
CREATE INDEX IF NOT EXISTS idx_tickets_context_resolved_at ON tickets_context(resolved_at);


-- Table 2: ticket_attachments
-- Tracks all files uploaded with tickets
CREATE TABLE IF NOT EXISTS ticket_attachments (
    attachment_id SERIAL PRIMARY KEY,
    id INTEGER NOT NULL REFERENCES new_tickets(id) ON DELETE CASCADE,
    ticket_number VARCHAR(100) REFERENCES new_tickets(ticketnumber) ON DELETE CASCADE,
    file_name VARCHAR(255) NOT NULL,
    file_type VARCHAR(100) NOT NULL,  -- MIME type
    file_size BIGINT NOT NULL,  -- Size in bytes
    file_path TEXT NOT NULL,  -- Storage location (local or cloud URL)
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed BOOLEAN DEFAULT FALSE,
    processing_status VARCHAR(50) DEFAULT 'pending',  -- pending, processing, completed, failed
    extracted_content TEXT,  -- Extracted text/data from the file
    processing_error TEXT  -- Error message if processing failed
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_ticket_attachments_id ON ticket_attachments(id);
CREATE INDEX IF NOT EXISTS idx_ticket_attachments_ticket_number ON ticket_attachments(ticket_number);
CREATE INDEX IF NOT EXISTS idx_ticket_attachments_processing_status ON ticket_attachments(processing_status);


-- Table 3: feedback_data
-- Collects human feedback for RLHF (Reinforcement Learning from Human Feedback)
CREATE TABLE IF NOT EXISTS feedback_data (
    feedback_id SERIAL PRIMARY KEY,
    id INTEGER NOT NULL REFERENCES new_tickets(id) ON DELETE CASCADE,
    ticket_number VARCHAR(100) REFERENCES new_tickets(ticketnumber) ON DELETE CASCADE,
    feedback_type VARCHAR(50) NOT NULL,  -- 'classification', 'assignment', 'resolution'
    is_correct BOOLEAN,  -- For binary feedback (correct/incorrect)
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),  -- For quality ratings (1-5)
    correction_data JSONB,  -- What should have been correct
    comments TEXT,  -- Additional feedback comments
    technician_id VARCHAR(100),  -- Who provided the feedback
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for feedback analysis
CREATE INDEX IF NOT EXISTS idx_feedback_data_id ON feedback_data(id);
CREATE INDEX IF NOT EXISTS idx_feedback_data_ticket_number ON feedback_data(ticket_number);
CREATE INDEX IF NOT EXISTS idx_feedback_data_type ON feedback_data(feedback_type);
CREATE INDEX IF NOT EXISTS idx_feedback_data_created_at ON feedback_data(created_at);


-- Table 4: model_training_history
-- Tracks fine-tuning iterations and model performance
CREATE TABLE IF NOT EXISTS model_training_history (
    training_id SERIAL PRIMARY KEY,
    model_version VARCHAR(100) NOT NULL UNIQUE,
    base_model VARCHAR(100) NOT NULL,  -- e.g., 'llama-3.1-8b-instant'
    training_data_count INTEGER NOT NULL,
    feedback_data_count INTEGER NOT NULL,
    performance_metrics JSONB,  -- Accuracy, F1 scores, precision, recall, etc.
    training_config JSONB,  -- Hyperparameters and training settings
    trained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT FALSE,  -- Currently active model
    notes TEXT
);

-- Index for active model lookup
CREATE INDEX IF NOT EXISTS idx_model_training_active ON model_training_history(is_active);


-- Trigger to update updated_at timestamp on tickets_context
CREATE OR REPLACE FUNCTION update_tickets_context_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_tickets_context_timestamp
    BEFORE UPDATE ON tickets_context
    FOR EACH ROW
    EXECUTE FUNCTION update_tickets_context_timestamp();


-- Comments for documentation
COMMENT ON TABLE tickets_context IS 'Stores enriched context for tickets including file analysis and entity extraction for LLM consumption';
COMMENT ON TABLE ticket_attachments IS 'Tracks all files uploaded with tickets and their processing status';
COMMENT ON TABLE feedback_data IS 'Collects human feedback for RLHF and continuous model improvement';
COMMENT ON TABLE model_training_history IS 'Tracks fine-tuning iterations and model performance metrics';

COMMENT ON COLUMN tickets_context.extracted_text IS 'All text extracted from uploaded files (PDF, DOCX, TXT, etc.)';
COMMENT ON COLUMN tickets_context.image_analysis IS 'OCR results, detected objects, and tables extracted from images';
COMMENT ON COLUMN tickets_context.table_data_parsed IS 'Structured data parsed from CSV/XLSX files';
COMMENT ON COLUMN tickets_context.entities IS 'Extracted entities like product names, versions, error codes, affected systems';
COMMENT ON COLUMN tickets_context.context_summary IS 'LLM-generated summary optimized for context reuse and preventing hallucination';
