"""
Structured JSON logger — outputs to stdout (CloudWatch ingests from EKS pods).

Every line is a JSON object, so CloudWatch Insights / kubectl logs | jq work out of the box.

Usage:
    from src.utils.logger import get_logger, flow
    log = get_logger(__name__)

    # Standard levels
    log.info("message")
    log.warning("something wrong")
    log.error("error", exc_info=True)

    # Flow-stage markers  — queryable via CloudWatch Insights:
    #   fields @timestamp, ticket, stage, message
    #   | filter stage like "TICKET"
    flow(log, "TICKET_CREATED",  ticket=tkt_num, user=uid, source=src, priority=pri)
    flow(log, "CLASSIFIED",      ticket=tkt_num, issuetype="Network", subissuetype="VPN/Remote Access")
    flow(log, "ROUTED:AGENT",    ticket=tkt_num, device=dev_id, confidence=0.91)
    flow(log, "ROUTED:TECH",     ticket=tkt_num, tech=tech_name, score=0.75)
    flow(log, "AGENT:CONNECTED", device=dev_id, os="linux", hostname="LAPTOP-001")
    flow(log, "AGENT:START",     session=sess_id, ticket=tkt_num, device=dev_id)
    flow(log, "AGENT:STEP",      session=sess_id, step=n, command="wifi_status")
    flow(log, "AGENT:RESOLVED",  session=sess_id, ticket=tkt_num, steps=n)
    flow(log, "AGENT:ESCALATED", session=sess_id, ticket=tkt_num, reason="...")
"""
import logging
import sys
import json
import time
import traceback
from datetime import datetime, timezone
from typing import Any

# Custom FLOW level sits between INFO (20) and WARNING (30)
FLOW_LEVEL = 25
logging.addLevelName(FLOW_LEVEL, "FLOW")


class _JSONFormatter(logging.Formatter):
    """
    Emits one JSON object per line. Fields:
      timestamp, level, logger, message
      + any keyword args passed via flow() — e.g. ticket, session, stage
    """
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts":      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level":   record.levelname,
            "module":  record.name.split(".")[-1],   # short name for readability
            "logger":  record.name,
            "msg":     record.getMessage(),
        }
        # Structured context attached by flow() or log.xxx(extra={...})
        for key in ("stage", "ticket", "session", "device", "tech", "user",
                    "source", "issuetype", "subissuetype", "priority",
                    "step", "command", "exit_code", "duration_ms", "steps",
                    "confidence", "score", "reason", "method", "count"):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val
        # Catch any other extra dict attached as record.extra
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            payload.update(record.extra)
        if record.exc_info:
            payload["exception"] = traceback.format_exception(*record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging():
    try:
        from src.config import Config
        level_name = Config.LOG_LEVEL.upper()
    except Exception:
        level_name = "INFO"

    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JSONFormatter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]   # avoid duplicate handlers on hot-reload

    # Quieten noisy third-party libraries
    for lib in ("fastembed", "transformers", "urllib3", "httpx", "httpcore",
                "botocore", "boto3", "langchain", "openai"):
        logging.getLogger(lib).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def flow(logger: logging.Logger, stage: str, **ctx: Any) -> None:
    """
    Emit a FLOW-level log line with a named pipeline stage and structured context.

    Example:
        flow(log, "TICKET_CREATED", ticket="TKT-20260624-001", user="u123", source="portal")

    CloudWatch Insights query:
        fields ts, stage, ticket, msg
        | filter level = "FLOW"
        | sort ts asc
    """
    extra = {"stage": stage, **ctx}
    # Build a human-readable message so plain `kubectl logs` is scannable
    ctx_str = " | ".join(f"{k}={v}" for k, v in ctx.items() if v is not None)
    msg = f"[{stage}]  {ctx_str}" if ctx_str else f"[{stage}]"
    record = logger.makeRecord(
        name=logger.name,
        level=FLOW_LEVEL,
        fn="",
        lno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for k, v in extra.items():
        setattr(record, k, v)
    logger.handle(record)


class Timer:
    """Context manager for measuring elapsed time in milliseconds."""
    def __init__(self):
        self._start = time.monotonic()

    @property
    def ms(self) -> int:
        return int((time.monotonic() - self._start) * 1000)

    @property
    def s(self) -> float:
        return round(time.monotonic() - self._start, 2)
