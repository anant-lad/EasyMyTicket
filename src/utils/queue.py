"""
SQS queue wrapper for async processing.
Falls back to synchronous execution if SQS is disabled or unavailable.
"""
import json
import logging
from typing import Any, Callable, Dict, Optional

log = logging.getLogger(__name__)

_sqs_client = None


def _get_sqs():
    global _sqs_client
    if _sqs_client is not None:
        return _sqs_client

    from src.config import Config
    if not Config.SQS_ENABLED:
        return None

    try:
        import boto3
        _sqs_client = boto3.client("sqs", region_name=Config.AWS_REGION)
        log.info("SQS client initialised (region=%s)", Config.AWS_REGION)
    except Exception as e:
        log.warning("SQS unavailable (%s) — falling back to synchronous execution", e)
        _sqs_client = None
    return _sqs_client


def send_notification(payload: Dict[str, Any]) -> bool:
    """
    Enqueue an email notification task.
    If SQS is unavailable, returns False (caller falls back to sync send).
    """
    from src.config import Config
    if not Config.SQS_NOTIFICATION_URL:
        return False

    client = _get_sqs()
    if not client:
        return False

    try:
        client.send_message(
            QueueUrl=Config.SQS_NOTIFICATION_URL,
            MessageBody=json.dumps(payload),
        )
        log.info("Notification queued: %s", payload.get("ticket_number", "?"))
        return True
    except Exception as e:
        log.warning("Failed to enqueue notification: %s", e)
        return False


def send_llm_job(payload: Dict[str, Any]) -> bool:
    """Enqueue a background LLM job."""
    from src.config import Config
    if not Config.SQS_LLM_URL:
        return False

    client = _get_sqs()
    if not client:
        return False

    try:
        client.send_message(
            QueueUrl=Config.SQS_LLM_URL,
            MessageBody=json.dumps(payload),
        )
        log.info("LLM job queued: type=%s", payload.get("job_type", "?"))
        return True
    except Exception as e:
        log.warning("Failed to enqueue LLM job: %s", e)
        return False


def consume_notifications(handler: Callable[[Dict], None], max_messages: int = 10):
    """Pull and process notification messages. Called by notification-worker pod."""
    from src.config import Config
    if not Config.SQS_NOTIFICATION_URL:
        return

    client = _get_sqs()
    if not client:
        return

    try:
        response = client.receive_message(
            QueueUrl=Config.SQS_NOTIFICATION_URL,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=20,
        )
        messages = response.get("Messages", [])
        for msg in messages:
            try:
                payload = json.loads(msg["Body"])
                handler(payload)
                client.delete_message(
                    QueueUrl=Config.SQS_NOTIFICATION_URL,
                    ReceiptHandle=msg["ReceiptHandle"],
                )
            except Exception as e:
                log.error("Failed to process notification message: %s", e)
    except Exception as e:
        log.error("SQS consume error: %s", e)
