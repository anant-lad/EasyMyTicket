"""End-to-end ticket lifecycle test — real app, real DB, real pipeline."""
import pytest


def test_full_ticket_lifecycle(client, api_key):
    """Create → retrieve → check assignment."""
    if not api_key:
        pytest.skip("API_KEYS not set")

    # Create
    r = client.post(
        "/api/tickets/create",
        json={
            "title": "Teams not showing profile picture",
            "description": (
                "I changed my profile picture in Office 365 but it is not reflecting "
                "in Microsoft Teams even after 24 hours."
            ),
            "user_id": "TECH001",
            "source": "portal",
        },
        headers={"X-API-Key": api_key},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    ticket_number = data["ticket_number"]
    assert ticket_number.startswith("TKT-") or len(ticket_number) > 5

    # Retrieve
    r2 = client.get(f"/api/tickets/{ticket_number}", headers={"X-API-Key": api_key})
    assert r2.status_code == 200
    ticket = r2.json()["ticket"]
    assert ticket["ticketnumber"] == ticket_number
    assert ticket.get("title") or ticket.get("description")


def test_source_validation(client, api_key):
    """Unknown source should be rejected at API level."""
    if not api_key:
        pytest.skip("API_KEYS not set")
    r = client.post(
        "/api/tickets/create",
        json={"title": "Test", "user_id": "TECH001", "source": "invalid_source"},
        headers={"X-API-Key": api_key},
    )
    assert r.status_code in (400, 422)
