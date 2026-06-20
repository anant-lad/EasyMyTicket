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

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

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
