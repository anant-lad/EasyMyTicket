"""Resolution and daily-report route tests — real app, real DB."""
import pytest


def test_daily_report_accepted(client, api_key):
    if not api_key:
        pytest.skip("API_KEYS not set")
    r = client.post(
        "/api/agent/daily-report",
        json={
            "device_id": "ci-test-device",
            "user_id": "TECH001",
            "scan_time": "2026-06-17T06:00:00Z",
            "system": {"os": "Linux", "hostname": "ci-runner"},
            "all_issues": ["Disk at 90% capacity"],
            "issue_count": 1,
        },
        headers={"X-API-Key": api_key},
    )
    assert r.status_code == 202
    data = r.json()
    assert data.get("status") == "accepted"
    assert "report_id" in data


def test_daily_report_no_issues(client, api_key):
    if not api_key:
        pytest.skip("API_KEYS not set")
    r = client.post(
        "/api/agent/daily-report",
        json={
            "device_id": "ci-clean-device",
            "user_id": "TECH001",
            "scan_time": "2026-06-17T06:00:00Z",
            "system": {"os": "Linux", "hostname": "ci-clean"},
            "all_issues": [],
            "issue_count": 0,
        },
        headers={"X-API-Key": api_key},
    )
    assert r.status_code == 202
    assert r.json().get("issues") == 0


def test_technician_list(client, api_key):
    if not api_key:
        pytest.skip("API_KEYS not set")
    r = client.get("/api/technicians", headers={"X-API-Key": api_key})
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
