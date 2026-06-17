"""
EasyMyTicket — Daily Report Analysis Pipeline (Part 1)
=======================================================
Called when the server receives a daily health report from a desktop agent.

Steps:
  1. LLM reads the full report and produces a structured analysis.
  2. For each issue found, auto-creates a ticket.
  3. For each ticket, decides: agent can fix (runs remediation session) OR
     needs a human technician (assigns + notifies).
  4. Sends the user a morning digest email summarising everything found.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage

from src.database.db_connection import DatabaseConnection
from src.llm.provider import get_callbacks, get_llm

log = logging.getLogger(__name__)

_ANALYSIS_SYSTEM = """You are an expert IT support engineer reviewing a daily system health report
from a user's computer. Your job is to:
1. Identify every real issue that needs attention.
2. Ignore minor warnings that don't require action.
3. For each issue, decide whether it can be fixed automatically by a remote agent
   or whether it requires a human technician.
4. Return a JSON array of issues.

Rules for auto-fix eligibility (can_agent_fix=true):
- Disk space low → agent can clear temp files
- Services crashed → agent can restart them
- DNS issues → agent can flush DNS
- Bluetooth/WiFi problems → agent can run diagnostics and fix
- Software updates pending → agent can install them
- AV scan overdue → agent can trigger scan
- Temp file bloat → agent can clear

Rules requiring human (can_agent_fix=false):
- Hardware failure (bad sectors, physical damage)
- Persistent kernel panics
- Security breach suspected
- Password/account issues requiring domain controller
- Issues requiring physical presence

Response format (JSON array only, no prose):
[
  {
    "title": "Short ticket title",
    "description": "Detailed description with specific metrics from the report",
    "category": "hardware|software|network|security|performance|general_inquiry",
    "priority": "critical|high|medium|low",
    "can_agent_fix": true,
    "fix_summary": "What the agent will do to fix this"
  }
]

