"""
Daily monitoring report endpoint.
Receives once-daily health reports from desktop agents, stores them,
then triggers the LangGraph analysis pipeline asynchronously.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel

from src.auth.dependencies import optional_user
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


@router.get("/api/dashboard/stats", tags=["monitoring"])
def get_dashboard_stats(payload: dict = Depends(optional_user)):
    """Summary stats for the technician dashboard (global + per-tech if caller is a technician)."""
    db = DatabaseConnection()
    rows = db.execute_query("""
        SELECT
            COUNT(*) FILTER (WHERE status='Open')          AS open_count,
            COUNT(*) FILTER (WHERE status='In Progress')   AS in_progress_count,
            COUNT(*) FILTER (WHERE status='Pending Agent') AS pending_agent_count,
            COUNT(*) FILTER (WHERE status='Resolved')      AS resolved_count,
            COUNT(*) FILTER (WHERE createdate >= NOW() - INTERVAL '24 hours') AS created_today
        FROM new_tickets WHERE ticketnumber LIKE 'TKT-%'
    """)
    ticket_stats = rows[0] if rows else {}

    session_rows = db.execute_query("""
        SELECT
            COUNT(*) FILTER (WHERE status='running')           AS active_sessions,
            COUNT(*) FILTER (WHERE status='awaiting_approval') AS awaiting_approval,
            COUNT(*) FILTER (WHERE status='resolved' AND completed_at >= NOW() - INTERVAL '24 hours') AS resolved_today
        FROM agent_sessions
    """)
    session_stats = session_rows[0] if session_rows else {}

    from routes.agent_routes import _connected_agents
    result = {
        "tickets": {
            "open":           int(ticket_stats.get("open_count") or 0),
            "in_progress":    int(ticket_stats.get("in_progress_count") or 0),
            "pending_agent":  int(ticket_stats.get("pending_agent_count") or 0),
            "resolved":       int(ticket_stats.get("resolved_count") or 0),
            "created_today":  int(ticket_stats.get("created_today") or 0),
        },
        "sessions": {
            "active":            int(session_stats.get("active_sessions") or 0),
            "awaiting_approval": int(session_stats.get("awaiting_approval") or 0),
            "resolved_today":    int(session_stats.get("resolved_today") or 0),
        },
        "agents": {
            "connected": len(_connected_agents),
        },
    }

    # Per-tech stats when the caller is a technician
    if payload and payload.get("role") in ("tech", "tech_lead", "admin"):
        tech_id = payload.get("sub")
        my_rows = db.execute_query("""
            SELECT
                COUNT(*) FILTER (WHERE status='Open')       AS my_open,
                COUNT(*) FILTER (WHERE status='In Progress') AS my_in_progress,
                COUNT(*) FILTER (WHERE status='Resolved'
                    AND resolveddatetime >= NOW() - INTERVAL '24 hours') AS my_resolved_today
            FROM new_tickets WHERE ticketnumber LIKE 'TKT-%%' AND assigned_tech_id=%s
        """, (tech_id,))
        my_stats = my_rows[0] if my_rows else {}
        # Also fetch the DB-side workload counter for comparison
        wl_rows = db.execute_query(
            "SELECT current_workload FROM technician_data WHERE tech_id=%s LIMIT 1", (tech_id,)
        )
        db_workload = int((wl_rows[0].get("current_workload") or 0) if wl_rows else 0)
        result["my_tickets"] = {
            "open":           int(my_stats.get("my_open") or 0),
            "in_progress":    int(my_stats.get("my_in_progress") or 0),
            "resolved_today": int(my_stats.get("my_resolved_today") or 0),
            "workload_column": db_workload,
        }

    return result


@router.get("/api/agent/sessions", tags=["monitoring"])
def list_sessions(status: str = None, limit: int = 20):
    """List agentic sessions, optionally filtered by status."""
    db = DatabaseConnection()
    if status:
        rows = db.execute_query(
            """SELECT s.*, t.title, t.issuetype AS category
               FROM agent_sessions s
               LEFT JOIN new_tickets t ON t.ticketnumber = s.ticket_number
               WHERE s.status = %s
               ORDER BY s.created_at DESC LIMIT %s""",
            (status, min(limit, 100)),
        )
    else:
        rows = db.execute_query(
            """SELECT s.*, t.title, t.issuetype AS category
               FROM agent_sessions s
               LEFT JOIN new_tickets t ON t.ticketnumber = s.ticket_number
               ORDER BY s.created_at DESC LIMIT %s""",
            (min(limit, 100),),
        )
    return {"sessions": rows or []}


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
