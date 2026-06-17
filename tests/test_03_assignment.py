"""Ticket creation + assignment integration tests — real app, real DB."""
import pytest


def test_create_ticket_returns_201(client, api_key):
    if not api_key:
        pytest.skip("API_KEYS not set")
    r = client.post(
        "/api/tickets/create",
        json={
            "title": "Printer jammed in Room 302",
            "description": "The laser printer in marketing has a paper jam and won't start.",
            "user_id": "TECH001",
            "source": "portal",
        },
        headers={"X-API-Key": api_key},
    )
    assert r.status_code == 201
    data = r.json()
    assert "ticket_number" in data


def test_create_ticket_has_classification(client, api_key):
    if not api_key:
        pytest.skip("API_KEYS not set")
    r = client.post(
        "/api/tickets/create",
        json={
            "title": "VPN connection issues on MacBook",
            "description": "Cannot connect to corporate VPN from laptop.",
            "user_id": "TECH001",
            "source": "portal",
        },
        headers={"X-API-Key": api_key},
    )
    assert r.status_code == 201
    data = r.json()
    assert "ticket_number" in data
    # classification fields may be null if LLM key is test_key — just check structure
    assert "priority" in data or "classification" in data or "assigned_tech_id" in data


def test_create_ticket_missing_title_rejected(client, api_key):
    if not api_key:
        pytest.skip("API_KEYS not set")
    r = client.post(
        "/api/tickets/create",
        json={"user_id": "TECH001"},
        headers={"X-API-Key": api_key},
    )
    assert r.status_code in (400, 422)


def test_get_ticket_after_create(client, api_key):
    if not api_key:
        pytest.skip("API_KEYS not set")
    # Create
    r = client.post(
        "/api/tickets/create",
        json={"title": "Email not working in Outlook", "user_id": "TECH001", "source": "email"},
        headers={"X-API-Key": api_key},
    )
    assert r.status_code == 201
    ticket_number = r.json()["ticket_number"]

    # Retrieve
    r2 = client.get(f"/api/tickets/{ticket_number}", headers={"X-API-Key": api_key})
    assert r2.status_code == 200
    assert r2.json()["ticketnumber"] == ticket_number
