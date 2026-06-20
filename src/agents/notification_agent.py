"""
Notification Agent — enqueues emails via SQS (async) with synchronous fallback.
All emails use professional HTML templates with EasyMyTicket branding.
"""
import logging
from typing import Dict, List, Optional

from src.utils.email_sender import EmailSender
from src.utils.picklist_loader import get_picklist_loader
from src.utils import queue as sqs_queue

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  HTML template helpers
# ─────────────────────────────────────────────────────────────────────────────

_PRIORITY_COLOR = {
    "Critical": "#dc2626",
    "High":     "#ea580c",
    "Medium":   "#2563eb",
    "Low":      "#6b7280",
}

_STATUS_COLOR = {
    "Open":          "#f59e0b",
    "In Progress":   "#3b82f6",
    "Resolved":      "#10b981",
    "Pending Agent": "#8b5cf6",
    "Escalated":     "#ef4444",
}


def _priority_badge(priority: str) -> str:
    color = _PRIORITY_COLOR.get(priority, "#6b7280")
    return (
        f'<span style="background:{color};color:#fff;padding:2px 10px;'
        f'border-radius:12px;font-size:12px;font-weight:600;">{priority}</span>'
    )


def _status_badge(status: str) -> str:
    color = _STATUS_COLOR.get(status, "#6b7280")
    return (
        f'<span style="background:{color};color:#fff;padding:2px 10px;'
        f'border-radius:12px;font-size:12px;font-weight:600;">{status}</span>'
    )


