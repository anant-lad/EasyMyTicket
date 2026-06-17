"""
SQS notification worker — runs in the ticket-worker pod.
Continuously polls the notification queue and sends emails.
"""
import logging
import os
import signal
import sys
import time

from src.utils.logger import setup_logging

setup_logging()
log = logging.getLogger(__name__)

_running = True
_HEARTBEAT_FILE = "/tmp/worker_heartbeat"


def _handle_signal(sig, frame):
    global _running
    log.info("Received signal %s — shutting down", sig)
    _running = False


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


def _touch_heartbeat():
    """Update heartbeat timestamp so the liveness probe knows we're alive."""
    try:
        with open(_HEARTBEAT_FILE, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def handle_notification(payload: dict):
    from src.utils.email_sender import EmailSender
    sender = EmailSender()
    to      = payload.get("to", "")
    subject = payload.get("subject", "")
    body    = payload.get("body", "")

    if not to:
        log.warning("Notification payload missing 'to' field: %s", payload)
        return

    success = sender.send_email(to, subject, body)
    if success:
        log.info("Email sent to %s for ticket %s", to, payload.get("ticket_number", "?"))
    else:
        log.error("Failed to send email to %s for ticket %s", to, payload.get("ticket_number", "?"))


def main():
    from src.utils import queue as sqs_queue
    log.info("Notification worker starting — polling SQS queue")
    _touch_heartbeat()   # write initial heartbeat so probe doesn't fail before first poll

    while _running:
        try:
            sqs_queue.consume_notifications(handle_notification, max_messages=10)
            _touch_heartbeat()
        except Exception as e:
            log.error("Worker loop error: %s", e)
            # Still touch heartbeat — loop is alive even if one poll errored
            _touch_heartbeat()

    log.info("Notification worker stopped")


if __name__ == "__main__":
    main()
