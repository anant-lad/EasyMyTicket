"""
Notification Agent — enqueues emails via SQS (async) with synchronous fallback.
"""
import logging
from typing import Dict, Optional

from src.utils.email_sender import EmailSender
from src.utils.picklist_loader import get_picklist_loader
from src.utils import queue as sqs_queue

log = logging.getLogger(__name__)


class NotificationAgent:
    def __init__(self):
        self.email_sender = EmailSender()

    def notify_technician(self, ticket_data: Dict, tech_data: Dict) -> bool:
        tech_email = tech_data.get("tech_mail")
        if not tech_email:
            log.warning("Technician email missing — skipping notification")
            return False

        picklist = get_picklist_loader()
        priority_label = (
            picklist.get_label("priority", str(ticket_data.get("priority")))
            or ticket_data.get("priority", "N/A")
        )

        subject = f"New Ticket Assigned: {ticket_data.get('ticketnumber')} - {ticket_data.get('title')}"
        body = (
            f"Hello {tech_data.get('tech_name', 'Technician')},\n\n"
            f"Ticket Number: {ticket_data.get('ticketnumber')}\n"
            f"Title: {ticket_data.get('title')}\n"
            f"Description: {ticket_data.get('description')}\n"
            f"Priority: {priority_label}\n"
            f"Due Date: {ticket_data.get('duedatetime') or 'N/A'}\n\n"
            f"Best regards,\nEasyMyTicket Support System"
        )

        return self._send(
            {
                "type": "technician",
                "to": tech_email,
                "subject": subject,
                "body": body,
                "ticket_number": ticket_data.get("ticketnumber"),
            }
        )

    def notify_user(
        self, ticket_data: Dict, user_data: Dict, tech_data: Optional[Dict] = None
    ) -> bool:
        user_email = user_data.get("user_mail")
        if not user_email:
            log.warning("User email missing — skipping notification")
            return False

        picklist = get_picklist_loader()
        priority_label = (
            picklist.get_label("priority", str(ticket_data.get("priority")))
            or ticket_data.get("priority", "N/A")
        )
        category_label = (
            picklist.get_label("ticketcategory", str(ticket_data.get("ticketcategory")))
            or ticket_data.get("ticketcategory", "N/A")
        )
        issue_label = (
            picklist.get_label("issuetype", str(ticket_data.get("issuetype")))
            or ticket_data.get("issuetype", "N/A")
        )

        tech_info = ""
        if tech_data:
            tech_info = (
                f"\nAssigned Technician: {tech_data.get('tech_name', 'N/A')}"
                f"\nTechnician Email: {tech_data.get('tech_mail', 'N/A')}"
            )

        subject = f"Ticket Created: {ticket_data.get('ticketnumber')}"
        body = (
            f"Hello {user_data.get('user_name', 'User')},\n\n"
            f"Your ticket has been created.\n\n"
            f"Ticket Number: {ticket_data.get('ticketnumber')}\n"
            f"Title: {ticket_data.get('title')}\n"
            f"Category: {category_label}\n"
            f"Issue Type: {issue_label}\n"
            f"Priority: {priority_label}"
            f"{tech_info}\n\n"
            f"Best regards,\nEasyMyTicket Support System"
        )

        return self._send(
            {
                "type": "user",
                "to": user_email,
                "subject": subject,
                "body": body,
                "ticket_number": ticket_data.get("ticketnumber"),
            }
        )

    def send_ticket_notification(
        self,
        ticket_number: str,
        title: str,
        priority: str,
        category: str,
        resolution: str,
        assigned_tech_id: Optional[str],
        user_id: Optional[str],
        auto_resolved: bool = False,
        agent_dispatched: bool = False,
    ) -> list:
        """
        High-level notification called by notify_node.
        Looks up tech/user email from DB and sends appropriate emails.
        Returns list of recipients notified.
        """
        from src.database.db_connection import DatabaseConnection
        db = DatabaseConnection()
        sent = []

        status_line = (
            "An agent has been dispatched to fix this automatically."
            if agent_dispatched
            else ("This ticket has been auto-resolved." if auto_resolved else "A technician has been assigned.")
        )

        # Notify assigned technician
        if assigned_tech_id and not auto_resolved and not agent_dispatched:
            try:
                rows = db.execute_query(
                    "SELECT tech_name, tech_mail FROM technician_data WHERE tech_id = %s",
                    (assigned_tech_id,),
                )
                if rows and rows[0].get("tech_mail"):
                    tech = rows[0]
                    self._send({
                        "type": "technician",
                        "to": tech["tech_mail"],
                        "subject": f"New Ticket Assigned: {ticket_number} — {title}",
                        "body": (
                            f"Hello {tech.get('tech_name', 'Technician')},\n\n"
                            f"A ticket has been assigned to you.\n\n"
                            f"Ticket: {ticket_number}\nTitle: {title}\n"
                            f"Priority: {priority.capitalize()}\nCategory: {category}\n\n"
                            f"Suggested Resolution:\n{resolution[:800]}\n\n"
                            f"Best regards,\nEasyMyTicket"
                        ),
                        "ticket_number": ticket_number,
                    })
                    sent.append(tech["tech_mail"])
            except Exception as e:
                log.warning("Could not notify technician %s: %s", assigned_tech_id, e)

        # Notify user/ticket creator
        if user_id:
            try:
                rows = db.execute_query(
                    "SELECT email, full_name FROM user_data WHERE user_id = %s LIMIT 1",
                    (user_id,),
                )
                if not rows:
                    # Fall back to technician_data (user_id may reference tech table)
                    rows = db.execute_query(
                        "SELECT tech_mail AS email, tech_name AS full_name FROM technician_data WHERE tech_id = %s LIMIT 1",
                        (user_id,),
                    )
                if rows and rows[0].get("email"):
                    user_email = rows[0]["email"]
                    user_name = rows[0].get("full_name", "User")
                    self._send({
                        "type": "user",
                        "to": user_email,
                        "subject": f"Ticket {ticket_number} Created — {title}",
                        "body": (
                            f"Hello {user_name},\n\n"
                            f"Your ticket has been received.\n\n"
                            f"Ticket: {ticket_number}\nTitle: {title}\n"
                            f"Priority: {priority.capitalize()}\nCategory: {category}\n\n"
                            f"{status_line}\n\n"
                            f"Best regards,\nEasyMyTicket Support"
                        ),
                        "ticket_number": ticket_number,
                    })
                    sent.append(user_email)
            except Exception as e:
                log.warning("Could not notify user %s: %s", user_id, e)

        return sent

    def _send(self, payload: Dict) -> bool:
        # Try async SQS first — keeps the ticket creation API response fast
        if sqs_queue.send_notification(payload):
            return True
        # Fallback: send synchronously
        log.info("SQS unavailable — sending email synchronously to %s", payload["to"])
        return self.email_sender.send_email(payload["to"], payload["subject"], payload["body"])
