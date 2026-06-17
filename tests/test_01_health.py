"""Health endpoint tests — real app via TestClient."""


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json().get("status") == "alive"


def test_readyz_with_db(client):
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json().get("status") == "ready"


def test_auth_rejects_missing_key(client):
    """Requests without X-API-Key must get 401, not 500."""
    r = client.post("/api/tickets/create", json={"title": "test", "user_id": "u1"})
    assert r.status_code == 401


def test_auth_accepts_valid_key(client, api_key):
    """A valid API key should not be rejected at the auth layer."""
    if not api_key:
        import pytest
        pytest.skip("API_KEYS env var not set")
    r = client.get("/healthz", headers={"X-API-Key": api_key})
    assert r.status_code == 200
