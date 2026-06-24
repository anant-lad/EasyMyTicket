"""
Email-to-ticket poller — runs as a background thread inside the ticket-worker pod.

Polls the Gmail IMAP inbox every 60 s. For each UNSEEN email:
  - If sender is a registered user → create a new ticket via the LangGraph pipeline.
  - If the subject contains a ticket number (Re: [EasyMyTicket] TKT-...) AND the
    sender is the ticket owner → append the email body as a comment instead.
  - Unrecognised senders are skipped (no account = no ticket).
  - Every processed email is marked SEEN so it's never processed twice.
"""
import email
import imaplib
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from email.header import decode_header
from typing import Optional

log = logging.getLogger(__name__)

_POLL_INTERVAL = 60  # seconds between IMAP polls
_TICKET_NUMBER_RE = re.compile(r"TKT-\d{14}-[A-Z0-9]{6}")


def _decode_str(value: str | bytes | None, charset: str | None = None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(charset or "utf-8", errors="replace")
    return value


def _decode_header_str(raw: str) -> str:
    parts = []
    for chunk, charset in decode_header(raw or ""):
        parts.append(_decode_str(chunk, charset))
    return "".join(parts).strip()


def _plain_body(msg: email.message.Message) -> str:
    """Extract plaintext body from a (possibly multipart) email."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = part.get("Content-Disposition", "")
            if ct == "text/plain" and "attachment" not in cd:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                return _decode_str(payload, charset)
        return ""
    payload = msg.get_payload(decode=True)
    charset = msg.get_content_charset() or "utf-8"
    return _decode_str(payload, charset)


def _lookup_user_by_email(db, sender_email: str) -> Optional[dict]:
    rows = db.execute_query(
        "SELECT user_id, user_name, user_mail FROM user_data WHERE LOWER(user_mail)=LOWER(%s)",
        (sender_email,),
    )
    return rows[0] if rows else None


def _find_existing_ticket(db, ticket_number: str, user_id: str) -> bool:
    rows = db.execute_query(
        "SELECT ticketnumber FROM new_tickets WHERE ticketnumber=%s AND user_id=%s",
        (ticket_number, user_id),
    )
    return bool(rows)


def _add_comment(db, ticket_number: str, user_id: str, author_name: str, body: str):
    db.execute_query(
        "INSERT INTO ticket_comments (ticket_number, content, role, author_name, author_type, created_at)"
        " VALUES (%s, %s, 'user', %s, 'user', NOW())",
        (ticket_number, body[:4000], author_name),
        fetch=False,
    )
    log.info("Added email reply as comment on %s from %s", ticket_number, user_id)


def _create_ticket_from_email(user: dict, subject: str, body: str):
    """Insert ticket row and kick off LangGraph pipeline (mirrors ticket_routes.py logic)."""
    from src.database.db_connection import DatabaseConnection
    from src.graph.ticket_graph import process_ticket

    user_id = user["user_id"]
    title = subject[:255] or "Email support request"
    description = body[:8000] or title

    ticket_number = f"TKT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

    db = DatabaseConnection()
    db.execute_query(
        "INSERT INTO new_tickets (ticketnumber, title, description, user_id, status, createdate, source)"
        " VALUES (%s,%s,%s,%s,'Open',NOW(),'email') ON CONFLICT (ticketnumber) DO NOTHING",
        (ticket_number, title, description, user_id),
        fetch=False,
    )
    log.info("Created ticket %s from email by %s", ticket_number, user_id)

    try:
        process_ticket(
            title=title,
            description=description,
            user_id=user_id,
            source="email",
            device_id=None,
            due_date_time=None,
            existing_ticket_number=ticket_number,
        )
    except Exception as exc:
        log.exception("Pipeline failed for email ticket %s: %s", ticket_number, exc)


def _process_email(uid_bytes: bytes, imap: imaplib.IMAP4_SSL):
    from src.database.db_connection import DatabaseConnection

    _, data = imap.fetch(uid_bytes, "(RFC822)")
    raw = data[0][1] if data and data[0] else None
    if not raw:
        return

    msg = email.message_from_bytes(raw)
    sender_raw = msg.get("From", "")
    match = re.search(r"[\w.+\-]+@[\w.\-]+", sender_raw)
    if not match:
        return
    sender_email = match.group(0).lower()

    db = DatabaseConnection()
    user = _lookup_user_by_email(db, sender_email)
    if not user:
        log.debug("Email from unregistered address %s — skipping", sender_email)
        return

    subject = _decode_header_str(msg.get("Subject", ""))
    body = _plain_body(msg).strip()

    # Check if this is a reply to an existing ticket
    ticket_match = _TICKET_NUMBER_RE.search(subject)
    if ticket_match:
        ticket_number = ticket_match.group(0)
        if _find_existing_ticket(db, ticket_number, user["user_id"]):
            _add_comment(db, ticket_number, user["user_id"], user["user_name"], body or subject)
            return

    # New ticket from email
    clean_subject = re.sub(r"^(Re|Fwd?):\s*", "", subject, flags=re.IGNORECASE).strip()
    _create_ticket_from_email(user, clean_subject or subject, body)


def _poll_once(imap: imaplib.IMAP4_SSL):
    imap.select("INBOX")
    _, data = imap.search(None, "UNSEEN")
    uid_list = data[0].split() if data and data[0] else []
    if not uid_list:
        return
    log.info("Email poller: %d unseen messages to process", len(uid_list))
    for uid in uid_list:
        try:
            _process_email(uid, imap)
        except Exception as exc:
            log.error("Error processing email uid %s: %s", uid, exc)
        finally:
            # Always mark as seen so we don't reprocess on error
            imap.store(uid, "+FLAGS", "\\Seen")


def _connect_imap(server: str, port: int, username: str, password: str) -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL(server, port)
    imap.login(username, password)
    log.info("Email poller connected to %s as %s", server, username)
    return imap


def run_email_poller():
    """Long-running loop. Call from a daemon thread."""
    from src.config import Config

    server   = getattr(Config, "IMAP_SERVER", "imap.gmail.com")
    port     = int(getattr(Config, "IMAP_PORT", 993))
    username = Config.SUPPORT_EMAIL
    password = Config.SUPPORT_EMAIL_APP_PASSWORD

    if not username or not password:
        log.warning("Email poller disabled — SUPPORT_EMAIL or SUPPORT_EMAIL_APP_PASSWORD not set")
        return

    imap: Optional[imaplib.IMAP4_SSL] = None

    while True:
        try:
            if imap is None:
                imap = _connect_imap(server, port, username, password)
            _poll_once(imap)
        except (imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError) as exc:
            log.warning("IMAP connection lost (%s) — reconnecting in 30 s", exc)
            try:
                if imap:
                    imap.logout()
            except Exception:
                pass
            imap = None
            time.sleep(30)
            continue
        except Exception as exc:
            log.exception("Unexpected error in email poller: %s", exc)

        time.sleep(_POLL_INTERVAL)


def start_email_poller_thread() -> threading.Thread:
    t = threading.Thread(target=run_email_poller, name="email-poller", daemon=True)
    t.start()
    log.info("Email poller thread started")
    return t
