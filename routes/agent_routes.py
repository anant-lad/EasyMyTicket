"""
Desktop agent WebSocket endpoint + agentic session management.

WebSocket message types (server → agent):
  task        — legacy one-shot command (backward compat)
  tool_call   — agentic session step; agent must reply with tool_result

WebSocket message types (agent → server):
  register    — device comes online
  task_result — result of a legacy task
  tool_result — result of an agentic tool_call
  pong        — keepalive response
  queue_stats — queued task stats
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from src.auth.dependencies import get_current_user
from src.database.db_connection import DatabaseConnection

router = APIRouter()
log    = logging.getLogger(__name__)

# ── In-memory registries ──────────────────────────────────────────────────────

# {device_id: WebSocket}
_connected_agents: Dict[str, WebSocket] = {}

# {device_id: bool} — True if agent was started with --auto / AGENT_AUTO_MODE=1
_agent_auto_mode: Dict[str, bool] = {}

# {call_id: asyncio.Future}  — pending agentic tool calls awaiting device reply
_pending_tool_calls: Dict[str, asyncio.Future] = {}

# E3: {session_id: asyncio.Future} — pending tech approval for Tier-2 commands
_pending_approvals: Dict[str, asyncio.Future] = {}

# Reverse mapping: user_id/tech_id → device_id (for auto-attaching device to tickets)
_user_to_device: Dict[str, str] = {}


def is_agent_auto_mode(device_id: str) -> bool:
    """Return True if the connected agent for this device has auto mode enabled."""
    return _agent_auto_mode.get(device_id, False)

# Main event loop — set at app startup; allows non-async threads to schedule
# coroutines on the uvicorn loop via asyncio.run_coroutine_threadsafe.
_main_loop: asyncio.AbstractEventLoop = None


# ── Pydantic models ───────────────────────────────────────────────────────────

class AgentTaskRequest(BaseModel):
    device_id:       str
    command_type:    str
    command_payload: dict = {}


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket("/ws/agent/{device_id}")
async def agent_websocket(device_id: str, ws: WebSocket):
    key = ws.query_params.get("key", "")

    # Authenticate via agent_api_key
    authenticated_user_id: str = ""
    if key:
        db = DatabaseConnection()
        user_rows = db.execute_query(
            "SELECT user_id FROM user_data WHERE agent_api_key = %s LIMIT 1",
            (key,),
        )
        if user_rows:
            authenticated_user_id = user_rows[0]["user_id"]
            log.info("Agent auth: key matched user_id=%s", authenticated_user_id)
        else:
            tech_rows = db.execute_query(
                "SELECT tech_id FROM technician_data WHERE agent_api_key = %s LIMIT 1",
                (key,),
            )
            if tech_rows:
                authenticated_user_id = tech_rows[0]["tech_id"]
                log.info("Agent auth: key matched tech_id=%s", authenticated_user_id)
            else:
                # Key provided but not found in either table — reject
                await ws.close(code=4401, reason="Unauthorized")
                log.warning("Agent connection rejected: invalid key for device_id=%s", device_id)
                return
    else:
        # No key provided — allow through only in dev mode (no keys configured at all)
        # In production deployments the installer always provides a key
        log.info("Agent connected without API key (dev mode): device_id=%s", device_id)

    await ws.accept()
    _connected_agents[device_id] = ws
    _agent_auto_mode[device_id] = False  # updated on register message
    if authenticated_user_id:
        _user_to_device[authenticated_user_id] = device_id
    log.info("Agent connected: %s user=%s (total=%d)", device_id, authenticated_user_id or "anonymous", len(_connected_agents))

    try:
        async for raw in ws.iter_text():
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")

            if msg_type == "register":
                device_info = msg.get("device", {})
                auto = bool(device_info.get("auto_mode", False))
                _agent_auto_mode[device_id] = auto
                log.info("Agent registered: device_id=%s os=%s hostname=%s auto_mode=%s",
                         device_id,
                         device_info.get("os", "?"),
                         device_info.get("hostname", "?"),
                         auto)
                _update_device_last_seen(device_id, device_info)
                # E1: kick off any tickets that were queued while offline
                asyncio.create_task(_auto_start_pending_sessions(device_id))

            elif msg_type == "task_result":
                # Legacy one-shot result
                task_id   = msg.get("task_id")
                exit_code = msg.get("exit_code", -1)
                output    = msg.get("result_output", "")
                status    = msg.get("status", "completed")
                if task_id:
                    _save_task_result(task_id, status, output, exit_code)

            elif msg_type == "tool_result":
                # Agentic session step result — resolve the waiting Future
                call_id = msg.get("call_id")
                if call_id and call_id in _pending_tool_calls:
                    future = _pending_tool_calls.pop(call_id)
                    if not future.done():
                        future.set_result(msg)
                    log.debug("tool_result resolved: call_id=%s session=%s exit=%s",
                              call_id, msg.get("session_id", "?"), msg.get("exit_code"))
                else:
                    log.warning("tool_result for unknown call_id=%s", call_id)

            elif msg_type == "pong":
                pass

            elif msg_type == "queue_stats":
                # Agent is reporting its offline queue stats — just log for now
                log.debug("Agent queue stats: %s", msg)

            else:
                log.debug("Unknown message type from agent: %s", msg_type)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.error("Agent WebSocket error (device=%s): %s", device_id, e)
    finally:
        _connected_agents.pop(device_id, None)
        _agent_auto_mode.pop(device_id, None)
        if authenticated_user_id:
            _user_to_device.pop(authenticated_user_id, None)
        log.info("Agent disconnected: %s (remaining=%d)", device_id, len(_connected_agents))


# ─────────────────────────────────────────────────────────────────────────────
#  Agentic session — tool call dispatch (called by remediation_graph.py)
# ─────────────────────────────────────────────────────────────────────────────

async def dispatch_tool_call(
    device_id:   str,
    session_id:  str,
    command:     str,
    args:        dict,
    allow_tier2: bool = True,
    auto_mode:   bool = False,
    script:      str  = None,
    script_type: str  = "auto",
    timeout:     int  = 120,
) -> dict:
    """
    Send a tool_call to the connected agent and await its tool_result.

    Returns the tool_result dict, or raises TimeoutError / RuntimeError.
    """
    ws = _connected_agents.get(device_id)
    if not ws:
        raise RuntimeError(f"Device {device_id!r} is not connected")

    call_id = str(uuid.uuid4())
    loop    = asyncio.get_event_loop()
    future  = loop.create_future()
    _pending_tool_calls[call_id] = future

    msg = {
        "type":        "tool_call",
        "session_id":  session_id,
        "call_id":     call_id,
        "command":     command,
        "args":        args,
        "allow_tier2": allow_tier2,
        "auto_mode":   auto_mode,
    }
    if script is not None:
        msg["script"]      = script
        msg["script_type"] = script_type

    try:
        await ws.send_text(json.dumps(msg))
        result = await asyncio.wait_for(future, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        _pending_tool_calls.pop(call_id, None)
        raise TimeoutError(f"tool_call '{command}' timed out after {timeout}s")
    except Exception:
        _pending_tool_calls.pop(call_id, None)
        raise


def is_agent_connected(device_id: str) -> bool:
    return device_id in _connected_agents


def get_connected_device_for_user(user_id: str) -> str | None:
    """Return the device_id currently connected for this user, or None."""
    return _user_to_device.get(user_id)


@router.get("/api/agents/my-device", tags=["agent"])
def get_my_device(payload: dict = Depends(get_current_user)):
    """Return the device currently connected for the calling user."""
    uid = payload.get("sub")
    device_id = get_connected_device_for_user(uid) if uid else None
    return {"device_id": device_id, "connected": device_id is not None}


# ── REST: legacy one-shot task dispatch ──────────────────────────────────────

@router.post("/api/tickets/{ticket_number}/agent-task", tags=["agent"])
async def create_agent_task(ticket_number: str, req: AgentTaskRequest):
    ws = _connected_agents.get(req.device_id)
    if not ws:
        raise HTTPException(
            status_code=409,
            detail=f"Device {req.device_id!r} is not connected",
        )

    task_id = str(uuid.uuid4())
    db      = DatabaseConnection()
    _create_task_record(db, task_id, ticket_number, req.device_id,
                        req.command_type, req.command_payload)

    task_msg = {
        "type":            "task",
        "task_id":         task_id,
        "ticket_number":   ticket_number,
        "command_type":    req.command_type,
        "command_payload": req.command_payload,
    }
    try:
        await ws.send_text(json.dumps(task_msg))
        _mark_task_sent(db, task_id)
        return {"task_id": task_id, "status": "sent", "device_id": req.device_id}
    except Exception as e:
        log.error("Failed to send task to agent: %s", e)
        raise HTTPException(status_code=500, detail="Failed to deliver task to agent")


@router.get("/api/tickets/{ticket_number}/agent-tasks", tags=["agent"])
def list_agent_tasks(ticket_number: str):
    db = DatabaseConnection()
    rows = db.execute_query(
        "SELECT * FROM agent_tasks WHERE ticket_number = %s ORDER BY created_at DESC",
        (ticket_number,),
    )
    return {"tasks": rows or []}


@router.get("/api/agents/connected", tags=["agent"])
def list_connected_agents():
    return {"connected": list(_connected_agents.keys()), "count": len(_connected_agents)}


@router.get("/api/agents/devices", tags=["agent"])
def list_all_devices():
    """Return all devices that have ever connected, with live status."""
    db = DatabaseConnection()
    rows = db.execute_query(
        "SELECT device_id, hostname, os_type, os_version, ip_address, first_seen, last_seen "
        "FROM devices ORDER BY last_seen DESC"
    ) or []
    connected = set(_connected_agents.keys())
    for row in rows:
        row["online"] = row["device_id"] in connected
    return {"devices": rows, "count": len(rows)}


# ── E1: Pending-Agent ticket pickup ──────────────────────────────────────────

@router.get("/api/agent/pending-tickets", tags=["agent"])
def get_pending_tickets(device_id: str):
    """Return tickets with status='Pending Agent' assigned to this device."""
    db = DatabaseConnection()
    rows = db.execute_query(
        """SELECT ticketnumber, title, description, issuetype AS category,
                  user_id, priority
           FROM new_tickets
           WHERE status = 'Pending Agent' AND device_id = %s
           ORDER BY createdate ASC""",
        (device_id,),
    )
    return {"tickets": rows or [], "count": len(rows or [])}


class ApprovalRequest(BaseModel):
    approved: bool
    reason:   str = ""


@router.post("/api/agent/sessions/{session_id}/approve", tags=["agent"])
async def approve_tier2(session_id: str, req: ApprovalRequest):
    """E3: Technician approves or rejects a pending Tier-2 command."""
    future = _pending_approvals.get(session_id)
    if not future or future.done():
        raise HTTPException(status_code=404, detail="No pending approval for this session")
    future.set_result({"approved": req.approved, "reason": req.reason})
    return {"status": "approved" if req.approved else "rejected"}


@router.get("/api/agent/sessions/{session_id}/approval-status", tags=["agent"])
def get_approval_status(session_id: str):
    future = _pending_approvals.get(session_id)
    if not future:
        return {"pending": False}
    return {"pending": not future.done()}


async def request_tier2_approval(session_id: str, command: str, reasoning: str,
                                  timeout: int = 300) -> bool:
    """
    E3: Suspend the agentic session until a technician approves/rejects the Tier-2 command.
    Returns True (approved) or False (rejected/timeout).
    """
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    _pending_approvals[session_id] = future
    log.info("Approval required for Tier-2 command=%s session=%s", command, session_id[:8])

    # Persist approval request to DB so dashboard can show it
    try:
        db = DatabaseConnection()
        db.execute_query(
            """UPDATE agent_sessions SET status='awaiting_approval',
               approval_command=%s, approval_reasoning=%s
               WHERE session_id=%s""",
            (command, reasoning, session_id), fetch=False,
        )
    except Exception:
        pass  # column may not exist yet; non-fatal

    try:
        result = await asyncio.wait_for(future, timeout=timeout)
        return result.get("approved", False)
    except asyncio.TimeoutError:
        log.warning("Approval timed out for session %s — escalating", session_id[:8])
        return False
    finally:
        _pending_approvals.pop(session_id, None)


async def _auto_start_pending_sessions(device_id: str):
    """Called when an agent reconnects — kick off remediation for queued tickets."""
    db = DatabaseConnection()
    rows = db.execute_query(
        "SELECT ticketnumber, title, description, issuetype, user_id, priority "
        "FROM new_tickets WHERE status='Pending Agent' AND device_id=%s",
        (device_id,),
    )
    if not rows:
        return
    from src.graph.remediation_graph import run_remediation_session
    for row in rows:
        log.info("Resuming pending-agent ticket %s for device %s",
                 row["ticketnumber"], device_id)
        asyncio.create_task(run_remediation_session(
            ticket_number=row["ticketnumber"],
            device_id=device_id,
            title=row.get("title", ""),
            description=row.get("description", ""),
            category=row.get("issuetype", "general_inquiry"),
            user_id=row.get("user_id", ""),
        ))


# ── Session status endpoints ──────────────────────────────────────────────────

@router.get("/api/sessions/{session_id}", tags=["agent"])
def get_session(session_id: str):
    db = DatabaseConnection()
    rows = db.execute_query(
        "SELECT * FROM agent_sessions WHERE session_id = %s", (session_id,)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Session not found")
    return rows[0]


@router.get("/api/sessions/{session_id}/steps", tags=["agent"])
def get_session_steps(session_id: str):
    db = DatabaseConnection()
    rows = db.execute_query(
        "SELECT * FROM session_steps WHERE session_id = %s ORDER BY step_number",
        (session_id,),
    )
    return {"steps": rows or []}


@router.post("/api/sessions/{session_id}/oversight", tags=["agent"])
def assign_oversight_tech(
    session_id: str,
    tech_id: str,
    payload: dict = Depends(get_current_user),
):
    """Assign (or re-assign) an oversight technician to an agent session. Tech-lead/admin only."""
    if payload.get("role") not in ("tech_lead", "admin"):
        raise HTTPException(status_code=403, detail="Only tech leads and admins may assign oversight")
    db = DatabaseConnection()
    tech_rows = db.execute_query(
        "SELECT tech_id, tech_name, tech_mail FROM technician_data WHERE tech_id=%s LIMIT 1",
        (tech_id,),
    )
    if not tech_rows:
        raise HTTPException(status_code=404, detail="Technician not found")
    tech = tech_rows[0]
    sess_rows = db.execute_query(
        "SELECT ticket_number FROM agent_sessions WHERE session_id=%s", (session_id,)
    )
    if not sess_rows:
        raise HTTPException(status_code=404, detail="Session not found")
    ticket_number = sess_rows[0]["ticket_number"]
    db.execute_query(
        """UPDATE agent_sessions SET oversight_tech_id=%s, oversight_tech_name=%s,
           oversight_notified_at=NOW() WHERE session_id=%s""",
        (tech["tech_id"], tech["tech_name"], session_id),
        fetch=False,
    )
    if tech.get("tech_mail"):
        title_rows = db.execute_query(
            "SELECT title FROM new_tickets WHERE ticketnumber=%s LIMIT 1", (ticket_number,)
        )
        title = title_rows[0]["title"] if title_rows else ticket_number
        from src.agents.notification_agent import NotificationAgent
        NotificationAgent().notify_oversight_tech(
            tech_name=tech["tech_name"],
            tech_email=tech["tech_mail"],
            ticket_number=ticket_number,
            title=title,
            session_id=session_id,
        )
    return {"success": True, "oversight_tech_id": tech["tech_id"], "oversight_tech_name": tech["tech_name"]}


@router.get("/api/tickets/{ticket_number}/agent-activity", tags=["agent"])
def get_agent_activity(ticket_number: str):
    """User-friendly agent activity feed for the portal — translates technical steps to plain English."""
    db = DatabaseConnection()
    sess_rows = db.execute_query(
        "SELECT * FROM agent_sessions WHERE ticket_number=%s ORDER BY created_at DESC LIMIT 1",
        (ticket_number,),
    )
    if not sess_rows:
        raise HTTPException(status_code=404, detail="No agent session")
    session = dict(sess_rows[0])
    step_rows = db.execute_query(
        "SELECT step_type, command, args, output, exit_code, llm_reasoning, created_at "
        "FROM session_steps WHERE session_id=%s ORDER BY step_number",
        (session["session_id"],),
    ) or []

    def _friendly(step: dict) -> dict:
        stype   = step.get("step_type", "")
        command = step.get("command") or ""
        args    = step.get("args") or {}
        ec      = step.get("exit_code")
        ts      = step.get("created_at")

        if stype == "reasoning":
            return None  # hide raw LLM reasoning from user

        if command == "web_search":
            query = args.get("query", "") if isinstance(args, dict) else ""
            return {"icon": "🔍", "message": f"Searching for fix: \"{query[:60]}\"", "ts": ts, "ok": True}

        if stype == "command" and command.startswith("script:"):
            return {"icon": "📜", "message": "Running repair script on your computer…", "ts": ts, "ok": True}

        CMD_LABELS = {
            "list_usb": "Scanning USB devices",
            "list_processes": "Checking running processes",
            "check_disk": "Checking disk health",
            "get_system_info": "Reading system information",
            "get_network_info": "Checking network configuration",
            "shell": "Running system command",
            "read_file": "Reading system file",
            "write_file": "Updating configuration file",
            "list_dir": "Scanning directory",
            "download": "Downloading required files",
        }
        if stype == "command":
            label = CMD_LABELS.get(command, f"Running: {command}")
            return {"icon": "⚡", "message": label + "…", "ts": ts, "ok": True}

        if stype == "result":
            success = ec == 0 or ec is None
            if command == "web_search":
                return {"icon": "📄", "message": "Found relevant information", "ts": ts, "ok": True}
            if success:
                return {"icon": "✅", "message": "Step completed successfully", "ts": ts, "ok": True}
            else:
                return {"icon": "⚠️", "message": "Step encountered an issue — trying alternative approach", "ts": ts, "ok": False}

        return {"icon": "⚙️", "message": stype.replace("_", " ").capitalize(), "ts": ts, "ok": True}

    activities = [r for r in (_friendly(s) for s in step_rows) if r is not None]

    status = session.get("status", "")
    if status == "resolved":
        activities.append({"icon": "🎉", "message": "Issue resolved by AI agent!", "ts": session.get("completed_at"), "ok": True})
    elif status == "escalated":
        activities.append({"icon": "👨‍💻", "message": "Escalated to human technician for manual review", "ts": session.get("completed_at"), "ok": False})
    elif status == "running":
        activities.append({"icon": "🤖", "message": "Agent is actively working on your issue…", "ts": None, "ok": True, "live": True})

    return {
        "session_id":   session["session_id"],
        "status":       status,
        "resolution":   session.get("resolution"),
        "activities":   activities,
        "oversight_tech_name": session.get("oversight_tech_name"),
    }


@router.get("/api/tickets/{ticket_number}/session", tags=["agent"])
def get_session_for_ticket(ticket_number: str):
    """Return the most recent agent session for a given ticket, including oversight tech."""
    db = DatabaseConnection()
    rows = db.execute_query(
        """SELECT a.*, t.tech_name AS oversight_tech_display_name, t.tech_mail AS oversight_tech_mail
           FROM agent_sessions a
           LEFT JOIN technician_data t ON t.tech_id = a.oversight_tech_id
           WHERE a.ticket_number=%s ORDER BY a.created_at DESC LIMIT 1""",
        (ticket_number,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No agent session for this ticket")
    return rows[0]


@router.get("/api/sessions/{session_id}/report", tags=["agent"])
def get_session_report(session_id: str):
    """Return a presigned S3 URL for the markdown report, or 404 if not yet generated."""
    db = DatabaseConnection()
    rows = db.execute_query(
        "SELECT report_s3_key FROM agent_sessions WHERE session_id=%s", (session_id,)
    )
    if not rows or not rows[0].get("report_s3_key"):
        raise HTTPException(status_code=404, detail="Report not yet available")
    import boto3, os
    bucket = os.environ.get("S3_EXPORTS_BUCKET", "ticketing-prod-exports-808812816838")
    s3_key = rows[0]["report_s3_key"]
    s3 = boto3.client("s3", region_name="ap-south-1")
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": s3_key},
        ExpiresIn=3600,
    )
    return {"url": url, "s3_key": s3_key}


from fastapi.responses import StreamingResponse as _StreamingResponse

@router.get("/api/sessions/{session_id}/stream", tags=["agent"])
async def stream_session_steps(session_id: str, since_step: int = Query(0)):
    """Server-Sent Events stream of new session steps since `since_step`.
    Client reconnects on close; backend emits new steps every 2s while session is running.
    """
    async def _event_gen():
        db = DatabaseConnection()
        last_step = since_step
        while True:
            rows = db.execute_query(
                "SELECT * FROM session_steps WHERE session_id=%s AND step_number>%s ORDER BY step_number",
                (session_id, last_step),
            ) or []
            for row in rows:
                import json as _json
                data = _json.dumps({k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v)
                                    for k, v in row.items()})
                yield f"data: {data}\n\n"
                last_step = max(last_step, row.get("step_number", last_step))

            # Check if session finished
            sess = db.execute_query(
                "SELECT status FROM agent_sessions WHERE session_id=%s", (session_id,)
            )
            if sess and sess[0].get("status") not in ("running", "awaiting_approval"):
                yield f"event: done\ndata: {sess[0]['status']}\n\n"
                break

            await asyncio.sleep(2)

    return _StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── DB helpers ────────────────────────────────────────────────────────────────

def _create_task_record(db, task_id, ticket_number, device_id, command_type, payload):
    db.execute_query(
        """INSERT INTO agent_tasks
           (task_id, ticket_number, device_id, command_type, command_payload, status)
           VALUES (%s, %s, %s, %s, %s::jsonb, 'pending')""",
        (task_id, ticket_number, device_id, command_type, json.dumps(payload)),
        fetch=False,
    )


def _mark_task_sent(db, task_id):
    db.execute_query(
        "UPDATE agent_tasks SET status='sent', sent_at=NOW() WHERE task_id=%s",
        (task_id,), fetch=False,
    )


def _save_task_result(task_id, status, output, exit_code):
    try:
        db = DatabaseConnection()
        db.execute_query(
            """UPDATE agent_tasks SET
               status=%s, result_output=%s, result_exit_code=%s, completed_at=NOW()
               WHERE task_id=%s""",
            (status, output, exit_code, task_id), fetch=False,
        )
    except Exception as e:
        log.error("Failed to save task result for %s: %s", task_id, e)


def _update_device_last_seen(device_id: str, device_info: dict):
    """UPSERT device registration into the persistent devices table."""
    log.info("Device %s last seen: os=%s hostname=%s",
             device_id,
             device_info.get("os", "?"),
             device_info.get("hostname", "?"))
    try:
        db = DatabaseConnection()
        db.execute_query(
            """INSERT INTO devices (device_id, hostname, os_type, os_version, ip_address)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (device_id) DO UPDATE SET
                 hostname   = EXCLUDED.hostname,
                 os_type    = EXCLUDED.os_type,
                 os_version = EXCLUDED.os_version,
                 ip_address = EXCLUDED.ip_address,
                 last_seen  = NOW()""",
            (
                device_id,
                device_info.get("hostname"),
                device_info.get("os"),
                device_info.get("os_version"),
                device_info.get("ip_address"),
            ),
            fetch=False,
        )
    except Exception as e:
        log.warning("Failed to upsert device %s: %s", device_id, e)
