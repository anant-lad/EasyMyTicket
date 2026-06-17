"""
Daily monitoring report endpoint.
Receives once-daily health reports from desktop agents, stores them,
then triggers the LangGraph analysis pipeline asynchronously.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

from src.database.db_connection import DatabaseConnection

router = APIRouter()
log    = logging.getLogger(__name__)


class DailyReport(BaseModel):
    schema_version: int = 3
    device_id:      str
    user_id:        str
    scan_time:      str
    system:         Dict[str, Any] = {}
    disk:           Dict[str, Any] = {}
    memory:         Dict[str, Any] = {}
    cpu:            Dict[str, Any] = {}
    battery:        Dict[str, Any] = {}
    services:       Dict[str, Any] = {}
    drivers:        Dict[str, Any] = {}
    network:        Dict[str, Any] = {}
    bluetooth:      Dict[str, Any] = {}
    security:       Dict[str, Any] = {}
    updates:        Dict[str, Any] = {}
    av:             Dict[str, Any] = {}
    all_issues:     list = []
    issue_count:    int  = 0


@router.post("/api/agent/daily-report", tags=["monitoring"], status_code=202)
async def receive_daily_report(report: DailyReport, background_tasks: BackgroundTasks):
    """
    Receive a daily health report from a desktop agent.
    Stores it and triggers background analysis.
    """
    db = DatabaseConnection()

    # Persist raw report
    report_dict = report.model_dump()
    rows = db.execute_query(
        """
        INSERT INTO daily_reports
            (device_id, user_id, os, hostname, scan_time, received_at, report)
        VALUES (%s, %s, %s, %s, %s, NOW(), %s::jsonb)
        RETURNING id
        """,
        (
            report.device_id,
            report.user_id,
            report.system.get("os", ""),
            report.system.get("hostname", ""),
            report.scan_time,
            __import__("json").dumps(report_dict),
        ),
    )
    report_id = rows[0]["id"] if rows else None
    log.info("Daily report stored: device=%s issues=%d id=%s",
             report.device_id, report.issue_count, report_id)

    # Trigger analysis in background (non-blocking)
    if report_id and report.issue_count > 0:
        background_tasks.add_task(
            _analyze_and_act, report_id, report_dict
        )

    return {
        "status":    "accepted",
        "report_id": report_id,
        "issues":    report.issue_count,
    }


@router.get("/api/agent/daily-reports/{device_id}", tags=["monitoring"])
def get_reports_for_device(device_id: str, limit: int = 7):
    """Retrieve recent daily reports for a device (for dashboard)."""
    db = DatabaseConnection()
    rows = db.execute_query(
        """SELECT id, device_id, user_id, scan_time, received_at,
                  issue_count, tickets_created, digest_sent, analysis
           FROM daily_reports WHERE device_id = %s
           ORDER BY received_at DESC LIMIT %s""",
        (device_id, min(limit, 30)),
    )
    return {"reports": rows or []}


# ─────────────────────────────────────────────────────────────────────────────
#  Background analysis pipeline
# ─────────────────────────────────────────────────────────────────────────────

async def _analyze_and_act(report_id: int, report: dict):
    """
    LLM analyses the daily report, auto-creates tickets for each issue,
    and sends the user a morning digest email.
    Called in a BackgroundTask — must not raise.
    """
    try:
        from src.graph.daily_report_graph import analyze_daily_report
        await analyze_daily_report(report_id, report)
    except Exception as e:
        log.error("Daily report analysis failed (id=%s): %s", report_id, e)