def _wrap_html(title: str, preheader: str, body_html: str) -> str:
    """Wrap email body in a consistent branded HTML shell."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <span style="display:none;max-height:0;overflow:hidden;">{preheader}</span>

  <!-- Outer wrapper -->
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f1f5f9;padding:32px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" border="0"
             style="max-width:600px;width:100%;background:#ffffff;border-radius:12px;
                    overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.07);">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%);
                     padding:28px 36px;text-align:center;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="text-align:left;">
                  <span style="font-size:22px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;">
                    🎫 EasyMyTicket
                  </span>
                  <br>
                  <span style="font-size:12px;color:#94a3b8;margin-top:2px;display:block;">
                    Intelligent IT Support
                  </span>
                </td>
                <td style="text-align:right;vertical-align:middle;">
                  <span style="font-size:11px;color:#64748b;">Automated Notification</span>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:36px 36px 24px;">
            {body_html}
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f8fafc;border-top:1px solid #e2e8f0;
                     padding:20px 36px;text-align:center;">
            <p style="margin:0;font-size:12px;color:#94a3b8;line-height:1.6;">
              This is an automated message from <strong>EasyMyTicket Support System</strong>.<br>
              Please do not reply to this email — use the portal to respond to tickets.
            </p>
            <p style="margin:8px 0 0;font-size:11px;color:#cbd5e1;">
              © 2025 EasyMyTicket · Blackshift Technologies LLP
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _ticket_meta_table(ticket_number: str, title: str, priority: str,
                        category: str = "", status: str = "") -> str:
    rows = [
        ("Ticket Number", f'<code style="font-family:monospace;background:#f1f5f9;padding:2px 6px;border-radius:4px;">{ticket_number}</code>'),
        ("Title", f"<strong>{title}</strong>"),
    ]
    if priority:
        rows.append(("Priority", _priority_badge(priority.capitalize())))
    if category:
        rows.append(("Category", category))
    if status:
        rows.append(("Status", _status_badge(status.capitalize())))

    cells = "".join(
        f"""<tr>
          <td style="padding:8px 12px;font-size:13px;color:#64748b;font-weight:500;
                     white-space:nowrap;width:140px;">{k}</td>
          <td style="padding:8px 12px;font-size:13px;color:#1e293b;">{v}</td>
        </tr>"""
        for k, v in rows
    )
    return f"""<table cellpadding="0" cellspacing="0" border="0"
           style="width:100%;border:1px solid #e2e8f0;border-radius:8px;
                  border-collapse:separate;border-spacing:0;overflow:hidden;">
    <thead>
      <tr style="background:#f8fafc;">
        <th colspan="2" style="padding:10px 12px;font-size:11px;font-weight:700;
                               color:#94a3b8;text-transform:uppercase;letter-spacing:0.8px;
                               text-align:left;border-bottom:1px solid #e2e8f0;">
          Ticket Details
        </th>
      </tr>
    </thead>
    <tbody>{cells}</tbody>
  </table>"""


def _cta_button(label: str, url: str, color: str = "#2563eb") -> str:
    return f"""<table cellpadding="0" cellspacing="0" border="0" style="margin:24px 0;">
    <tr>
      <td style="border-radius:8px;background:{color};">
        <a href="{url}" target="_blank"
           style="display:inline-block;padding:12px 28px;font-size:14px;font-weight:600;
                  color:#ffffff;text-decoration:none;letter-spacing:0.2px;">
          {label} →
        </a>
      </td>
    </tr>
  </table>"""


# ─────────────────────────────────────────────────────────────────────────────
#  NotificationAgent
# ─────────────────────────────────────────────────────────────────────────────

PORTAL_URL = "https://easymyticket.vercel.app"


class NotificationAgent:
    def __init__(self):
        self.email_sender = EmailSender()

    # ── Legacy method (used by some older call sites) ─────────────────────────
    def notify_technician(self, ticket_data: Dict, tech_data: Dict) -> bool:
        tech_email = tech_data.get("tech_mail")
        if not tech_email:
            return False
        tn   = ticket_data.get("ticketnumber", "")
        title = ticket_data.get("title", "")
        body = _wrap_html(
            title=f"New Ticket Assigned — {tn}",
            preheader=f"You have been assigned ticket {tn}: {title}",
            body_html=f"""
              <h2 style="margin:0 0 8px;font-size:20px;color:#0f172a;">New Ticket Assigned</h2>
              <p style="margin:0 0 24px;font-size:14px;color:#475569;">
                Hello <strong>{tech_data.get("tech_name", "Technician")}</strong>,
                a new support ticket has been assigned to you. Please review and respond promptly.
              </p>
              {_ticket_meta_table(tn, title, ticket_data.get("priority",""), ticket_data.get("issuetype",""))}
              {_cta_button("View Ticket", f"{PORTAL_URL}/tech/tickets/{tn}")}
            """,
        )
        return self._send({"to": tech_email, "subject": f"[EasyMyTicket] New Ticket: {tn} — {title}", "body": body, "is_html": True})

    def notify_user(self, ticket_data: Dict, user_data: Dict, tech_data: Optional[Dict] = None) -> bool:
        user_email = user_data.get("user_mail")
        if not user_email:
            return False
        tn    = ticket_data.get("ticketnumber", "")
        title = ticket_data.get("title", "")
        tech_block = ""
        if tech_data:
            tech_block = f"""
              <div style="margin-top:20px;padding:16px;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;">
                <p style="margin:0;font-size:13px;color:#166534;">
                  <strong>👨‍💻 Assigned Technician:</strong> {tech_data.get("tech_name","—")}<br>
                  <strong>Email:</strong> {tech_data.get("tech_mail","—")}
                </p>
              </div>"""
        body = _wrap_html(
            title=f"Your ticket {tn} has been received",
            preheader=f"Ticket {tn} is open and being processed.",
            body_html=f"""
              <h2 style="margin:0 0 8px;font-size:20px;color:#0f172a;">Ticket Received</h2>
              <p style="margin:0 0 24px;font-size:14px;color:#475569;">
                Hello <strong>{user_data.get("user_name", "there")}</strong>,
                your support ticket has been received and is being processed by our system.
              </p>
              {_ticket_meta_table(tn, title, ticket_data.get("priority",""))}
              {tech_block}
              {_cta_button("Track Your Ticket", f"{PORTAL_URL}/portal/tickets/{tn}")}
            """,
        )
        return self._send({"to": user_email, "subject": f"[EasyMyTicket] Ticket {tn} Received — {title}", "body": body, "is_html": True})

    def notify_oversight_tech(
        self,
        tech_name: str,
        tech_email: str,
        ticket_number: str,
        title: str,
        session_id: str,
    ) -> bool:
        """Notify a technician that they have been assigned as oversight for an agent session."""
        body = _wrap_html(
            title=f"Agent Oversight Assignment — {ticket_number}",
            preheader=f"You are overseeing AI agent session for ticket {ticket_number}",
            body_html=f"""
              <div style="background:#f5f3ff;border:1px solid #ddd6fe;border-radius:8px;
                          padding:16px 20px;margin-bottom:24px;display:flex;align-items:center;gap:12px;">
                <span style="font-size:28px;">🤖</span>
                <div>
                  <p style="margin:0;font-size:13px;font-weight:700;color:#5b21b6;">AI Agent Dispatched</p>
                  <p style="margin:2px 0 0;font-size:12px;color:#6d28d9;">
                    An AI agent has been dispatched to automatically resolve this ticket.
                    You are assigned as the human oversight technician.
                  </p>
                </div>
              </div>

              <h2 style="margin:0 0 8px;font-size:20px;color:#0f172a;">Oversight Assignment</h2>
              <p style="margin:0 0 24px;font-size:14px;color:#475569;">
                Hello <strong>{tech_name}</strong>,<br><br>
                You have been assigned as the <strong>oversight technician</strong> for the following
                AI-driven remediation session. Your role is to monitor the agent's progress,
                approve high-risk operations (Tier-2 commands), and intervene if escalation is needed.
              </p>

              {_ticket_meta_table(ticket_number, title, "", "", "Pending Agent")}

              <div style="margin-top:20px;padding:16px;background:#fefce8;border:1px solid #fde68a;border-radius:8px;">
                <p style="margin:0;font-size:13px;color:#92400e;">
                  <strong>⚡ Your responsibilities:</strong>
                </p>
                <ul style="margin:8px 0 0;padding-left:20px;font-size:13px;color:#78350f;line-height:1.8;">
                  <li>Monitor the live agent trace in the technician portal</li>
                  <li>Approve or reject Tier-2 (fix) commands when prompted</li>
                  <li>Escalate to manual resolution if the agent fails after 3 attempts</li>
                  <li>Review the final session report once the agent completes</li>
                </ul>
              </div>

              <div style="margin-top:12px;padding:12px 16px;background:#f8fafc;border:1px solid #e2e8f0;
                          border-radius:8px;">
                <p style="margin:0;font-size:12px;color:#64748b;">
                  Session ID: <code style="font-family:monospace;background:#e2e8f0;padding:1px 4px;border-radius:3px;">{session_id[:16]}…</code>
                </p>
              </div>

              {_cta_button("Monitor Agent Session", f"{PORTAL_URL}/tech/sessions/{session_id}", color="#7c3aed")}
              {_cta_button("View Ticket", f"{PORTAL_URL}/tech/tickets/{ticket_number}", color="#0f172a")}
            """,
        )
        return self._send({
            "to":      tech_email,
            "subject": f"[EasyMyTicket] 🤖 Oversight Assignment — {ticket_number}: {title}",
            "body":    body,
            "is_html": True,
            "ticket_number": ticket_number,
        })

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
    ) -> List[str]:
        from src.database.db_connection import DatabaseConnection
        db = DatabaseConnection()
        sent = []

        # ── Notify assigned technician (human path only) ─────────────────────
        if assigned_tech_id and not auto_resolved and not agent_dispatched:
            try:
                rows = db.execute_query(
                    "SELECT tech_name, tech_mail FROM technician_data WHERE tech_id=%s", (assigned_tech_id,)
                )
                if rows and rows[0].get("tech_mail"):
                    tech = rows[0]
                    resolution_block = ""
                    if resolution:
                        resolution_block = f"""
                          <div style="margin-top:20px;">
                            <p style="margin:0 0 8px;font-size:13px;font-weight:600;color:#374151;">
                              💡 AI-Suggested Resolution Steps
                            </p>
                            <div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;
                                        padding:16px;font-size:13px;color:#0c4a6e;
                                        line-height:1.7;white-space:pre-wrap;">{resolution[:600]}{"…" if len(resolution) > 600 else ""}</div>
                          </div>"""
                    body = _wrap_html(
                        title=f"New Ticket Assigned — {ticket_number}",
                        preheader=f"Ticket {ticket_number} assigned to you: {title}",
                        body_html=f"""
                          <h2 style="margin:0 0 8px;font-size:20px;color:#0f172a;">New Ticket Assigned to You</h2>
                          <p style="margin:0 0 24px;font-size:14px;color:#475569;">
                            Hello <strong>{tech.get("tech_name","Technician")}</strong>,
                            a new support ticket has been assigned to you. Please review it and begin
                            working on a resolution as soon as possible.
                          </p>
                          {_ticket_meta_table(ticket_number, title, priority.capitalize(), category, "Open")}
                          {resolution_block}
                          {_cta_button("Open Ticket in Portal", f"{PORTAL_URL}/tech/tickets/{ticket_number}")}
                        """,
                    )
                    self._send({
                        "to": tech["tech_mail"],
                        "subject": f"[EasyMyTicket] 🎫 Ticket Assigned: {ticket_number} — {title}",
                        "body":    body,
                        "is_html": True,
                        "ticket_number": ticket_number,
                    })
                    sent.append(tech["tech_mail"])
            except Exception as e:
                log.warning("Could not notify technician %s: %s", assigned_tech_id, e)

        # ── Notify ticket creator / user ─────────────────────────────────────
        if user_id:
            try:
                rows = db.execute_query(
                    "SELECT user_mail AS email, user_name AS full_name FROM user_data WHERE user_id=%s LIMIT 1",
                    (user_id,),
                )
                if not rows:
                    rows = db.execute_query(
                        "SELECT tech_mail AS email, tech_name AS full_name FROM technician_data WHERE tech_id=%s LIMIT 1",
                        (user_id,),
                    )
                if rows and rows[0].get("email"):
                    email     = rows[0]["email"]
                    full_name = rows[0].get("full_name", "there")

                    if agent_dispatched:
                        status_block = f"""
                          <div style="margin-top:20px;padding:16px 20px;background:#f5f3ff;
                                      border:1px solid #ddd6fe;border-radius:8px;">
                            <p style="margin:0;font-size:14px;font-weight:700;color:#5b21b6;">
                              🤖 AI Agent Dispatched
                            </p>
                            <p style="margin:6px 0 0;font-size:13px;color:#6d28d9;line-height:1.6;">
                              Our AI agent has been dispatched to your device to diagnose and
                              automatically fix this issue. You can track its progress in real time
                              from your ticket page.
                            </p>
                          </div>"""
                    elif auto_resolved:
                        status_block = f"""
                          <div style="margin-top:20px;padding:16px 20px;background:#f0fdf4;
                                      border:1px solid #bbf7d0;border-radius:8px;">
                            <p style="margin:0;font-size:14px;font-weight:700;color:#15803d;">
                              ✅ Auto-Resolved
                            </p>
                            <p style="margin:6px 0 0;font-size:13px;color:#166534;line-height:1.6;">
                              {resolution[:400] if resolution else "Your ticket has been automatically resolved."}
                            </p>
                          </div>"""
                    else:
                        status_block = f"""
                          <div style="margin-top:20px;padding:16px 20px;background:#eff6ff;
                                      border:1px solid #bfdbfe;border-radius:8px;">
                            <p style="margin:0;font-size:14px;font-weight:700;color:#1d4ed8;">
                              👨‍💻 Technician Assigned
                            </p>
                            <p style="margin:6px 0 0;font-size:13px;color:#1e40af;line-height:1.6;">
                              A technician has been assigned to your ticket and will reach out shortly.
                            </p>
                          </div>"""

                    body = _wrap_html(
                        title=f"Ticket {ticket_number} — Update",
                        preheader=f"Your ticket {ticket_number} has been received and is being handled.",
                        body_html=f"""
                          <h2 style="margin:0 0 8px;font-size:20px;color:#0f172a;">
                            Your Ticket is In Good Hands
                          </h2>
                          <p style="margin:0 0 24px;font-size:14px;color:#475569;">
                            Hello <strong>{full_name}</strong>,<br><br>
                            Thank you for reaching out. Your support ticket has been received,
                            classified, and is now being handled. Here's a summary:
                          </p>
                          {_ticket_meta_table(ticket_number, title, priority.capitalize(), category)}
                          {status_block}
                          {_cta_button("Track Your Ticket", f"{PORTAL_URL}/portal/tickets/{ticket_number}")}
                        """,
                    )
                    self._send({
                        "to":      email,
                        "subject": f"[EasyMyTicket] Ticket {ticket_number} — {'AI Agent Dispatched' if agent_dispatched else 'Assigned'}",
                        "body":    body,
                        "is_html": True,
                        "ticket_number": ticket_number,
                    })
                    sent.append(email)
            except Exception as e:
                log.warning("Could not notify user %s: %s", user_id, e)

        return sent

    def _send(self, payload: Dict) -> bool:
        if sqs_queue.send_notification(payload):
            return True
        log.info("SQS unavailable — sending email synchronously to %s", payload["to"])
        return self.email_sender.send_email(
            payload["to"],
            payload["subject"],
            payload["body"],
            is_html=payload.get("is_html", False),
        )