If there are no real issues, return an empty array: []
"""


async def analyze_daily_report(report_id: int, report: Dict[str, Any]):
    """
    Main entry: analyse a daily report and take action on each issue.
    Called as a background task from monitoring_routes.py.
    """
    device_id   = report.get("device_id", "unknown")
    user_id     = report.get("user_id", "unknown")
    device_os   = report.get("system", {}).get("os", "Unknown")
    hostname    = report.get("system", {}).get("hostname", "unknown")
    all_issues  = report.get("all_issues", [])
    issue_count = report.get("issue_count", 0)

    log.info("Analysing daily report id=%d device=%s issues=%d", report_id, device_id, issue_count)

    if issue_count == 0:
        log.info("No issues found in report %d — no action needed", report_id)
        _mark_report_analyzed(report_id, "No issues detected.", [])
        return

    # ── LLM analysis ─────────────────────────────────────────────────────────
    issue_summary = "\n".join(f"- {i}" for i in all_issues)
    report_json   = json.dumps({
        "system":   report.get("system", {}),
        "disk":     report.get("disk", {}),
        "memory":   report.get("memory", {}),
        "services": report.get("services", {}),
        "security": report.get("security", {}),
        "updates":  report.get("updates", {}),
        "bluetooth":report.get("bluetooth", {}),
        "drivers":  report.get("drivers", {}),
        "av":       report.get("av", {}),
    }, indent=2)

    callbacks = get_callbacks()
    llm       = get_llm(callbacks)

    human_msg = (
        f"Daily health report for {hostname} (OS: {device_os}, User: {user_id}):\n\n"
        f"Issues detected:\n{issue_summary}\n\n"
        f"Full report:\n{report_json[:6000]}"  # truncate to stay in token budget
    )

    try:
        response  = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: llm.invoke([
                SystemMessage(content=_ANALYSIS_SYSTEM),
                HumanMessage(content=human_msg),
            ])
        )
        raw = response.content.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw[raw.find("["):]
        if raw.endswith("```"):
            raw = raw[:-3]
        issues_structured: List[Dict] = json.loads(raw)
    except Exception as e:
        log.error("LLM analysis failed for report %d: %s", report_id, e)
        # Fall back: create one generic ticket for all issues
        issues_structured = [{
            "title":         f"Daily scan found {issue_count} issue(s) on {hostname}",
            "description":   f"Issues detected:\n{issue_summary}",
            "category":      "general_inquiry",
            "priority":      "medium",
            "can_agent_fix": False,
            "fix_summary":   "",
        }]

    log.info("LLM identified %d actionable issues in report %d",
             len(issues_structured), report_id)

    if not issues_structured:
        _mark_report_analyzed(report_id, "LLM found no actionable issues.", [])
        return

    # ── Create tickets + act on each issue ───────────────────────────────────
    created_tickets: List[str] = []
    db = DatabaseConnection()

    for issue in issues_structured:
        ticket_number = await _create_ticket_for_issue(
            db, issue, device_id, user_id, report.get("scan_time", "")
        )
        if ticket_number:
            created_tickets.append(ticket_number)
            log.info("Auto-ticket created: %s — %s", ticket_number, issue.get("title", "?"))

            if issue.get("can_agent_fix") and device_id:
                # Kick off agentic remediation in background
                from routes.agent_routes import is_agent_connected
                if is_agent_connected(device_id):
                    asyncio.create_task(
                        _run_agent_fix(ticket_number, device_id, issue, user_id, device_os)
                    )
                else:
                    log.info("Device %s offline — ticket %s queued for next connection",
                             device_id, ticket_number)
                    # Mark as pending — remediation will start when agent reconnects
                    db.execute_query(
                        "UPDATE new_tickets SET status='Pending Agent' WHERE ticketnumber=%s",
                        (ticket_number,), fetch=False,
                    )
            else:
                # Route to human technician (uses existing pipeline)
                await _route_to_technician(db, ticket_number, issue)

    # ── Morning digest email ──────────────────────────────────────────────────
    analysis_summary = _build_digest_text(issues_structured, hostname)
    _mark_report_analyzed(report_id, analysis_summary, created_tickets)
    await _send_morning_digest(user_id, hostname, issues_structured, created_tickets)


async def _create_ticket_for_issue(
    db: DatabaseConnection,
    issue: Dict,
    device_id: str,
    user_id: str,
    scan_time: str,
) -> str:
    """Insert a ticket into new_tickets and return its ticket_number."""
    from datetime import datetime, timezone as tz
    import uuid as _uuid
    ticket_number = (
        f"AUTO-{datetime.now(tz.utc).strftime('%Y%m%d%H%M%S')}-"
        f"{_uuid.uuid4().hex[:5].upper()}"
    )
    priority_map = {"critical": "Critical", "high": "High",
                    "medium": "Medium", "low": "Low"}
    try:
        db.execute_query(
            """INSERT INTO new_tickets
               (ticketnumber, title, description, user_id, status, priority,
                issuetype, source, createdate)
               VALUES (%s, %s, %s, %s, 'Open', %s, %s, 'agent', NOW())""",
            (
                ticket_number,
                f"[AUTO] {issue['title']}",
                issue.get("description", ""),
                user_id,
                priority_map.get(issue.get("priority", "medium"), "Medium"),
                issue.get("category", "general_inquiry"),
            ),
            fetch=False,
        )
        return ticket_number
    except Exception as e:
        log.error("Failed to create auto-ticket: %s", e)
        return ""


async def _run_agent_fix(
    ticket_number: str,
    device_id: str,
    issue: Dict,
    user_id: str,
    device_os: str,
):
    """Kick off the agentic remediation session for an auto-created ticket."""
    from src.graph.remediation_graph import run_remediation_session
    try:
        result = await run_remediation_session(
            ticket_number=ticket_number,
            device_id=device_id,
            title=issue.get("title", ""),
            description=issue.get("description", ""),
            category=issue.get("category", "general_inquiry"),
            user_id=user_id,
            device_os=device_os,
        )
        log.info("Auto-fix complete for %s: resolved=%s steps=%d",
                 ticket_number, result.get("resolved"), result.get("step_count"))
    except Exception as e:
        log.error("Auto-fix failed for ticket %s: %s", ticket_number, e)


async def _route_to_technician(db: DatabaseConnection, ticket_number: str, issue: Dict):
    """Assign ticket to best available technician."""
    try:
        from src.agents.smart_ticket_assignment import SmartAssignmentAgent
        agent   = SmartAssignmentAgent(db)
        tech_id = agent.assign_ticket(
            ticket_data={"title": issue.get("title", ""), "ticketnumber": ticket_number},
            classification={"issuetype": issue.get("category", "general_inquiry"),
                            "priority":  issue.get("priority", "medium")},
        )
        if tech_id:
            db.execute_query(
                "UPDATE new_tickets SET assigned_tech_id=%s WHERE ticketnumber=%s",
                (tech_id, ticket_number), fetch=False,
            )
            log.info("Ticket %s assigned to tech %s", ticket_number, tech_id)
    except Exception as e:
        log.warning("Could not assign ticket %s: %s", ticket_number, e)


async def _send_morning_digest(
    user_id: str,
    hostname: str,
    issues: List[Dict],
    ticket_numbers: List[str],
):
    """Send a morning summary email to the user."""
    try:
        from src.utils.email_sender import EmailSender
        from src.database.db_connection import DatabaseConnection

        db = DatabaseConnection()
        user_rows = db.execute_query(
            "SELECT tech_mail AS email FROM technician_data WHERE tech_id = %s LIMIT 1", (user_id,)
        )
        if not user_rows or not user_rows[0].get("email"):
            log.debug("No email found for user_id=%s — skipping digest", user_id)
            return

        user_email = user_rows[0]["email"]
        auto_fix   = [i for i in issues if i.get("can_agent_fix")]
        human_fix  = [i for i in issues if not i.get("can_agent_fix")]

        lines = [f"Good morning! Here's your daily health report for {hostname}.\n"]
        if auto_fix:
            lines.append(f"🤖 Automatically fixing ({len(auto_fix)} issue(s)):")
            for i in auto_fix:
                lines.append(f"  • {i['title']} — {i.get('fix_summary','')}")
        if human_fix:
            lines.append(f"\n👨‍💻 Requires technician attention ({len(human_fix)} issue(s)):")
            for i in human_fix:
                lines.append(f"  • [{i.get('priority','?').upper()}] {i['title']}")
        if ticket_numbers:
            lines.append(f"\nTicket(s) created: {', '.join(ticket_numbers)}")
        if not issues:
            lines.append("✅ All systems healthy — no issues found today.")

        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: EmailSender.send_email(
                to_email=user_email,
                subject=f"EasyMyTicket Daily Report — {hostname} — {len(issues)} issue(s)",
                body="\n".join(lines),
            ),
        )
        log.info("Morning digest sent to %s", user_email)
    except Exception as e:
        log.warning("Could not send morning digest: %s", e)


def _build_digest_text(issues: List[Dict], hostname: str) -> str:
    if not issues:
        return f"No actionable issues on {hostname}."
    summaries = [f"- [{i.get('priority','?')}] {i.get('title','?')}" for i in issues]
    return f"{len(issues)} issue(s) on {hostname}:\n" + "\n".join(summaries)


def _mark_report_analyzed(report_id: int, analysis: str, tickets: List[str]):
    try:
        db = DatabaseConnection()
        db.execute_query(
            "UPDATE daily_reports SET analysis=%s, tickets_created=%s, digest_sent=TRUE WHERE id=%s",
            (analysis, tickets, report_id), fetch=False,
        )
    except Exception as e:
        log.warning("Could not update report %d: %s", report_id, e)
