"""
EasyMyTicket Desktop Agent — Daily Report Uploader
===================================================
Reads the locally-cached daily scan report and POSTs it to the server.
Retries when the network is unavailable (called by main.py on connect).

Usage:
    from agent.reporter import send_pending_report
    sent = await send_pending_report(api_url, api_key, device_id)
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("agent.reporter")

_CACHE_DIR      = Path(os.getenv("AGENT_CACHE_DIR", Path.home() / ".easymyticket"))
_REPORT_FILE    = _CACHE_DIR / "last_daily_report.json"
_SENT_FLAG_FILE = _CACHE_DIR / "last_report_sent_date.txt"


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def report_already_sent_today() -> bool:
    """True if we already uploaded a report for today (avoids duplicate sends)."""
    if not _SENT_FLAG_FILE.exists():
        return False
    try:
        return _SENT_FLAG_FILE.read_text().strip() == _today_str()
    except OSError:
        return False


def mark_report_sent():
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _SENT_FLAG_FILE.write_text(_today_str())
    except OSError as e:
        log.warning("Could not write sent flag: %s", e)


async def send_pending_report(
    api_url: str,
    api_key: str,
    device_id: str,
    force: bool = False,
) -> bool:
    """
    Upload the cached daily report to the server.

    Args:
        api_url:   Base URL of the EasyMyTicket API (http/https, not ws).
        api_key:   X-API-Key header value.
        device_id: This machine's device identifier.
        force:     Send even if already sent today (for testing).

    Returns:
        True if sent successfully, False otherwise.
    """
    if not force and report_already_sent_today():
        log.debug("Daily report already sent today — skipping")
        return True

    if not _REPORT_FILE.exists():
        log.debug("No cached report found at %s", _REPORT_FILE)
        return False

    try:
        report = json.loads(_REPORT_FILE.read_text())
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Could not read cached report: %s", e)
        return False

    # Normalise base URL (remove ws:// → http://)
    base = api_url.replace("wss://", "https://").replace("ws://", "http://").rstrip("/")
    url  = f"{base}/api/agent/daily-report"

    headers: dict = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    try:
        import httpx
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=report, headers=headers)
            if resp.status_code in (200, 201, 202):
                log.info("Daily report uploaded successfully (status=%d)", resp.status_code)
                mark_report_sent()
                return True
            else:
                log.warning("Daily report upload failed: HTTP %d — %s",
                            resp.status_code, resp.text[:200])
                return False
    except Exception as e:
        log.warning("Daily report upload error (will retry next connection): %s", e)
        return False


async def run_and_send(
    api_url: str,
    api_key: str,
    device_id: str,
    user_id: str,
) -> bool:
    """
    Convenience: run the scan, cache it, then immediately try to upload.
    Called at 06:00 by the OS scheduler entry point.
    """
    from agent.monitor import run_daily_scan
    log.info("Starting scheduled daily scan for device_id=%s", device_id)
    run_daily_scan(device_id=device_id, user_id=user_id)
    return await send_pending_report(api_url, api_key, device_id)
