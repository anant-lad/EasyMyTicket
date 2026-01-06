# Project Structure

## Overview
This document describes the modular structure of the Ticket Intake Classification System.

## Directory Structure

```
EasyMyTicket/
├── main.py                          # FastAPI application entry point
├── routes/                          # API route handlers
│   ├── __init__.py
│   ├── ticket_routes.py            # Ticket creation and management endpoints
│   └── database_routes.py          # Database exploration endpoints
├── src/                             # Source code modules
│   ├── __init__.py
│   ├── config.py                   # Centralized configuration
│   ├── database/                   # Database layer
│   │   ├── __init__.py
│   │   ├── db_connection.py       # Database connection and operations
│   │   └── create_tables.sql      # Database schema definitions
│       ├── __init__.py
│       ├── intake_classification.py  # Classification agent
│       ├── smart_ticket_assignment.py # Technician matching logic
│       ├── resolution_generation.py  # Resolution AI agent
│       └── notification_agent.py     # Email notification agent
├── src/utils/
│       ├── picklist_loader.py        # Picklist/CSV utility
│       ├── email_sender.py           # SMTP mailer
│       └── oauth_manager.py          # Google OAuth logic
├── scripts/                         # Utility scripts
│   ├── README.md                   # Scripts documentation
│   ├── init_database.py            # Initialize database tables
│   ├── import_closed_tickets.py    # Import historical tickets
│   ├── import_resolved_tickets.py  # Legacy import script
│   └── add_user_id_column.py       # Migration script (one-time)
├── tests/                           # Test suite
│   ├── __init__.py
│   └── test_ticket_creation.py     # API integration tests
├── dataset/                         # Data files
│   └── ticket_data_updated.csv     # Historical ticket data
├── start_database.sh               # Database startup script
├── .env.example                    # Environment variables template
├── requirements.txt                # Python dependencies
├── .gitignore                      # Git ignore rules
├── README.md                       # Main documentation
├── PROJECT_STRUCTURE.md            # This file
└── workflow.png                    # Workflow diagram
```

## Module Responsibilities

### `src/config.py`
- Centralized configuration management
- Environment variable handling
- Application settings (database, API keys, models, etc.)

### `src/database/db_connection.py`
- PostgreSQL database connections
- GROQ LLM API integration
- Semantic similarity search using embeddings
- Database query execution
- Automatic table creation

### `src/agents/`
- **IntakeClassificationAgent**: Metadata extraction and classification.
- **SmartAssignmentAgent**: Skill-based matching and workload balancing.
- **ResolutionGenerationAgent**: Historical resolution analysis.
- **NotificationAgent**: Automated email responses.

### `src/utils/`
- **EmailSender**: Handles SMTP communications.
- **OAuthManager**: Manages Google OAuth client secrets.
- **PicklistLoader**: Normalizes ticket fields from CSV.

### `routes/ticket_routes.py`
- Ticket creation endpoint
- Ticket retrieval endpoint
- Health check endpoint
- Request/response validation

### `routes/database_routes.py`
- Database container management
- Database status checking
- Table listing and exploration
- Data browsing with pagination

### `main.py`
- FastAPI application setup
- CORS configuration
- Router registration
- Application startup events

### `tests/`
- Test suite for API endpoints
- Integration tests for ticket creation and retrieval
- Health check tests
- Test utilities and helpers

## Key Features

1. **Lazy Loading**: Database connections and agents are created on first use
2. **Automatic Table Creation**: Tables are created automatically if missing
3. **Semantic Search**: Uses embeddings for intelligent ticket similarity matching
4. **Modular Design**: Clear separation of concerns
5. **Configuration Management**: Centralized config in `src/config.py`

## Configuration

All configuration is managed through `src/config.py` which reads from:
- Environment variables
- `.env` file
- Default values

## Scripts

Utility scripts are organized in the `scripts/` directory:
- Database initialization
- Data import
- Migration scripts

## Testing

Test files are organized in the `tests/` directory:
- **`test_ticket_creation.py`**: Integration tests for ticket creation API
  - Tests ticket creation endpoint
  - Tests ticket retrieval endpoint
  - Tests health check endpoint
  - Validates API responses and data structures

To run tests:
```bash
# Run all tests
python -m pytest tests/

# Run specific test file
python tests/test_ticket_creation.py
```

