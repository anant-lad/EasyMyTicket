"""Notification agent unit tests — pure logic, no SMTP/SQS."""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_notify_technician_skips_without_email():
    """Gracefully skips when tech_mail is absent — no exception."""
    from src.agents.notification_agent import NotificationAgent
    with patch("src.agents.notification_agent.sqs_queue") as mock_sqs:
        mock_sqs.send_notification.return_value = True
        agent = NotificationAgent()
        result = agent.notify_technician(
            ticket_data={"ticketnumber": "TKT-001", "title": "Test", "priority": "2"},
            tech_data={"tech_name": "Alice"},  # no tech_mail
        )
    assert result is False


def test_notify_user_skips_without_email():
    from src.agents.notification_agent import NotificationAgent
    with patch("src.agents.notification_agent.sqs_queue") as mock_sqs:
        mock_sqs.send_notification.return_value = True
        agent = NotificationAgent()
        result = agent.notify_user(
            ticket_data={"ticketnumber": "TKT-001", "title": "Test", "priority": "2"},
            user_data={"user_name": "Bob"},  # no user_mail
        )
    assert result is False


def test_notify_technician_sends_via_sqs():
    from src.agents.notification_agent import NotificationAgent
    with patch("src.agents.notification_agent.sqs_queue") as mock_sqs:
        mock_sqs.send_notification.return_value = True
        agent = NotificationAgent()
        result = agent.notify_technician(
            ticket_data={"ticketnumber": "TKT-002", "title": "VPN issue", "priority": "2"},
            tech_data={"tech_name": "Alice", "tech_mail": "alice@example.com"},
        )
    assert result is True
    mock_sqs.send_notification.assert_called_once()
    payload = mock_sqs.send_notification.call_args[0][0]
    assert payload["to"] == "alice@example.com"
    assert "TKT-002" in payload["subject"]
