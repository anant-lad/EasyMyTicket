"""
Shared fixtures for the test suite.

In CI the PostgreSQL service container is already running on localhost:5432.
TestClient starts the real FastAPI app in-process — no mock server needed.
"""
import os
import pytest

# Set all env vars before any app imports
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "tickets_db")
os.environ.setdefault("DB_USER", "ticketing_admin")
os.environ.setdefault("DB_PASSWORD", os.environ.get("DB_PASSWORD", "test"))
os.environ.setdefault("DB_SSL_MODE", "disable")
os.environ.setdefault("REDIS_ENABLED", "false")
os.environ.setdefault("SQS_ENABLED", "false")
os.environ.setdefault("GROQ_API_KEY", os.environ.get("GROQ_API_KEY", "test_key"))
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("LOG_LEVEL", "WARNING")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(scope="session")
def api_key():
    """Return the API key from env or a known test key."""
    raw = os.environ.get("API_KEYS", "")
    # API_KEYS may be a comma-separated list or a single key
    return raw.split(",")[0].strip() if raw else ""
